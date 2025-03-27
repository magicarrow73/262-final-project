"""
ft_server_grpc.py

This script defines a fault-tolerant gRPC server for a chat service using 
Raft consensus to replicate state across multiple servers. It can tolerate 
up to f node failures in a 2f+1 node cluster.
"""

import threading
import queue
import grpc
from concurrent import futures
import argparse
import os
import time
import signal
import sys

import chat_pb2
import chat_pb2_grpc
from raft_db import RaftDB
from utils import verify_password

SERVER_LOG_FILE = "server_data_usage.log"

def log_data_usage(method_name: str, request_size: int, response_size: int):
    """
    Log the data usage (request size, response size) for each gRPC call
    to a local CSV file for analytical or monitoring purposes.

    :param method_name: Name of the gRPC method (e.g. "CreateUser", "Login", etc.).
    :param request_size: The byte size of the serialized gRPC request.
    :param response_size: The byte size of the serialized gRPC response.
    """
    file_exists = os.path.exists(SERVER_LOG_FILE)
    if not file_exists:
        with open(SERVER_LOG_FILE, "w") as f:
            f.write("method_name,request_size,response_size\n")

    with open(SERVER_LOG_FILE, "a") as f:
        f.write(f"{method_name},{request_size},{response_size}\n")

class FaultTolerantChatServicer(chat_pb2_grpc.ChatServiceServicer):
    """
    Implements the ChatService gRPC service methods with fault tolerance
    through Raft consensus. The server state is replicated across a cluster,
    ensuring consistency even if some nodes fail.
    """

    def __init__(self, raft_db):
        """
        Constructor for FaultTolerantChatServicer.

        :param raft_db: An instance of RaftDB for replicated state operations.
        """
        super().__init__()
        self.raft_db = raft_db
        
        # Structures for push notifications
        self.subscribers = {}
        self.subscribers_lock = threading.Lock()

    def add_subscriber(self, username):
        """
        Create a subscription queue for a user if one does not already exist.

        :param username: The username for which to create a subscription queue.
        """
        with self.subscribers_lock:
            if username not in self.subscribers:
                self.subscribers[username] = queue.Queue()

    def remove_subscriber(self, username):
        """
        Remove the subscription queue for a user if it exists.

        :param username: The username whose subscription queue should be removed.
        """
        with self.subscribers_lock:
            if username in self.subscribers:
                del self.subscribers[username]

    def push_incoming_message(self, receiver_username, sender, content):
        """
        Push an incoming message into the receiver's subscription queue.

        :param receiver_username: The username of the message receiver.
        :param sender: The username of the message sender.
        :param content: The text content of the message.
        """
        with self.subscribers_lock:
            if receiver_username in self.subscribers:
                q = self.subscribers[receiver_username]
                q.put((sender, content))

    # ------------------ RPC Methods with Data Usage Logging ------------------

    def CreateUser(self, request, context):
        """
        RPC method to create a new user. Enforced via Raft consensus.

        :param request: A CreateUserRequest containing username, hashed_password, and display_name.
        :param context: gRPC context, can be used for metadata or cancellations.
        :return: CreateUserResponse indicating success or failure (user exists, DB error, etc.).
        """
        req_size = len(request.SerializeToString())

        username = request.username
        hashed_password = request.hashed_password
        display_name = request.display_name

        # Check if user already exists (read operation doesn't need consensus)
        existing_user = self.raft_db.get_user_by_username(username)
        if existing_user is not None:
            resp = chat_pb2.CreateUserResponse(
                status="user_exists",
                message=f"User '{username}' already exists.",
                username=username
            )
            resp_size = len(resp.SerializeToString())
            log_data_usage("CreateUser", req_size, resp_size)
            return resp
        
        if not self.raft_db.isReady():
            # Block until ready
            self.raft_db.waitReady()

        # Create user (this is a replicated operation)
        success = self.raft_db.create_user(username, hashed_password, display_name, sync=True, timeout=20.0)
        
        if not success:
            resp = chat_pb2.CreateUserResponse(
                status="error",
                message="Could not create user (DB error or timeout).",
                username=username
            )
            resp_size = len(resp.SerializeToString())
            log_data_usage("CreateUser", req_size, resp_size)
            return resp

        resp = chat_pb2.CreateUserResponse(
            status="success",
            message="User created successfully.",
            username=username
        )

        resp_size = len(resp.SerializeToString())
        log_data_usage("CreateUser", req_size, resp_size)
        return resp

    def Login(self, request, context):
        """
        RPC method to log in an existing user with hashed password verification.
        Mark the user as active in the Raft cluster state.

        :param request: A LoginRequest containing username and hashed_password.
        :param context: gRPC context.
        :return: LoginResponse indicating success (with unread_count) or failure (error message).
        """
        req_size = len(request.SerializeToString())

        username = request.username
        hashed_password = request.hashed_password

        # 1) DEBUG: Check Raft status
        status = self.raft_db.getStatus()
        if status is not None:
            state = status.get('state')
            leader = status.get('leader')
            print(f"[DEBUG] getStatus() => state={state}, known_leader={leader}")
        else:
            print("[DEBUG] getStatus() returned None (node might not be ready)")

        # 2) Check if cluster is 'ready'
        if not self.raft_db.isReady():
            print("[DEBUG] Database not fully ready yet. Waiting...")
            self.raft_db.waitReady()
            print("[DEBUG] Done waiting for readiness")

        # Get user (read-only operation)
        user = self.raft_db.get_user_by_username(username)
        if not user:
            resp = chat_pb2.LoginResponse(
                status="error",
                message="User not found.",
                unread_count=0,
                username=username
            )
            resp_size = len(resp.SerializeToString())
            log_data_usage("Login", req_size, resp_size)
            return resp

        if not verify_password(hashed_password, user["password_hash"]):
            resp = chat_pb2.LoginResponse(
                status="error",
                message="Incorrect password.",
                unread_count=0,
                username=username
            )
            resp_size = len(resp.SerializeToString())
            log_data_usage("Login", req_size, resp_size)
            return resp
        
        # ---------------------------------------------------------
        # (A) Synchronous Raft replication with a 5s timeout
        # ---------------------------------------------------------
        result = self.raft_db.user_login(username, sync=True, timeout=20.0)
        if result is None:
            print("[DEBUG] user_login(...) returned None => possibly forwarding or replication timed out.")
            # Possibly we're on a follower and didn't get the final result,
            # or replication took >5s. Let's do a fallback read:
            time.sleep(0.5)
            if self.raft_db.is_user_active(username):
                # The cluster eventually marked user as active
                print("[DEBUG] Fallback read: user is actually active now, so let's treat it as success.")
                result = True
            else:
                print("[DEBUG] Fallback read: user still inactive, final failure.")
                result = None  # Confirmed not active

        if not result:
            # This means replication timed out or failed
            resp = chat_pb2.LoginResponse(
                status="error",
                message="Login replication failed or timed out.",
                unread_count=0,
                username=username
            )
            resp_size = len(resp.SerializeToString())
            log_data_usage("Login", req_size, resp_size)
            return resp

        unread_count = self.raft_db.get_num_unread_messages(username)
        resp = chat_pb2.LoginResponse(
            status="success",
            message="Login successful.",
            unread_count=unread_count,
            username=username
        )
        
        resp_size = len(resp.SerializeToString())
        log_data_usage("Login", req_size, resp_size)
        return resp

    def Logout(self, request, context):
        """
        RPC method to log out a currently active user.

        :param request: A LogoutRequest containing the username.
        :param context: gRPC context.
        :return: LogoutResponse indicating success or failure.
        """
        req_size = len(request.SerializeToString())

        username = request.username
        
        # Check if user is active
        if not self.raft_db.is_user_active(username):
            resp = chat_pb2.LogoutResponse(
                status="error",
                message="User is not logged in."
            )
            resp_size = len(resp.SerializeToString())
            log_data_usage("Logout", req_size, resp_size)
            return resp
        
        if not self.raft_db.isReady():
            # Block until ready
            self.raft_db.waitReady()
        
        # Logout user (replicated operation)
        success = self.raft_db.user_logout(username,sync=True,timeout=20.0)

        if not success:
            resp = chat_pb2.LogoutResponse(
                status="error",
                message="Logout replication failed or timed out."
            )
            return resp

        self.remove_subscriber(username)
        resp = chat_pb2.LogoutResponse(
            status="success",
            message=f"User {username} is now logged out."
        )
        
        resp_size = len(resp.SerializeToString())
        log_data_usage("Logout", req_size, resp_size)
        return resp

    def ListUsers(self, request, context):
        """
        RPC method to list users that match a given pattern (wildcards allowed).

        :param request: A ListUsersRequest containing username (caller) and pattern.
        :param context: gRPC context.
        :return: ListUsersResponse with a list of matching users, or error if caller not logged in.
        """
        req_size = len(request.SerializeToString())

        username = request.username
        
        # Check if user is active
        if not self.raft_db.is_user_active(username):
            resp = chat_pb2.ListUsersResponse(
                status="error",
                message="You are not logged in.",
                pattern=request.pattern
            )
            resp_size = len(resp.SerializeToString())
            log_data_usage("ListUsers", req_size, resp_size)
            return resp

        # List users (read-only operation)
        pat = request.pattern or "*"
        results = self.raft_db.list_users(pat)
        
        user_infos = []
        for (u, disp) in results:
            user_infos.append(chat_pb2.UserInfo(username=u, display_name=disp))

        resp = chat_pb2.ListUsersResponse(
            status="success",
            message=f"Found {len(user_infos)} user(s).",
            users=user_infos,
            pattern=pat
        )
        resp_size = len(resp.SerializeToString())
        log_data_usage("ListUsers", req_size, resp_size)
        return resp

    def SendMessage(self, request, context):
        """
        RPC method to send a message from sender to receiver.

        :param request: A SendMessageRequest containing sender, receiver, and content.
        :param context: gRPC context.
        :return: SendMessageResponse indicating success or failure.
        """
        req_size = len(request.SerializeToString())

        sender = request.sender
        receiver = request.receiver
        content = request.content

        # Check if sender is active
        if not self.raft_db.is_user_active(sender):
            resp = chat_pb2.SendMessageResponse(
                status="error",
                message="Sender is not logged in."
            )
            resp_size = len(resp.SerializeToString())
            log_data_usage("SendMessage", req_size, resp_size)
            return resp
        
        if not self.raft_db.isReady():
            # Block until ready
            self.raft_db.waitReady()

        # Send message (replicated operation)
        success = self.raft_db.create_message(
            sender, receiver, content,
            sync=True, timeout=20.0
        )

        if not success:
            resp = chat_pb2.SendMessageResponse(
                status="error",
                message="Could not send message (DB error or timeout)."
            )
            resp_size = len(resp.SerializeToString())
            log_data_usage("SendMessage", req_size, resp_size)
            return resp
        
        self.push_incoming_message(receiver, sender, content)
        resp = chat_pb2.SendMessageResponse(
            status="success",
            message="Message sent."
        )
        
        resp_size = len(resp.SerializeToString())
        log_data_usage("SendMessage", req_size, resp_size)
        return resp

    def ReadMessages(self, request, context):
        """
        RPC method to retrieve messages for the current user and mark them as read.

        :param request: A ReadMessagesRequest containing username, only_unread, and limit.
        :param context: gRPC context.
        :return: ReadMessagesResponse with a list of messages and status.
        """
        req_size = len(request.SerializeToString())

        username = request.username
        only_unread = request.only_unread
        limit = request.limit if request.limit > 0 else None

        # Check if user is active
        if not self.raft_db.is_user_active(username):
            resp = chat_pb2.ReadMessagesResponse(
                status="error",
                message="User not logged in.",
                messages=[]
            )
            resp_size = len(resp.SerializeToString())
            log_data_usage("ReadMessages", req_size, resp_size)
            return resp

        # Get messages (read-only operation)
        msgs_db = self.raft_db.get_messages_for_user(username, only_unread=only_unread, limit=limit)

        if not self.raft_db.isReady():
            # Block until ready
            self.raft_db.waitReady()
        
        # Mark messages as read (replicated operation)
        all_marked = True
        for m in msgs_db:
            result = self.raft_db.mark_message_read(
                m["id"], username,
                sync=True, timeout=20.0
            )
            if not result:
                all_marked = False

        # Build response
        msg_list = []
        for row in msgs_db:
            msg_list.append(chat_pb2.ChatMessage(
                id=row["id"],
                sender_username=row["sender_username"],
                content=row["content"],
                timestamp=row["timestamp"],
                read_status=row["read_status"],
            ))

        if all_marked:
            status = "success"
            message = f"Retrieved {len(msg_list)} messages."
        else:
            status = "partial_success"
            message = f"Retrieved {len(msg_list)} messages, but some messages could not be marked as read."

        resp = chat_pb2.ReadMessagesResponse(
            status=status,
            message=message,
            messages=msg_list
        )
        resp_size = len(resp.SerializeToString())
        log_data_usage("ReadMessages", req_size, resp_size)
        return resp

    def DeleteMessages(self, request, context):
        """
        RPC method to delete one or more messages if the user is either the sender or the receiver.

        :param request: A DeleteMessagesRequest containing username and a list of message_ids.
        :param context: gRPC context.
        :return: DeleteMessagesResponse indicating the number of messages successfully deleted.
        """
        req_size = len(request.SerializeToString())

        username = request.username
        
        # Check if user is active
        if not self.raft_db.is_user_active(username):
            resp = chat_pb2.DeleteMessagesResponse(
                status="error",
                message="User not logged in.",
                deleted_count=0
            )
            resp_size = len(resp.SerializeToString())
            log_data_usage("DeleteMessages", req_size, resp_size)
            return resp
        
        if not self.raft_db.isReady():
            # Block until ready
            self.raft_db.waitReady()

        # Delete messages (replicated operations)
        deleted_count = 0
        for mid in request.message_ids:
            result = self.raft_db.delete_message(
                mid, username,
                sync=True, timeout=20.0
            )
            if result:
                deleted_count += 1

        if deleted_count == 0:
            resp = chat_pb2.DeleteMessagesResponse(
                status="error",
                message="No messages deleted.",
                deleted_count=0
            )
        else:
            resp = chat_pb2.DeleteMessagesResponse(
                status="success",
                message=f"Deleted {deleted_count} messages.",
                deleted_count=deleted_count
            )

        resp_size = len(resp.SerializeToString())
        log_data_usage("DeleteMessages", req_size, resp_size)
        return resp

    def DeleteUser(self, request, context):
        """
        RPC method to delete the current user from the database, along with their messages.

        :param request: A DeleteUserRequest containing the username.
        :param context: gRPC context.
        :return: DeleteUserResponse indicating success or failure.
        """
        req_size = len(request.SerializeToString())

        username = request.username
        
        # Check if user is active
        if not self.raft_db.is_user_active(username):
            resp = chat_pb2.DeleteUserResponse(
                status="error",
                message="You are not logged in."
            )
            resp_size = len(resp.SerializeToString())
            log_data_usage("DeleteUser", req_size, resp_size)
            return resp
        
        if not self.raft_db.isReady():
            # Block until ready
            self.raft_db.waitReady()

        # Delete user (replicated operation)
        success = self.raft_db.delete_user(
            username,
            sync=True,
            timeout=20.0
        )

        if not success:
            resp = chat_pb2.DeleteUserResponse(
                status="error",
                message="User not found or DB error (or timed out)."
            )
            return resp
        
        self.remove_subscriber(username)
        resp = chat_pb2.DeleteUserResponse(
            status="success",
            message=f"User {username} deleted."
        )

        resp_size = len(resp.SerializeToString())
        log_data_usage("DeleteUser", req_size, resp_size)
        return resp

    def Subscribe(self, request, context):
        """
        Streaming RPC that yields messages to the user in real-time. The user must be active
        (logged in) to receive messages. As soon as they disconnect (context ends),
        the subscription is removed.

        :param request: A SubscribeRequest containing the username.
        :param context: gRPC context.
        :return: A generator of IncomingMessage objects (streamed via gRPC).
        """
        username = request.username
        
        # Check if user is active
        if not self.raft_db.is_user_active(username):
            return

        # Add to subscribers (local operation)
        self.add_subscriber(username)
        q = self.subscribers[username]

        # Stream messages
        try:
            while True:
                # Check if context is still active
                if context.is_active():
                    try:
                        # Get message with timeout to periodically check context
                        sender, content = q.get(block=True, timeout=1.0)
                        yield chat_pb2.IncomingMessage(sender=sender, content=content)
                    except queue.Empty:
                        # Just continue if no message is available
                        continue
                else:
                    # Context is no longer active, stop streaming
                    break
        except Exception:
            pass
        finally:
            # Ensure we clean up subscription
            self.remove_subscriber(username)

def run_server(host, port, node_id, raft_port, other_nodes=None):
    """
    Run a fault-tolerant chat server node. This sets up the RaftDB instance,
    starts the gRPC server, and periodically prints cluster debug info.

    :param host: The host/IP address to bind the gRPC server to.
    :param port: The port to bind the gRPC server to.
    :param node_id: Unique integer ID for this node in the cluster.
    :param raft_port: Port used for Raft consensus communication.
    :param other_nodes: List of other nodes in the format ["host:raft_port", ...].
                       Defaults to an empty list if None.
    """
    # Create Raft address for this node
    self_addr = f"{host}:{raft_port}"
    
    # Set up database with unique path for this node
    db_path = f"chat_node_{node_id}.db"

    print(f"[DEBUG] Starting node {node_id} at {host}:{port}, raft={host}:{raft_port}")
    print(f"[DEBUG] Other nodes: {other_nodes}")
    
    # Create RaftDB instance
    raft_db = RaftDB(self_addr, other_nodes or [], db_path)
    
    # Wait for initial Raft consensus
    time.sleep(5)  # Give Raft time to establish leadership

    def debug_print_cluster():
        """
        Continuously print debug information about the cluster's status,
        including leadership info, quorum presence, and partner nodes.
        """
        while True:
            time.sleep(5)
            status = raft_db.getStatus()
            if status is not None:
                # status is a dict containing various info like 'state', 'leader', 'has_quorum', etc.
                state_num = status.get('state')  # 0=follower, 1=candidate, 2=leader
                if state_num == 0:
                    role_str = "Follower"
                elif state_num == 1:
                    role_str = "Candidate"
                elif state_num == 2:
                    role_str = "Leader"
                else:
                    role_str = "Unknown"

                leader = status.get('leader')
                has_quorum = status.get('has_quorum')
                partner_count = status.get('partner_nodes_count', -1)

                print(f"[DEBUG] Node {node_id} => role={role_str}, leader={leader}, "
                      f"has_quorum={has_quorum}, partners={partner_count}")

                for k, v in status.items():
                    if 'partner_node_status_server_' in k:
                        print(f"    [DEBUG] {k} => {v}")
            else:
                print(f"[DEBUG] Node {node_id} => No status yet.")

    t = threading.Thread(target=debug_print_cluster, daemon=True)
    t.start()
    
    # Create gRPC server
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    
    # Add our servicer to the server
    servicer = FaultTolerantChatServicer(raft_db)
    chat_pb2_grpc.add_ChatServiceServicer_to_server(servicer, server)
    
    # Start listening
    server_addr = f"{host}:{port}"
    server.add_insecure_port(server_addr)
    server.start()

    print(f"[DEBUG] Node {node_id} started. Checking status...")
    print(f"[DEBUG] getStatus() => {raft_db.getStatus()}")
    
    print(f"Node {node_id} started at {server_addr} (Raft: {self_addr})")
    
    # Set up signal handlers for graceful shutdown
    def handle_shutdown(signum, frame):
        """
        Handle termination signals to gracefully stop the gRPC server and close the DB.
        """
        print(f"Node {node_id} shutting down...")
        raft_db.close()
        server.stop(5)  # 5 second grace period
        sys.exit(0)
    
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    # Keep the server running
    try:
        while True:
            time.sleep(3600)  # Sleep for an hour
    except KeyboardInterrupt:
        handle_shutdown(None, None)


def main():
    """
    Main entry point for the fault-tolerant gRPC chat server. Parses command-line 
    arguments and launches the server with the specified configuration.
    """
    parser = argparse.ArgumentParser(description="Fault-Tolerant gRPC Chat Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=50051, help="Port for gRPC server")
    parser.add_argument("--node-id", type=int, required=True, help="Unique node ID")
    parser.add_argument("--raft-port", type=int, default=50100, help="Base port for Raft consensus")
    parser.add_argument("--cluster", help="Comma-separated list of other nodes (host:raft_port)")
    args = parser.parse_args()
    
    # Parse cluster nodes
    other_nodes = []
    if args.cluster:
        other_nodes = args.cluster.split(",")

    
    time.sleep(5)
    
    # Run the server
    run_server(
        args.host, 
        args.port,
        args.node_id,
        args.raft_port,
        other_nodes
    )


if __name__ == "__main__":
    main()

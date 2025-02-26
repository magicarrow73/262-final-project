import threading
import queue
import grpc
from concurrent import futures
import argparse
import os

import chat_pb2
import chat_pb2_grpc

from db import (
    init_db, close_db, create_user, get_user_by_username, delete_user,
    create_message, list_users, get_messages_for_user,
    mark_message_read, delete_message, get_num_unread_messages
)
from utils import verify_password

SERVER_LOG_FILE = "server_data_usage.log"

def log_data_usage(method_name: str, request_size: int, response_size: int):
    """
    Append data usage (req_size, resp_size) to a local file, with a header
    if the file does not exist yet.
    """
    file_exists = os.path.exists(SERVER_LOG_FILE)
    if not file_exists:
        with open(SERVER_LOG_FILE, "w") as f:
            f.write("method_name,request_size,response_size\n")

    with open(SERVER_LOG_FILE, "a") as f:
        f.write(f"{method_name},{request_size},{response_size}\n")

class ChatServiceServicer(chat_pb2_grpc.ChatServiceServicer):
    def __init__(self):
        super().__init__()
        self.active_users = {}
        self.lock = threading.Lock()

        self.subscribers = {}
        self.subscribers_lock = threading.Lock()

    def add_subscriber(self, username):
        with self.subscribers_lock:
            if username not in self.subscribers:
                self.subscribers[username] = queue.Queue()

    def remove_subscriber(self, username):
        with self.subscribers_lock:
            if username in self.subscribers:
                del self.subscribers[username]

    def push_incoming_message(self, receiver_username, sender, content):
        with self.subscribers_lock:
            if receiver_username in self.subscribers:
                q = self.subscribers[receiver_username]
                q.put((sender, content))

    # ------------------ RPC Methods with Data Usage Logging ------------------

    def CreateUser(self, request, context):
        req_size = len(request.SerializeToString())

        username = request.username
        hashed_password = request.hashed_password
        display_name = request.display_name

        existing_user = get_user_by_username(username)
        if existing_user is not None:
            resp = chat_pb2.CreateUserResponse(
                status="user_exists",
                message=f"User '{username}' already exists.",
                username=username
            )
            resp_size = len(resp.SerializeToString())
            log_data_usage("CreateUser", req_size, resp_size)
            return resp

        success = create_user(username, hashed_password, display_name)
        if success:
            resp = chat_pb2.CreateUserResponse(
                status="success",
                message="User created successfully.",
                username=username
            )
        else:
            resp = chat_pb2.CreateUserResponse(
                status="error",
                message="Could not create user (DB error?).",
                username=username
            )

        resp_size = len(resp.SerializeToString())
        log_data_usage("CreateUser", req_size, resp_size)
        return resp

    def Login(self, request, context):
        req_size = len(request.SerializeToString())

        username = request.username
        hashed_password = request.hashed_password

        user = get_user_by_username(username)
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

        with self.lock:
            self.active_users[username] = True

        unread_count = get_num_unread_messages(username)
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
        req_size = len(request.SerializeToString())

        username = request.username
        with self.lock:
            if username not in self.active_users:
                resp = chat_pb2.LogoutResponse(
                    status="error",
                    message="User is not logged in."
                )
                resp_size = len(resp.SerializeToString())
                log_data_usage("Logout", req_size, resp_size)
                return resp
            del self.active_users[username]

        self.remove_subscriber(username)
        resp = chat_pb2.LogoutResponse(
            status="success",
            message=f"User {username} is now logged out."
        )
        resp_size = len(resp.SerializeToString())
        log_data_usage("Logout", req_size, resp_size)
        return resp

    def ListUsers(self, request, context):
        req_size = len(request.SerializeToString())

        username = request.username
        with self.lock:
            if username not in self.active_users:
                resp = chat_pb2.ListUsersResponse(
                    status="error",
                    message="You are not logged in.",
                    pattern=request.pattern
                )
                resp_size = len(resp.SerializeToString())
                log_data_usage("ListUsers", req_size, resp_size)
                return resp

        pat = request.pattern or "*"
        results = list_users(pat)
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
        req_size = len(request.SerializeToString())

        sender = request.sender
        receiver = request.receiver
        content = request.content

        with self.lock:
            if sender not in self.active_users:
                resp = chat_pb2.SendMessageResponse(
                    status="error",
                    message="Sender is not logged in."
                )
                resp_size = len(resp.SerializeToString())
                log_data_usage("SendMessage", req_size, resp_size)
                return resp

        success = create_message(sender, receiver, content)
        if not success:
            resp = chat_pb2.SendMessageResponse(
                status="error",
                message="Could not send message. (Maybe receiver does not exist?)"
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
        req_size = len(request.SerializeToString())

        username = request.username
        only_unread = request.only_unread
        limit = request.limit if request.limit > 0 else None

        with self.lock:
            if username not in self.active_users:
                resp = chat_pb2.ReadMessagesResponse(
                    status="error",
                    message="User not logged in.",
                    messages=[]
                )
                resp_size = len(resp.SerializeToString())
                log_data_usage("ReadMessages", req_size, resp_size)
                return resp

        msgs_db = get_messages_for_user(username, only_unread=only_unread, limit=limit)
        for m in msgs_db:
            mark_message_read(m["id"], username)

        msg_list = []
        for row in msgs_db:
            msg_list.append(chat_pb2.ChatMessage(
                id=row["id"],
                sender_username=row["sender_username"],
                content=row["content"],
                timestamp=row["timestamp"],
                read_status=row["read_status"],
            ))

        resp = chat_pb2.ReadMessagesResponse(
            status="success",
            message=f"Retrieved {len(msg_list)} messages.",
            messages=msg_list
        )
        resp_size = len(resp.SerializeToString())
        log_data_usage("ReadMessages", req_size, resp_size)
        return resp

    def DeleteMessages(self, request, context):
        req_size = len(request.SerializeToString())

        username = request.username
        with self.lock:
            if username not in self.active_users:
                resp = chat_pb2.DeleteMessagesResponse(
                    status="error",
                    message="User not logged in.",
                    deleted_count=0
                )
                resp_size = len(resp.SerializeToString())
                log_data_usage("DeleteMessages", req_size, resp_size)
                return resp

        deleted_count = 0
        for mid in request.message_ids:
            if delete_message(mid, username):
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
        req_size = len(request.SerializeToString())

        username = request.username
        with self.lock:
            if username not in self.active_users:
                resp = chat_pb2.DeleteUserResponse(
                    status="error",
                    message="You are not logged in."
                )
                resp_size = len(resp.SerializeToString())
                log_data_usage("DeleteUser", req_size, resp_size)
                return resp

        success = delete_user(username)
        if success:
            with self.lock:
                if username in self.active_users:
                    del self.active_users[username]
            self.remove_subscriber(username)
            resp = chat_pb2.DeleteUserResponse(
                status="success",
                message=f"User {username} deleted."
            )
        else:
            resp = chat_pb2.DeleteUserResponse(
                status="error",
                message="User not found or DB error."
            )

        resp_size = len(resp.SerializeToString())
        log_data_usage("DeleteUser", req_size, resp_size)
        return resp

    def Subscribe(self, request, context):
        # We'll omit data usage measurement for streaming.
        username = request.username
        with self.lock:
            if username not in self.active_users:
                return

        self.add_subscriber(username)
        q = self.subscribers[username]

        while True:
            try:
                sender, content = q.get(block=True)
                yield chat_pb2.IncomingMessage(sender=sender, content=content)
            except Exception:
                break

def main():
    parser = argparse.ArgumentParser(description="Start gRPC chat server.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host (interface) to bind to, e.g. 0.0.0.0 or 127.0.0.1")
    parser.add_argument("--port", type=int, default=12345,
                        help="Port to bind the server on.")
    args = parser.parse_args()

    init_db()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServiceServicer_to_server(
        ChatServiceServicer(), server
    )

    address = f"{args.host}:{args.port}"
    server.add_insecure_port(address)
    server.start()
    print(f"gRPC server started on {address}")
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("Shutting down gRPC server.")
    finally:
        close_db()

if __name__ == "__main__":
    main()

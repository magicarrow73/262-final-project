import threading
import queue
import grpc
from concurrent import futures

import chat_pb2
import chat_pb2_grpc

from db import (
    init_db, close_db, create_user, get_user_by_username, delete_user,
    create_message, list_users, get_messages_for_user,
    mark_message_read, delete_message, get_num_unread_messages
)
from utils import verify_password

class ChatServiceServicer(chat_pb2_grpc.ChatServiceServicer):
    def __init__(self):
        super().__init__()
        # Keep track of which users are "logged in".
        # E.g. active_users[username] = True
        self.active_users = {}
        self.lock = threading.Lock()

        # For push notifications, we'll store a dictionary:
        #   subscribers[username] = queue.Queue() 
        # so that the Subscribe() RPC can yield new messages from that queue.
        self.subscribers = {}
        self.subscribers_lock = threading.Lock()

    # ------------------ Utility Methods for Subscriptions ------------------

    def add_subscriber(self, username):
        """Create a subscription queue for a user, if not already existing."""
        with self.subscribers_lock:
            if username not in self.subscribers:
                self.subscribers[username] = queue.Queue()

    def remove_subscriber(self, username):
        """Remove subscription queue (if user unsubscribes/logs out)."""
        with self.subscribers_lock:
            if username in self.subscribers:
                del self.subscribers[username]

    def push_incoming_message(self, receiver_username, sender, content):
        """
        If receiver is subscribed, push a new message to their queue
        so that the streaming Subscribe() method can yield it.
        """
        with self.subscribers_lock:
            if receiver_username in self.subscribers:
                q = self.subscribers[receiver_username]
                q.put((sender, content))  # a tuple

    # ------------------ RPC Implementations ------------------

    def CreateUser(self, request, context):
        username = request.username
        hashed_password = request.hashed_password
        display_name = request.display_name

        existing_user = get_user_by_username(username)
        if existing_user is not None:
            return chat_pb2.CreateUserResponse(
                status="user_exists",
                message=f"User '{username}' already exists.",
                username=username
            )

        success = create_user(username, hashed_password, display_name)
        if success:
            return chat_pb2.CreateUserResponse(
                status="success",
                message="User created successfully.",
                username=username
            )
        else:
            return chat_pb2.CreateUserResponse(
                status="error",
                message="Could not create user (DB error?).",
                username=username
            )

    def Login(self, request, context):
        username = request.username
        hashed_password = request.hashed_password

        user = get_user_by_username(username)
        if not user:
            return chat_pb2.LoginResponse(
                status="error",
                message="User not found.",
                unread_count=0,
                username=username
            )
        if not verify_password(hashed_password, user["password_hash"]):
            return chat_pb2.LoginResponse(
                status="error",
                message="Incorrect password.",
                unread_count=0,
                username=username
            )

        with self.lock:
            self.active_users[username] = True

        unread_count = get_num_unread_messages(username)
        return chat_pb2.LoginResponse(
            status="success",
            message="Login successful.",
            unread_count=unread_count,
            username=username
        )

    def Logout(self, request, context):
        username = request.username
        with self.lock:
            if username not in self.active_users:
                return chat_pb2.LogoutResponse(
                    status="error",
                    message="User is not logged in."
                )
            del self.active_users[username]

        # Also remove subscription queue for push notifications
        self.remove_subscriber(username)
        return chat_pb2.LogoutResponse(
            status="success",
            message=f"User {username} is now logged out."
        )

    def ListUsers(self, request, context):
        # verify user is logged in
        username = request.username
        with self.lock:
            if username not in self.active_users:
                return chat_pb2.ListUsersResponse(
                    status="error",
                    message="You are not logged in.",
                    pattern=request.pattern
                )

        pat = request.pattern or "*"
        results = list_users(pat)
        user_infos = []
        for (u, disp) in results:
            user_infos.append(chat_pb2.UserInfo(username=u, display_name=disp))

        return chat_pb2.ListUsersResponse(
            status="success",
            message=f"Found {len(user_infos)} user(s).",
            users=user_infos,
            pattern=pat
        )

    def SendMessage(self, request, context):
        sender = request.sender
        receiver = request.receiver
        content = request.content

        # check if sender is logged in
        with self.lock:
            if sender not in self.active_users:
                return chat_pb2.SendMessageResponse(
                    status="error",
                    message="Sender is not logged in."
                )

        success = create_message(sender, receiver, content)
        if not success:
            return chat_pb2.SendMessageResponse(
                status="error",
                message="Could not send message. (Maybe receiver does not exist?)"
            )

        # If the receiver is subscribed, push a real-time message:
        self.push_incoming_message(receiver, sender, content)

        return chat_pb2.SendMessageResponse(
            status="success",
            message="Message sent."
        )

    def ReadMessages(self, request, context):
        username = request.username
        only_unread = request.only_unread
        limit = request.limit if request.limit > 0 else None

        with self.lock:
            if username not in self.active_users:
                return chat_pb2.ReadMessagesResponse(
                    status="error",
                    message="User not logged in.",
                    messages=[]
                )

        msgs_db = get_messages_for_user(username, only_unread=only_unread, limit=limit)

        # Mark them read:
        for m in msgs_db:
            mark_message_read(m["id"], username)

        msg_list = []
        for row in msgs_db:
            msg_list.append(
                chat_pb2.ChatMessage(
                    id=row["id"],
                    sender_username=row["sender_username"],
                    content=row["content"],
                    timestamp=row["timestamp"],
                    read_status=row["read_status"],
                )
            )

        return chat_pb2.ReadMessagesResponse(
            status="success",
            message=f"Retrieved {len(msg_list)} messages.",
            messages=msg_list
        )

    def DeleteMessages(self, request, context):
        username = request.username
        with self.lock:
            if username not in self.active_users:
                return chat_pb2.DeleteMessagesResponse(
                    status="error",
                    message="User not logged in.",
                    deleted_count=0
                )

        deleted_count = 0
        for mid in request.message_ids:
            if delete_message(mid, username):
                deleted_count += 1

        if deleted_count == 0:
            return chat_pb2.DeleteMessagesResponse(
                status="error",
                message="No messages deleted.",
                deleted_count=0
            )
        else:
            return chat_pb2.DeleteMessagesResponse(
                status="success",
                message=f"Deleted {deleted_count} messages.",
                deleted_count=deleted_count
            )

    def DeleteUser(self, request, context):
        username = request.username
        with self.lock:
            if username not in self.active_users:
                return chat_pb2.DeleteUserResponse(
                    status="error",
                    message="You are not logged in."
                )

        success = delete_user(username)
        if success:
            # remove from active users
            with self.lock:
                if username in self.active_users:
                    del self.active_users[username]
            # remove subscription
            self.remove_subscriber(username)
            return chat_pb2.DeleteUserResponse(
                status="success",
                message=f"User {username} deleted."
            )
        else:
            return chat_pb2.DeleteUserResponse(
                status="error",
                message="User not found or DB error."
            )

    def Subscribe(self, request, context):
        """
        Server-streaming method for push notifications. We block,
        waiting for new messages from the queue, then yield them to the client.
        """
        username = request.username
        # Check if user is logged in
        with self.lock:
            if username not in self.active_users:
                # Immediately return, no streaming
                return

        # Create (or reuse) a queue for this user
        self.add_subscriber(username)
        q = self.subscribers[username]

        # Continuously yield new messages from the queue:
        while True:
            try:
                # If the client cancels the RPC, this will raise an exception
                sender, content = q.get(block=True)
                yield chat_pb2.IncomingMessage(sender=sender, content=content)
            except Exception as e:
                break  # if there's an error or cancellation, end the stream

def serve():
    init_db()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServiceServicer_to_server(ChatServiceServicer(), server)
    server.add_insecure_port("[::]:12345")
    server.start()
    print("gRPC server started on port 12345.")
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("Shutting down gRPC server.")
    finally:
        close_db()

if __name__ == "__main__":
    serve()

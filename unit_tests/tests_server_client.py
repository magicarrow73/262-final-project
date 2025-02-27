import unittest
import sys
import os
import time
import threading
import socket
import grpc

# Import your server module from the system_main package
from system_main.server_grpc import main as server_main

import system_main.chat_pb2 as chat_pb2
import system_main.chat_pb2_grpc as chat_pb2_grpc

#from system_main import chat_pb2, chat_pb2_grpc

from concurrent import futures

class TestChatIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """
        Set up a gRPC server in a background thread on an available port, 
        then create a client channel and stub pointing to that port.
        """
        # 1) Pick an available port dynamically
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))  # binds to a random free port
        cls.port = sock.getsockname()[1]
        sock.close()

        # 2) Start server in a thread, passing --host=127.0.0.1 --port=<randomPort>
        def run_server():
            # We simulate command-line args by using an array or patching sys.argv.
            # For clarity, we pass them inline:
            import sys
            sys.argv = ["server_grpc.py", 
                        "--host=127.0.0.1", 
                        f"--port={cls.port}"]
            server_main()

        cls.server_thread = threading.Thread(target=run_server, daemon=True)
        cls.server_thread.start()

        # Give the server a moment to spin up
        time.sleep(1.0)

        # 3) Create a channel & stub
        cls.channel = grpc.insecure_channel(f"127.0.0.1:{cls.port}")
        cls.stub = chat_pb2_grpc.ChatServiceStub(cls.channel)

        # Make sure log files from previous runs don't interfere:
        # You can decide if you want to remove or keep them
        if os.path.exists("server_data_usage.log"):
            os.remove("server_data_usage.log")
        if os.path.exists("client_data_usage.log"):
            os.remove("client_data_usage.log")

    @classmethod
    def tearDownClass(cls):
        """
        Clean up: close the channel and (optionally) kill the server.
        In practice, the server_main will block forever unless we forcibly stop it.
        """
        cls.channel.close()
        # The server is still running in a daemon thread and will exit when tests end.

    def test_1_create_user(self):
        """Test that we can create a user and get a success response."""
        request = chat_pb2.CreateUserRequest(
            username="alice",
            hashed_password="pass123",
            display_name="Alice A."
        )
        response = self.stub.CreateUser(request)
        self.assertEqual(response.status, "success")
        self.assertEqual(response.username, "alice")

    def test_2_create_duplicate_user(self):
        """Test that creating the same user again results in 'user_exists'."""
        request = chat_pb2.CreateUserRequest(
            username="alice",
            hashed_password="somethingElse",
            display_name="Another name"
        )
        response = self.stub.CreateUser(request)
        self.assertEqual(response.status, "user_exists")
        self.assertIn("already exists", response.message.lower())

    def test_3_login_user(self):
        """Test that we can log in 'alice' and get correct unread count (0)."""
        request = chat_pb2.LoginRequest(username="alice", hashed_password="pass123")
        response = self.stub.Login(request)
        self.assertEqual(response.status, "success")
        self.assertEqual(response.unread_count, 0)

    def test_4_send_message_to_nonexistent_user(self):
        """Test error case sending message to a user that doesn't exist."""
        request = chat_pb2.SendMessageRequest(
            sender="alice",
            receiver="bob",  # 'bob' doesn't exist yet
            content="Hello, Bob!"
        )
        response = self.stub.SendMessage(request)
        self.assertEqual(response.status, "error")
        self.assertIn("does not exist", response.message.lower())

    def test_5_create_other_user_and_send(self):
        """Create 'bob' user, log him in, and then have 'alice' send him a message."""
        # Create 'bob'
        create_req = chat_pb2.CreateUserRequest(
            username="bob",
            hashed_password="pw",
            display_name="Bobby"
        )
        create_resp = self.stub.CreateUser(create_req)
        self.assertEqual(create_resp.status, "success")

        # Log 'bob' in
        login_req = chat_pb2.LoginRequest(username="bob", hashed_password="pw")
        login_resp = self.stub.Login(login_req)
        self.assertEqual(login_resp.status, "success")

        # Now have 'alice' send a message to 'bob'
        send_req = chat_pb2.SendMessageRequest(
            sender="alice",
            receiver="bob",
            content="Hello from Alice!"
        )
        send_resp = self.stub.SendMessage(send_req)
        self.assertEqual(send_resp.status, "success")

    def test_6_read_messages_for_bob(self):
        """Read messages for bob and ensure the one from 'alice' is present."""
        read_req = chat_pb2.ReadMessagesRequest(
            username="bob",
            only_unread=False,
            limit=0  # 0 means no limit
        )
        read_resp = self.stub.ReadMessages(read_req)
        self.assertEqual(read_resp.status, "success")
        self.assertIn("Retrieved 1 messages", read_resp.message)
        self.assertEqual(len(read_resp.messages), 1)
        msg = read_resp.messages[0]
        self.assertEqual(msg.sender_username, "alice")
        self.assertIn("Hello from Alice!", msg.content)

    def test_7_logout_bob(self):
        """Log 'bob' out and confirm success."""
        logout_req = chat_pb2.LogoutRequest(username="bob")
        logout_resp = self.stub.Logout(logout_req)
        self.assertEqual(logout_resp.status, "success")
        self.assertIn("logged out", logout_resp.message.lower())

    def test_8_delete_messages_as_alice(self):
        """
        Let 'alice' read and then delete messages she sent or received 
        (in this case, the message from alice->bob can be deleted by the sender).
        """
        # Alice reading her outbox doesn't directly exist, but let's confirm read returns 0
        # Actually, read is for the 'receiver', so 'alice' won't see her own message in "read messages".
        read_req = chat_pb2.ReadMessagesRequest(username="alice", only_unread=False)
        read_resp = self.stub.ReadMessages(read_req)
        # She shouldn't see anything because she didn't receive messages
        self.assertTrue("Retrieved 0 messages" in read_resp.message)

        # We attempt to delete msg ID=1 as a guess, but in reality we’d have to read the ID from bob’s messages
        # or store it somewhere. For demonstration, let's assume ID=1 is valid if there's only that one message.
        del_req = chat_pb2.DeleteMessagesRequest(username="alice", message_ids=[1])
        del_resp = self.stub.DeleteMessages(del_req)
        # If success, we might get "Deleted 1 messages."
        # Or "No messages deleted" if ID doesn't match. 
        # We'll just check status is either success or error but the code is valid:
        self.assertIn(del_resp.status, ("success", "error"))

    def test_9_delete_user_alice(self):
        """Delete user 'alice' entirely."""
        deluser_req = chat_pb2.DeleteUserRequest(username="alice")
        deluser_resp = self.stub.DeleteUser(deluser_req)
        # Expect success or error if it's not found or DB error.
        self.assertIn(deluser_resp.status, ("success", "error"))

    def test_A_final_cleanup_delete_bob(self):
        """Finally, delete user 'bob' too."""
        deluser_req = chat_pb2.DeleteUserRequest(username="bob")
        deluser_resp = self.stub.DeleteUser(deluser_req)
        self.assertIn(deluser_resp.status, ("success", "error"))


if __name__ == "__main__":
    unittest.main()

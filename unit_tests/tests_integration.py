import os
import unittest
import tempfile

from system_main import server_grpc
from system_main.server_grpc import ChatServiceServicer
from system_main.db import init_db, close_db, get_connection

import system_main.chat_pb2 as chat_pb2
import system_main.chat_pb2_grpc as chat_pb2_grpc
from system_main.server_grpc import main as server_main

class TestChatServiceServicer(unittest.TestCase):
    """
    Full tests for ChatServiceServicer methods, using a test DB.
    """
    @classmethod
    def setUpClass(cls):
        """
        Runs once before all tests in this class. Set up a test DB environment.
        """
        # If you want to isolate test DB, you can point to a temp file or in-memory DB
        # Option A: In-memory DB
        os.environ["CHAT_DB_PATH"] = ":memory:"
        # or Option B: Temporary on-disk file
        # cls.temp_db = tempfile.NamedTemporaryFile(delete=False)
        # os.environ["CHAT_DB_PATH"] = cls.temp_db.name

        # Now initialize DB
        init_db()

    @classmethod
    def tearDownClass(cls):
        """
        Runs once after all tests have finished. Clean up the DB.
        """
        close_db()
        # If you used a temporary file, optionally delete it here:
        # if hasattr(cls, 'temp_db'):
        #     os.remove(cls.temp_db.name)

    def setUp(self):
        """
        Runs before each test. Create a fresh ChatServiceServicer.
        """
        self.servicer = ChatServiceServicer()
        # If you want to ensure a fresh DB for every test, you might drop/recreate tables here.

    def tearDown(self):
        """
        Runs after each test. Could do additional cleanup if needed.
        """
        pass

    def test_create_user(self):
        """
        Test that CreateUser properly creates a new user and returns success.
        """
        request = chat_pb2.CreateUserRequest(
            username="alice",
            hashed_password="hash_of_pw",
            display_name="Alice In Wonderland"
        )
        response = self.servicer.CreateUser(request, None)
        self.assertEqual(response.status, "success", "Expected user creation to succeed.")
        self.assertEqual(response.username, "alice")

        # Try creating the same user again => should fail with 'user_exists'
        response2 = self.servicer.CreateUser(request, None)
        self.assertEqual(response2.status, "user_exists", "Creating the same user twice should fail.")

    def test_login(self):
        """
        Test that Login works after a user is created.
        """
        # Create a user first
        create_req = chat_pb2.CreateUserRequest(
            username="bob",
            hashed_password="pw123",
            display_name="Bobby"
        )
        self.servicer.CreateUser(create_req, None)

        # Now login
        login_req = chat_pb2.LoginRequest(username="bob", hashed_password="pw123")
        login_resp = self.servicer.Login(login_req, None)
        self.assertEqual(login_resp.status, "success", "Expected login to succeed.")
        self.assertEqual(login_resp.unread_count, 0, "Expected no unread messages for new user.")
        self.assertEqual(login_resp.username, "bob")

        # Incorrect password
        bad_login_req = chat_pb2.LoginRequest(username="bob", hashed_password="wrong")
        bad_login_resp = self.servicer.Login(bad_login_req, None)
        self.assertEqual(bad_login_resp.status, "error", "Wrong password should fail login.")

    def test_send_and_read_messages(self):
        """
        Test SendMessage and ReadMessages flow. 
        """
        # Create two users
        self.servicer.CreateUser(chat_pb2.CreateUserRequest(
            username="alice", hashed_password="pwA", display_name="Alice"
        ), None)
        self.servicer.CreateUser(chat_pb2.CreateUserRequest(
            username="bob", hashed_password="pwB", display_name="Bob"
        ), None)

        # Mark them as logged in in the server (like they've called Login)
        with self.servicer.lock:
            self.servicer.active_users["alice"] = True
            self.servicer.active_users["bob"] = True

        # Alice sends message to Bob
        send_req = chat_pb2.SendMessageRequest(
            sender="alice",
            receiver="bob",
            content="Hello Bob!"
        )
        send_resp = self.servicer.SendMessage(send_req, None)
        self.assertEqual(send_resp.status, "success", "Sending message should succeed.")

        # Bob reads messages
        read_req = chat_pb2.ReadMessagesRequest(
            username="bob",
            only_unread=False,  # get all messages
            limit=0             # 0 or none means no limit
        )
        read_resp = self.servicer.ReadMessages(read_req, None)
        self.assertEqual(read_resp.status, "success")
        self.assertGreaterEqual(len(read_resp.messages), 1, "Expected at least 1 message for Bob.")
        self.assertEqual(read_resp.messages[0].content, "Hello Bob!")

    def test_delete_user(self):
        """
        Test deleting a user. 
        """
        # Create and log in a user
        self.servicer.CreateUser(chat_pb2.CreateUserRequest(
            username="charlie", hashed_password="pwC", display_name="Charlie"
        ), None)
        with self.servicer.lock:
            self.servicer.active_users["charlie"] = True

        # Delete the user
        del_req = chat_pb2.DeleteUserRequest(username="charlie")
        del_resp = self.servicer.DeleteUser(del_req, None)
        self.assertEqual(del_resp.status, "success", "Deleting user should succeed.")

        # Attempt to login again => user not found
        login_req = chat_pb2.LoginRequest(username="charlie", hashed_password="pwC")
        login_resp = self.servicer.Login(login_req, None)
        self.assertEqual(login_resp.status, "error", "User should no longer exist after deletion.")


if __name__ == "__main__":
    unittest.main()

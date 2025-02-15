# tests2.py

import unittest
import os
import json
from unittest.mock import MagicMock, patch

# Make sure our database is in-memory so tests do not interfere with a real DB file
os.environ["CHAT_DB_PATH"] = ":memory:"

# Instead of importing TkClient and log_transfer directly, 
# we import the entire client module so we can reference module-level globals.
import system_main.client as client_module

from system_main.db import (
    init_db, close_db,
    get_user_by_username, create_user
)
from system_main.server import Server
from system_main.utils import hash_password

class TestServerCommandHandlers(unittest.TestCase):
    """
    Tests focusing on the Server class's command handler methods.
    We directly call methods like create_user_command, login_command, etc.
    using a mock socket to simulate a connected client.
    """
    def setUp(self):
        init_db()
        self.server = Server(protocol_type="json")
        self.mock_socket = MagicMock()

    def tearDown(self):
        close_db()

    def test_create_user_command_success(self):
        """
        Test that create_user_command returns 'success' if user does not already exist.
        """
        request = {
            "command": "create_user",
            "username": "alice",
            "hashed_password": hash_password("password123"),
            "display_name": "Alice Wonderland"
        }
        response = self.server.create_user_command(request, self.mock_socket)
        self.assertEqual(response["status"], "success")
        self.assertIn("User created successfully", response["message"])

        # Verify user is actually in the DB
        row = get_user_by_username("alice")
        self.assertIsNotNone(row)

    def test_create_user_command_user_exists(self):
        """
        Test that create_user_command returns 'user_exists' if username is taken.
        """
        # First, manually create the user
        create_user("bob", hash_password("pw"), "Bob Display")
        
        request = {
            "command": "create_user",
            "username": "bob",
            "hashed_password": hash_password("pw"),
            "display_name": "Bobby"
        }
        response = self.server.create_user_command(request, self.mock_socket)
        self.assertEqual(response["status"], "user_exists")
        self.assertIn("already exists", response["message"])

    def test_login_command_success(self):
        """
        Test that login_command returns success and unread_count when correct credentials are provided.
        """
        # Create user
        create_user("charlie", hash_password("charliepw"), "Charlie D.")
        
        request = {
            "command": "login",
            "username": "charlie",
            "hashed_password": hash_password("charliepw")
        }
        response = self.server.login_command(request, self.mock_socket)
        self.assertEqual(response["status"], "success")
        self.assertIn("Login successful", response["message"])
        # Should also return unread_count
        self.assertIn("unread_count", response)

        # Check that server's active_users got updated
        self.assertIn(self.mock_socket, self.server.active_users)
        self.assertEqual(self.server.active_users[self.mock_socket], "charlie")

    def test_login_command_user_not_found(self):
        """
        Test that login_command returns an error if user doesn't exist.
        """
        request = {
            "command": "login",
            "username": "nonexistent",
            "hashed_password": hash_password("whatever")
        }
        response = self.server.login_command(request, self.mock_socket)
        self.assertEqual(response["status"], "error")
        self.assertIn("User not found", response["message"])
        self.assertNotIn(self.mock_socket, self.server.active_users)

    def test_logout_command_success(self):
        """
        Test that logout_command removes the user from active_users.
        """
        # Setup: create a user, log them in
        create_user("david", hash_password("davidpw"), "David D.")
        self.server.active_users[self.mock_socket] = "david"

        # Now call logout
        request = {"command": "logout"}
        response = self.server.logout_command(request, self.mock_socket)
        self.assertEqual(response["status"], "success")
        self.assertIn("now logged out", response["message"])
        self.assertNotIn(self.mock_socket, self.server.active_users)

    def test_logout_command_not_logged_in(self):
        """
        Test that logout_command returns error if the user is not logged in.
        """
        request = {"command": "logout"}
        response = self.server.logout_command(request, self.mock_socket)
        self.assertEqual(response["status"], "error")
        self.assertIn("No user is currently logged in", response["message"])

    def test_list_users_command_not_logged_in(self):
        """
        Test that list_users_command returns an error if the socket is not associated with a logged-in user.
        """
        request = {"command": "list_users", "pattern": "*"}
        response = self.server.list_users_command(request, self.mock_socket)
        self.assertEqual(response["status"], "error")
        self.assertIn("You are not logged in", response["message"])

    def test_list_users_command_success(self):
        """
        Test that list_users_command returns a list of users when the socket is logged in.
        """
        # Create user who will be "logged in"
        create_user("eric", hash_password("ericpw"), "Eric E.")
        self.server.active_users[self.mock_socket] = "eric"

        # Create some other user so that there's something to list
        create_user("frank", hash_password("frankpw"), "Frank F.")

        request = {"command": "list_users", "pattern": "*"}
        response = self.server.list_users_command(request, self.mock_socket)
        self.assertEqual(response["status"], "success")
        self.assertIn("users", response)
        self.assertGreaterEqual(len(response["users"]), 1)  # Should see at least 'eric' and 'frank'

    def test_delete_user_command(self):
        """
        Test that a logged-in user can delete themselves.
        """
        create_user("greg", hash_password("gregpw"), "Greg G.")
        self.server.active_users[self.mock_socket] = "greg"

        response = self.server.delete_user_command(self.mock_socket)
        self.assertEqual(response["status"], "success")
        self.assertIn("deleted successfully", response["message"])

        # Check DB
        self.assertIsNone(get_user_by_username("greg"))

    def test_delete_user_command_not_logged_in(self):
        """
        Test that an un-logged user cannot delete an account.
        """
        response = self.server.delete_user_command(self.mock_socket)
        # The server returns a string or dict in some cases; we handle both
        if isinstance(response, dict):
            self.assertEqual(response["status"], "error")
        else:
            self.assertIn("not logged in", response.lower())


class TestClientLogic(unittest.TestCase):
    """
    Demonstrates how you might test some client-side functionality in a unit-test style.
    Note that Tkinter-based GUIs are harder to test thoroughly without integration tests,
    but we can at least test certain methods in isolation by mocking or bypassing the GUI parts.
    """
    def setUp(self):
        # Create an instance of TkClient from the client_module
        self.client = client_module.TkClient(host="fakehost", port=9999, use_json=True)
        # Instead of a real socket, we can mock
        self.client.sock = MagicMock()

    def test_send_line(self):
        """
        Test that send_line calls sock.sendall with the correct data.
        """
        test_string = "HELLO_SERVER"
        self.client.send_line(test_string)
        # Check that sock.sendall was called with 'HELLO_SERVER\n' encoded in utf-8
        expected_call = (test_string + "\n").encode('utf-8')
        self.client.sock.sendall.assert_called_with(expected_call)

    def test_send_json(self):
        """
        Test that send_json serializes an object to JSON and sends it with a newline.
        """
        obj = {"command": "ping", "payload": "test"}
        self.client.send_json(obj)
        # We expect something like '{"command": "ping", "payload": "test"}\n'
        sent_data = self.client.sock.sendall.call_args[0][0]
        sent_str = sent_data.decode('utf-8')
        self.assertTrue(sent_str.endswith("\n"))
        # Remove the trailing newline and parse back to dict
        sent_json = json.loads(sent_str.strip())
        self.assertEqual(sent_json, obj)

    def test_log_transfer_sent(self):
        """
        Test log_transfer function for 'sent' direction, referencing the client module's global counters.
        """
        with patch("builtins.open", new_callable=MagicMock):
            old_sent = client_module.CLIENT_TOTAL_SENT
            client_module.log_transfer(50, direction="sent")
            self.assertEqual(
                client_module.CLIENT_TOTAL_SENT,
                old_sent + 50
            )

    def test_log_transfer_received(self):
        """
        Test log_transfer function for 'received' direction, referencing the client module's global counters.
        """
        with patch("builtins.open", new_callable=MagicMock):
            old_received = client_module.CLIENT_TOTAL_RECEIVED
            client_module.log_transfer(100, direction="received")
            self.assertEqual(
                client_module.CLIENT_TOTAL_RECEIVED,
                old_received + 100
            )

    def test_handle_server_line_valid_json(self):
        """
        Test handle_server_line with a successful JSON response.
        We can mock self.log to see what gets logged to the text_area.
        """
        sample_response = {
            "status": "success",
            "message": "User created successfully."
        }
        with patch.object(self.client, 'log') as mock_log:
            line = json.dumps(sample_response)
            self.client.handle_server_line(line)
            # Check that mock_log was called with something like "[SUCCESS] User created successfully."
            mock_log.assert_any_call("[SUCCESS] User created successfully.")

    def test_handle_server_line_invalid_json(self):
        """
        Test handle_server_line with invalid JSON.
        """
        with patch.object(self.client, 'log') as mock_log:
            self.client.handle_server_line("NOT VALID JSON!!!")
            mock_log.assert_any_call("[Invalid JSON from server] NOT VALID JSON!!!")


if __name__ == "__main__":
    unittest.main()

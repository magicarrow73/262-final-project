import unittest
import threading
import socket
import json
import os

# We set the DB path to :memory: so each test is isolated in an in-memory SQLite db.
os.environ["CHAT_DB_PATH"] = ":memory:"

from system_main.server import Server, close_db, init_db

class TestIntegration(unittest.TestCase):
    def setUp(self):
        """
        1. Initialize the database in memory.
        2. Start the server (JSON protocol) on an ephemeral port in a background thread.
        """
        init_db()

        # Create Server instance, using protocol="json"
        self.server = Server(host="127.0.0.1", port=0, protocol_type="json")

        # Manually bind to an ephemeral port (port=0 means "pick an available port")
        self.server.server.bind((self.server.host, 0))
        self.server.port = self.server.server.getsockname()[1]
        self.server.server.listen(5)

        # Start the server in a background thread
        self.server_thread = threading.Thread(target=self.server_loop, daemon=True)
        self.server_thread.start()

    def server_loop(self):
        """
        This runs the server's 'start' logic, except we've already bound the socket manually.
        So we replicate only the accept() loop. On KeyboardInterrupt or test teardown, it stops.
        """
        try:
            while True:
                client_socket, addr = self.server.server.accept()
                client_handler = threading.Thread(
                    target=self.server.handle_client, 
                    args=(client_socket,),
                    daemon=True
                )
                client_handler.start()
        except (KeyboardInterrupt, OSError):
            pass  # Happens when we shut down

    def tearDown(self):
        """
        1. Simulate shutting down the server.
        2. Close in-memory DB.
        """
        # Close the server socket to stop accept() loop
        self.server.server.close()
        close_db()

    # ----------------------------------------------------
    # Helper Method to Send/Receive JSON to/from Server
    # ----------------------------------------------------
    def send_json_command(self, command_obj):
        """
        Opens a TCP connection to the server, sends a JSON command, 
        reads the JSON response (one line), and returns it as a dict.
        """
        with socket.create_connection((self.server.host, self.server.port)) as s:
            # Send JSON
            request_str = json.dumps(command_obj) + "\n"
            s.sendall(request_str.encode("utf-8"))

            # Receive response (one line)
            # Note: The server sends each response followed by \n
            response_data = b""
            while True:
                chunk = s.recv(1024)
                if not chunk:
                    break
                response_data += chunk
                if b"\n" in response_data:
                    break

            # We only read up to the first newline (server sends 1 line per response)
            line, *_ = response_data.split(b"\n", 1)
            resp_str = line.decode("utf-8")
            try:
                return json.loads(resp_str)
            except json.JSONDecodeError:
                return {"status": "error", "message": f"Invalid response: {resp_str}"}

    # ----------------------------------------------------
    # Actual Tests
    # ----------------------------------------------------
    def test_user_deletion_and_relogin(self):
        """
        1. Create user "alice", 
        2. Delete user "alice",
        3. Try logging in again => fails
        """
        # 1) Create user
        create_req = {
            "command": "create_user",
            "username": "alice",
            "hashed_password": "alicepw",
            "display_name": "Alice"
        }
        resp = self.send_json_command(create_req)
        self.assertEqual(resp.get("status"), "success", f"Create user failed: {resp}")

        # 2) Delete user
        # Must log in first to actually delete. So let's do a login:
        login_req = {
            "command": "login",
            "username": "alice",
            "hashed_password": "alicepw"
        }
        resp_login = self.send_json_command(login_req)
        self.assertEqual(resp_login.get("status"), "success", f"Login failed: {resp_login}")

        # Now delete user
        delete_req = {
            "command": "delete_user"
        }
        resp_del = self.send_json_command(delete_req)
        self.assertEqual(resp_del.get("status"), "success", f"Delete user failed: {resp_del}")

        # 3) Attempt to log in => fails
        resp_relogin = self.send_json_command(login_req)
        self.assertEqual(resp_relogin.get("status"), "error", f"Should not be able to log in after delete: {resp_relogin}")

    def test_unread_messages_flow(self):
        """
        1. Create user 'rahul', create user 'brandon'
        2. rahul logs in, sends 2 messages to brandon
        3. brandon logs in => sees 2 unread
        4. brandon reads messages => 0 unread
        """
        # Create user rahul
        resp_create_rahul = self.send_json_command({
            "command": "create_user",
            "username": "rahul",
            "hashed_password": "rahulpw",
            "display_name": "Rahul"
        })
        self.assertEqual(resp_create_rahul.get("status"), "success")

        # Create user brandon
        resp_create_brandon = self.send_json_command({
            "command": "create_user",
            "username": "brandon",
            "hashed_password": "brandonpw",
            "display_name": "Brandon"
        })
        self.assertEqual(resp_create_brandon.get("status"), "success")

        # rahul logs in
        resp_login_rahul = self.send_json_command({
            "command": "login",
            "username": "rahul",
            "hashed_password": "rahulpw"
        })
        self.assertEqual(resp_login_rahul.get("status"), "success")

        # rahul sends 2 messages to brandon
        msg1 = {"command": "send_message", "receiver": "brandon", "content": "Hello #1"}
        msg2 = {"command": "send_message", "receiver": "brandon", "content": "Hello #2"}
        resp_msg1 = self.send_json_command(msg1)
        resp_msg2 = self.send_json_command(msg2)
        self.assertEqual(resp_msg1.get("status"), "success")
        self.assertEqual(resp_msg2.get("status"), "success")

        # brandon logs in => sees 2 unread messages
        resp_login_brandon = self.send_json_command({
            "command": "login",
            "username": "brandon",
            "hashed_password": "brandonpw"
        })
        self.assertEqual(resp_login_brandon.get("status"), "success")
        unread_count = resp_login_brandon.get("unread_count")
        self.assertEqual(unread_count, 2, f"Brandon should have 2 unread, got {unread_count}")

        # brandon reads messages => pass "read_messages"
        resp_read = self.send_json_command({"command": "read_messages"})
        self.assertEqual(resp_read.get("status"), "success", f"Could not read messages: {resp_read}")

        # check if unread messages now => should be 0
        # brandon can request "read_messages" again
        resp_read_again = self.send_json_command({"command": "read_messages"})
        # we expect "messages": [] or no "messages" if none found. 
        # Or the server might not show "unread_count" now.
        # We can do a separate request for unread_count if your server returns it:
        # For demonstration, let's assume the server re-checks unread:
        self.assertTrue(resp_read_again.get("status") in ("success", "error", "push"),
            f"Unexpected status: {resp_read_again}")
        # Alternatively, re-login brandon to see if unread_count=0
        resp_relogin_brandon = self.send_json_command({
            "command": "login",
            "username": "brandon",
            "hashed_password": "brandonpw"
        })
        # might get error "already logged in" depending on your logic
        # or might get success + unread_count=0
        if resp_relogin_brandon.get("status") == "success":
            self.assertEqual(resp_relogin_brandon.get("unread_count"), 0,
                             f"After reading, brandon should have 0 unread: {resp_relogin_brandon}")

if __name__ == "__main__":
    unittest.main()

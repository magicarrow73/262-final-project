"""
ft_client_grpc.py

This script defines a fault-tolerant gRPC client for a chat service.
It can automatically reconnect to alternative servers if the current one fails.
"""

import tkinter as tk
import threading
import grpc
import argparse
import os
import time
import random
import queue

# #uncomment if running a testing file in unittests
# from system_main import chat_pb2
# from system_main import chat_pb2_grpc
import chat_pb2_grpc
import chat_pb2

from utils import hash_password

CLIENT_LOG_FILE = "client_data_usage.log"

def log_data_usage(method_name: str, request_size: int, response_size: int):
    """
    Log data usage (request size and response size) for each gRPC call
    to a local CSV file for monitoring or analytics.

    :param method_name: The name of the gRPC method (e.g., "CreateUser", "Login").
    :param request_size: The byte size of the serialized request message.
    :param response_size: The byte size of the serialized response message.
    """
    file_exists = os.path.exists(CLIENT_LOG_FILE)
    if not file_exists:
        with open(CLIENT_LOG_FILE, "w") as f:
            f.write("method_name,request_size,response_size\n")

    with open(CLIENT_LOG_FILE, "a") as f:
        f.write(f"{method_name},{request_size},{response_size}\n")

class FaultTolerantTkClientGRPC:
    """
    A Tkinter-based gRPC client with fault tolerance capabilities.
    
    This client can detect server failures and automatically reconnect
    to alternative servers in a list. It provides a simple GUI interface
    to perform chat-related operations such as creating accounts, logging in,
    sending/reading messages, etc.
    """

    def __init__(self, server_list):
        """
        Initialize the fault-tolerant client.

        :param server_list: List of server addresses in the format ["host:port", ...].
        """
        self.server_list = server_list
        self.current_server_idx = 0
        self.channel = None
        self.stub = None
        self.max_retries = 5
        self.backoff_base = 0.5  # Starting delay in seconds
        
        self.current_user = None
        self.subscribe_thread = None
        self.subscribe_stop_event = threading.Event()
        self.retry_lock = threading.Lock()
        
        # Track server failures to prioritize healthy servers
        self.server_health = {server: 0 for server in server_list}  # Higher = more failures

        # GUI setup
        self.root = tk.Tk()
        self.root.title("Fault-Tolerant gRPC Chat Client")

        self.text_area = tk.Text(self.root, state='disabled', width=80, height=20)
        self.text_area.pack()

        self.entry = tk.Entry(self.root, width=80)
        self.entry.pack()

        self.status_label = tk.Label(self.root, text="Disconnected", fg="red")
        self.status_label.pack()

        self.btn_frame = tk.Frame(self.root)
        self.btn_frame.pack()

        tk.Button(self.btn_frame, text="Create Account", command=self.create_account_dialog).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="Login", command=self.login_dialog).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="Logout", command=self.logout_dialog).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="Send", command=self.send_dialog).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="List", command=self.list_accounts_dialog).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="Read", command=self.read_messages_dialog).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="Delete Msg", command=self.delete_msg_dialog).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="Delete Account", command=self.delete_account).pack(side=tk.LEFT)

    def connect(self):
        """
        Establish a new gRPC channel and stub by trying available servers in order.
        Closes any existing channel before attempting to reconnect.

        :return: True if the connection succeeded (channel+stub created), False otherwise.
        """
        # Always close any existing channel
        if self.channel:
            try:
                self.channel.close()
            except:
                pass
            self.channel = None
            self.stub = None

        # Prioritize the previously successful (preferred) server if available
        servers_to_try = list(range(len(self.server_list)))
        if hasattr(self, 'preferred_server_idx') and self.preferred_server_idx is not None:
            if self.preferred_server_idx in servers_to_try:
                servers_to_try.remove(self.preferred_server_idx)
                servers_to_try.insert(0, self.preferred_server_idx)

        for idx in servers_to_try:
            server_addr = self.server_list[idx]
            self.log(f"Attempting to connect to server {idx}: {server_addr}")
            try:
                # Create a new channel with basic retry enabled
                self.channel = grpc.insecure_channel(
                    server_addr,
                    options=[('grpc.enable_retries', 1)]
                )
                self.stub = chat_pb2_grpc.ChatServiceStub(self.channel)
                # Send a simple ping request to test connectivity
                ping_request = chat_pb2.ListUsersRequest(username="ping", pattern="*")
                self.stub.ListUsers(ping_request, timeout=3)
                self.log(f"Connected to server {idx}: {server_addr}")
                self.current_server_idx = idx
                self.status_label.config(text=f"Connected to {server_addr}", fg="green")
                return True
            except grpc.RpcError as e:
                self.log(f"Connection failed: {e.details() or str(e)}")
                if self.channel:
                    try:
                        self.channel.close()
                    except:
                        pass
                self.channel = None
                self.stub = None

        self.log("ERROR: All servers are unavailable")
        self.status_label.config(text="Disconnected", fg="red")
        return False

    def try_rpc(self, rpc_func, *args, **kwargs):
        """
        Execute an RPC call with automatic retry and failover logic using exponential backoff.

        - If the channel/stub is inactive, it attempts to reconnect.
        - Retries on connection-related errors (e.g., UNAVAILABLE) up to self.max_retries times.

        :param rpc_func: The RPC function pointer (e.g., self.stub.CreateUser).
        :param args: Positional arguments for the RPC function.
        :param kwargs: Keyword arguments for the RPC function.
        :return: The result of the successful RPC call, or raises the last exception if it fails.
        """
        retries = 0
        delay = 0.5
        last_exception = None

        while retries < self.max_retries:
            try:
                if self.channel is None or self.stub is None:
                    self.log("[DEBUG] try_rpc: Channel/stub is None, calling connect()")
                    if not self.connect():
                        raise Exception("No servers available")
                    
                # Attempt the RPC call
                self.log(f"[DEBUG] try_rpc: calling RPC function on server index={self.current_server_idx}")
                return rpc_func(*args, **kwargs)
            
            except grpc.RpcError as e:
                last_exception = e
                self.log(f"[DEBUG] try_rpc: caught RpcError {e.code()} => {e.details() or str(e)}")
                # Only retry on connection-related errors
                if e.code() in [grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED]:
                    self.log(f"RPC error ({e.code()}): {e.details() or str(e)}. Reconnecting...")
                    self.channel = None
                    self.stub = None
                    time.sleep(delay)

                    retries += 1
                    delay = min(delay * 2, 30)
                    continue
                else:
                    raise e

        if last_exception:
            raise last_exception
        else:
            # Shouldn't happen logically, but just in case
            raise Exception(f"Failed after {self.max_retries} retries")
    
    def log(self, msg):
        """
        Log a message to the GUI text area.

        :param msg: The string message to display.
        """
        self.text_area.config(state='normal')
        self.text_area.insert(tk.END, msg + "\n")
        self.text_area.config(state='disabled')
        self.text_area.see(tk.END)

    # ------------------ Subscription / Push Handling ------------------ #

    def start_subscription_thread(self):
        """
        Start a background thread that continuously subscribes for incoming messages
        from the server. If the stream is broken, it attempts to reconnect using
        exponential backoff until the user logs out or the client shuts down.
        """
        if not self.current_user:
            return
        self.subscribe_stop_event.clear()

        def run_stream():
            """
            Continuously subscribe for incoming messages from the server.
            Reconnects automatically on stream failure.
            """
            consecutive_failures = 0
            while not self.subscribe_stop_event.is_set():
                try:
                    # Ensure there is an active connection before subscribing
                    if self.channel is None or self.stub is None:
                        self.log("No active connection for subscription. Reconnecting...")
                        if not self.connect():
                            raise Exception("Unable to reconnect for subscription")
                    request = chat_pb2.SubscribeRequest(username=self.current_user)
                    stream_iter = self.stub.Subscribe(request)
                    # Reset failure count on successful connection
                    consecutive_failures = 0

                    for incoming in stream_iter:
                        if self.subscribe_stop_event.is_set():
                            break
                        self.log(f"[New Message] from={incoming.sender}: {incoming.content}")

                except grpc.RpcError as e:
                    self.log(f"Subscription RPC error: {e.details() if hasattr(e, 'details') else str(e)}")
                    consecutive_failures += 1
                    delay = min(2 ** consecutive_failures, 30)
                    time.sleep(delay)
                    self.connect()  # attempt to reconnect after failure

                except Exception as ex:
                    self.log(f"Subscription error: {ex}")
                    consecutive_failures += 1
                    delay = min(2 ** consecutive_failures, 30)
                    time.sleep(delay)
                    self.connect()

        self.subscribe_thread = threading.Thread(target=run_stream, daemon=True)
        self.subscribe_thread.start()

    def stop_subscription_thread(self):
        """
        Signal the subscription thread to stop and wait briefly for it to join.
        """
        self.subscribe_stop_event.set()
        if self.subscribe_thread:
            self.subscribe_thread.join(timeout=2)

    # ------------------ Dialog & Command Implementations ------------------ #

    def create_account_dialog(self):
        """
        Open a dialog to create a new user account. 
        Gathers username, password, and display name, then calls CreateUser via gRPC.
        """
        w = tk.Toplevel(self.root)
        w.title("Create Account")

        tk.Label(w, text="Username").pack()
        user_entry = tk.Entry(w)
        user_entry.pack()

        tk.Label(w, text="Password").pack()
        pass_entry = tk.Entry(w, show="*")
        pass_entry.pack()

        tk.Label(w, text="Display Name").pack()
        disp_entry = tk.Entry(w)
        disp_entry.pack()

        def on_ok():
            """Collects user input and calls CreateUser with retry logic."""
            username = user_entry.get().strip()
            password = pass_entry.get()
            display = disp_entry.get()
            w.destroy()

            # if not self.connect():
            #     self.log("[ERROR] Could not connect to any server")
            #     return

            hashed_pw = hash_password(password)
            req = chat_pb2.CreateUserRequest(
                username=username,
                hashed_password=hashed_pw,
                display_name=display
            )
            req_size = len(req.SerializeToString())
            try:
                resp = self.try_rpc(self.stub.CreateUser, req)
                resp_size = len(resp.SerializeToString())
                log_data_usage("CreateUser", req_size, resp_size)

                self.log(f"[{resp.status.upper()}] {resp.message}")
            except Exception as e:
                self.log(f"[ERROR] {str(e)}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def login_dialog(self):
        """
        Open a dialog to log in an existing user account.
        On success, starts the subscription thread for incoming messages.
        """
        w = tk.Toplevel(self.root)
        w.title("Login")

        tk.Label(w, text="Username").pack()
        user_entry = tk.Entry(w)
        user_entry.pack()

        tk.Label(w, text="Password").pack()
        pass_entry = tk.Entry(w, show="*")
        pass_entry.pack()

        def on_ok():
            """Collects user input and calls Login with retry logic."""
            username = user_entry.get().strip()
            password = pass_entry.get()
            w.destroy()

            # if not self.connect():
            #     self.log("[ERROR] Could not connect to any server")
            #     return

            hashed_pw = hash_password(password)
            req = chat_pb2.LoginRequest(username=username, hashed_password=hashed_pw)
            req_size = len(req.SerializeToString())
            try:
                resp = self.try_rpc(self.stub.Login, req)
                resp_size = len(resp.SerializeToString())
                log_data_usage("Login", req_size, resp_size)

                self.log(f"[{resp.status.upper()}] {resp.message} (unread={resp.unread_count})")
                if resp.status == "success":
                    self.preferred_server_idx = self.current_server_idx
                    self.current_user = resp.username
                    self.start_subscription_thread()
            except Exception as e:
                self.log(f"[ERROR] {str(e)}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def logout_dialog(self):
        """
        Open a dialog to confirm logout. On confirmation, sends Logout request
        and stops the subscription thread.
        """
        if not self.current_user:
            self.log("[ERROR] No user is currently logged in.")
            return

        w = tk.Toplevel(self.root)
        w.title("Logout")
        tk.Label(w, text=f"Are you sure you want to logout {self.current_user}?").pack()

        def on_ok():
            """Sends Logout request with retry logic."""
            w.destroy()
            self.stop_subscription_thread()

            # if not self.connect():
            #     self.log("[ERROR] Could not connect to any server")
            #     return

            req = chat_pb2.LogoutRequest(username=self.current_user)
            req_size = len(req.SerializeToString())
            try:
                resp = self.try_rpc(self.stub.Logout, req)
                resp_size = len(resp.SerializeToString())
                log_data_usage("Logout", req_size, resp_size)
                self.log(f"[{resp.status.upper()}] {resp.message}")
                
                if resp.status == "success":
                    self.current_user = None
            except Exception as e:
                self.log(f"[ERROR] {str(e)}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def send_dialog(self):
        """
        Open a dialog to send a new message. Requests receiver username and content,
        then calls SendMessage via gRPC.
        """
        if not self.current_user:
            self.log("[ERROR] You are not logged in.")
            return

        w = tk.Toplevel(self.root)
        w.title("Send Message")

        tk.Label(w, text="To User").pack()
        to_entry = tk.Entry(w)
        to_entry.pack()

        tk.Label(w, text="Message").pack()
        msg_entry = tk.Entry(w)
        msg_entry.pack()

        def on_ok():
            """Sends message with retry logic."""
            receiver = to_entry.get().strip()
            content = msg_entry.get()
            w.destroy()

            # if not self.connect():
            #     self.log("[ERROR] Could not connect to any server")
            #     return

            req = chat_pb2.SendMessageRequest(
                sender=self.current_user,
                receiver=receiver,
                content=content
            )
            req_size = len(req.SerializeToString())
            try:
                resp = self.try_rpc(self.stub.SendMessage, req)
                resp_size = len(resp.SerializeToString())
                log_data_usage("SendMessage", req_size, resp_size)

                self.log(f"[{resp.status.upper()}] {resp.message}")
            except Exception as e:
                self.log(f"[ERROR] {str(e)}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def list_accounts_dialog(self):
        """
        Open a dialog to list user accounts matching a wildcard pattern (default "*").
        Displays results in a Listbox and also logs them to the main text area.
        """
        if not self.current_user:
            self.log("[ERROR] You are not logged in.")
            return

        w = tk.Toplevel(self.root)
        w.title("List Accounts")

        tk.Label(w, text="Pattern (leave blank for all)").pack()
        pattern_entry = tk.Entry(w)
        pattern_entry.pack()

        list_frame = tk.Frame(w)
        list_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL)
        account_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, width=50, height=10)
        scrollbar.config(command=account_listbox.yview)
        account_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def on_ok():
            """Lists users with retry logic."""
            pat = pattern_entry.get().strip() or "*"

            # if not self.connect():
            #     self.log("[ERROR] Could not connect to any server")
            #     return

            req = chat_pb2.ListUsersRequest(username=self.current_user, pattern=pat)
            req_size = len(req.SerializeToString())
            try:
                resp = self.try_rpc(self.stub.ListUsers, req)
                resp_size = len(resp.SerializeToString())
                log_data_usage("ListUsers", req_size, resp_size)

                self.log(f"[{resp.status.upper()}] {resp.message}")
                account_listbox.delete(0, tk.END)
                for u in resp.users:
                    line = f"{u.username} ({u.display_name})"
                    self.log("  " + line)
                    account_listbox.insert(tk.END, line)
            except Exception as e:
                self.log(f"[ERROR] {str(e)}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def read_messages_dialog(self):
        """
        Open a dialog to retrieve messages for the current user (unread or all, up to a limit).
        Each retrieved message is automatically marked as read.
        """
        if not self.current_user:
            self.log("[ERROR] You are not logged in.")
            return

        w = tk.Toplevel(self.root)
        w.title("Read Messages")

        unread_var = tk.BooleanVar(value=False)
        chk = tk.Checkbutton(w, text="Only Unread?", variable=unread_var)
        chk.pack()

        tk.Label(w, text="How many messages (blank for all)").pack()
        limit_entry = tk.Entry(w)
        limit_entry.pack()

        def on_ok():
            """Reads messages with retry logic."""
            only_unread = unread_var.get()
            limit_str = limit_entry.get().strip()
            w.destroy()

            limit_val = 0
            if limit_str:
                try:
                    limit_val = int(limit_str)
                except ValueError:
                    self.log("[ERROR] Invalid integer for limit.")
                    return

            # if not self.connect():
            #     self.log("[ERROR] Could not connect to any server")
            #     return

            req = chat_pb2.ReadMessagesRequest(
                username=self.current_user,
                only_unread=only_unread,
                limit=limit_val
            )
            req_size = len(req.SerializeToString())
            try:
                resp = self.try_rpc(self.stub.ReadMessages, req)
                resp_size = len(resp.SerializeToString())
                log_data_usage("ReadMessages", req_size, resp_size)

                self.log(f"[{resp.status.upper()}] {resp.message}")
                for m in resp.messages:
                    self.log(f"  ID={m.id}, from={m.sender_username}, content={m.content}")
            except Exception as e:
                self.log(f"[ERROR] {str(e)}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def delete_msg_dialog(self):
        """
        Open a dialog to delete one or more messages by ID. The user must either be
        the sender or receiver of the message(s) to delete them.
        """
        if not self.current_user:
            self.log("[ERROR] You are not logged in.")
            return

        w = tk.Toplevel(self.root)
        w.title("Delete Message(s)")

        tk.Label(w, text="Message ID(s), comma separated").pack()
        msg_id_entry = tk.Entry(w)
        msg_id_entry.pack()

        def on_ok():
            """Deletes messages with retry logic."""
            raw_input = msg_id_entry.get().strip()
            w.destroy()
            if not raw_input:
                return

            parts = [p.strip() for p in raw_input.split(",") if p.strip()]
            msg_ids = []
            for p in parts:
                try:
                    msg_ids.append(int(p))
                except ValueError:
                    self.log("[ERROR] IDs must be numeric.")
                    return

            # if not self.connect():
            #     self.log("[ERROR] Could not connect to any server")
            #     return

            req = chat_pb2.DeleteMessagesRequest(
                username=self.current_user,
                message_ids=msg_ids
            )
            req_size = len(req.SerializeToString())
            try:
                resp = self.try_rpc(self.stub.DeleteMessages, req)
                resp_size = len(resp.SerializeToString())
                log_data_usage("DeleteMessages", req_size, resp_size)

                self.log(f"[{resp.status.upper()}] {resp.message}, count={resp.deleted_count}")
            except Exception as e:
                self.log(f"[ERROR] {str(e)}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def delete_account(self):
        """
        Open a dialog to confirm deletion of the current user's account.
        This also deletes all their messages (sent or received).
        """
        if not self.current_user:
            self.log("[ERROR] You are not logged in.")
            return

        w = tk.Toplevel(self.root)
        w.title("Delete Account")
        tk.Label(w, text=f"Are you sure you want to delete your account '{self.current_user}'?").pack()

        def on_ok():
            """Deletes account with retry logic."""
            w.destroy()
            self.stop_subscription_thread()

            # if not self.connect():
            #     self.log("[ERROR] Could not connect to any server")
            #     return

            req = chat_pb2.DeleteUserRequest(username=self.current_user)
            req_size = len(req.SerializeToString())
            try:
                resp = self.try_rpc(self.stub.DeleteUser, req)
                resp_size = len(resp.SerializeToString())
                log_data_usage("DeleteUser", req_size, resp_size)

                self.log(f"[{resp.status.upper()}] {resp.message}")
                if resp.status == "success":
                    self.current_user = None
            except Exception as e:
                self.log(f"[ERROR] {str(e)}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def run(self):
        """
        Start the client application by attempting an initial connection to a server.
        Then run the Tkinter main loop until the user closes the application.
        """
        if self.connect():
            self.log("Successfully connected to server")
        else:
            self.log("Failed to connect to any server. Will retry on operations.")
            
        self.root.mainloop()
        self.stop_subscription_thread()
        if self.channel:
            self.channel.close()


def main():
    """
    Main entry point for the fault-tolerant gRPC Chat Client.
    Parses command-line arguments for server addresses, then 
    launches the Tkinter-based GUI.
    """
    parser = argparse.ArgumentParser(description="Fault-Tolerant gRPC Chat Client")
    parser.add_argument("--servers", default="127.0.0.1:50051,127.0.0.1:50052,127.0.0.1:50053",
                        help="Comma-separated list of server addresses (host:port)")
    args = parser.parse_args()
    
    # Parse server addresses
    server_list = args.servers.split(",")
    
    # Create and run client
    gui = FaultTolerantTkClientGRPC(server_list)
    gui.run()


if __name__ == "__main__":
    main()

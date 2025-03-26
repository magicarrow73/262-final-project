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

import chat_pb2
import chat_pb2_grpc
from utils import hash_password

CLIENT_LOG_FILE = "client_data_usage.log"

def log_data_usage(method_name: str, request_size: int, response_size: int):
    """Logs data usage to a file."""
    file_exists = os.path.exists(CLIENT_LOG_FILE)
    if not file_exists:
        with open(CLIENT_LOG_FILE, "w") as f:
            f.write("method_name,request_size,response_size\n")

    with open(CLIENT_LOG_FILE, "a") as f:
        f.write(f"{method_name},{request_size},{response_size}\n")

class FaultTolerantTkClientGRPC:
    """
    A Tkinter-based gRPC client with fault tolerance capabilities.
    Can detect server failures and reconnect to alternative servers.
    """

    def __init__(self, server_list):
        """
        Constructor for the fault-tolerant client.
        
        Parameters:
        -----------
        server_list : list
            List of server addresses in the format ["host:port", ...]
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
        Establishes a gRPC channel to a server, with retry and failover logic.
        Returns True if connection succeeds, False otherwise.
        """
        with self.retry_lock:
            # Don't log reconnection attempts unless it's the first try or we changed servers
            first_try = (self.channel is None)

            # Get servers sorted by health
            sorted_servers = sorted(self.server_list, key=lambda s: self.server_health[s])
    
            for server_addr in sorted_servers:
                try:
                    # Only close the channel if we're switching servers
                    if self.channel and server_addr != self.server_list[self.current_server_idx]:
                        self.channel.close()
                        self.channel = None
                    
                    # Only create a new channel if we don't have one
                    if self.channel is None:
                        if first_try:
                            self.log(f"Connecting to server at {server_addr}...")
                        
                        self.channel = grpc.insecure_channel(
                            server_addr,
                            options=[
                                ('grpc.enable_retries', 1),
                                ('grpc.keepalive_time_ms', 10000),
                                ('grpc.keepalive_timeout_ms', 5000),
                                ('grpc.max_receive_message_length', 10 * 1024 * 1024)  # 10MB
                            ]
                        )
                        self.stub = chat_pb2_grpc.ChatServiceStub(self.channel)
                    
                    # Light-weight connection check
                    if self.current_user:
                        req = chat_pb2.ListUsersRequest(username=self.current_user, pattern="*")
                        self.stub.ListUsers(req, timeout=2)
                    
                    # Connection successful
                    self.status_label.config(text=f"Connected to {server_addr}", fg="green")
                    self.current_server_idx = self.server_list.index(server_addr)
                    self.server_health[server_addr] = max(0, self.server_health[server_addr] - 1)
                    return True
                    
                except grpc.RpcError as e:
                    if first_try:
                        self.log(f"Failed to connect to {server_addr}: {e.details()}")
                    
                    # Update server health score
                    self.server_health[server_addr] += 1
                    
                    # Reset connection
                    if self.channel:
                        self.channel.close()
                        self.channel = None
                    
            # All servers failed
            self.status_label.config(text="Disconnected - All servers unavailable", fg="red")
            return False

    def try_rpc(self, rpc_func, *args, **kwargs):
        """
        Try to execute an RPC call with automatic retry and failover.
        
        Parameters:
        -----------
        rpc_func : function
            The RPC function to call
        *args, **kwargs:
            Arguments to pass to the RPC function
        
        Returns:
        --------
        The result of the RPC call or raises an exception if all retries fail
        """
        retries = 0
        last_exception = None
        
        while retries < self.max_retries:
            try:
                # Try the RPC call
                return rpc_func(*args, **kwargs)
                
            except grpc.RpcError as e:
                last_exception = e
                
                # Check if it's a server failure
                if e.code() in [
                    grpc.StatusCode.UNAVAILABLE,
                    grpc.StatusCode.DEADLINE_EXCEEDED,
                    grpc.StatusCode.INTERNAL
                ]:
                    retries += 1
                    
                    # Capture current server for health tracking
                    current_server = self.server_list[self.current_server_idx]
                    
                    # Update server health
                    self.server_health[current_server] += 1
                    
                    # Log the error
                    self.log(f"Server error: {e.details()}. Retrying ({retries}/{self.max_retries})...")
                    
                    # Exponential backoff
                    delay = self.backoff_base * (2 ** (retries - 1))
                    delay = min(delay, 10)  # Cap at 10 seconds
                    time.sleep(delay)
                    
                    # Try to reconnect
                    if not self.connect():
                        self.log("Failed to reconnect to any server")
                        
                else:
                    # Not a connection issue, just raise it
                    raise
        
        # Max retries exceeded
        if last_exception:
            raise last_exception
        else:
            raise Exception(f"Failed after {self.max_retries} retries")

    def log(self, msg):
        """Logs a message to the GUI's text area."""
        self.text_area.config(state='normal')
        self.text_area.insert(tk.END, msg + "\n")
        self.text_area.config(state='disabled')
        self.text_area.see(tk.END)

    # ------------------ Subscription / Push Handling ------------------ #

    def start_subscription_thread(self):
        """Starts a background thread for streaming messages with fault tolerance."""
        if not self.current_user:
            return
        self.subscribe_stop_event.clear()

        def run_stream():
            """Continuously reads from Subscribe with automatic reconnection."""
            consecutive_failures = 0
            while not self.subscribe_stop_event.is_set():
                try:
                    request = chat_pb2.SubscribeRequest(username=self.current_user)
                    stream_iter = self.stub.Subscribe(request)

                    consecutive_failures = 0
                    
                    for incoming in stream_iter:
                        if self.subscribe_stop_event.is_set():
                            break
                        sender = incoming.sender
                        content = incoming.content
                        self.log(f"[New Message] from={sender}: {content}")
                        
                except grpc.RpcError as e:
                    if self.subscribe_stop_event.is_set():
                        break
                        
                    if consecutive_failures < 3:
                        self.log(f"[Subscription interrupted]: {e.details()}")
                        
                    # Exponential backoff for reconnection attempts
                    consecutive_failures += 1
                    delay = min(2 ** consecutive_failures, 30)  # Cap at 30 seconds
                    time.sleep(delay)
                    
                    # Don't spam reconnect attempts
                    if consecutive_failures % 3 == 0:
                        self.connect()
                    
                except Exception as e:
                    if self.subscribe_stop_event.is_set():
                        break
                        
                    if consecutive_failures < 3:
                        self.log(f"[Subscription error]: {str(e)}")

                    time.sleep(5)  # Throttle reconnection attempts

        self.subscribe_thread = threading.Thread(target=run_stream, daemon=True)
        self.subscribe_thread.start()

    def stop_subscription_thread(self):
        """Signals the subscription thread to stop."""
        self.subscribe_stop_event.set()
        if self.subscribe_thread:
            self.subscribe_thread.join(timeout=2)

    # ------------------ Dialog & Command Implementations ------------------ #

    def create_account_dialog(self):
        """Opens a dialog to create a new user account with fault tolerance."""
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

            if not self.connect():
                self.log("[ERROR] Could not connect to any server")
                return

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
        """Opens a dialog to log in an existing user with fault tolerance."""
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

            if not self.connect():
                self.log("[ERROR] Could not connect to any server")
                return

            hashed_pw = hash_password(password)
            req = chat_pb2.LoginRequest(username=username, hashed_password=hashed_pw)
            req_size = len(req.SerializeToString())
            try:
                resp = self.try_rpc(self.stub.Login, req)
                resp_size = len(resp.SerializeToString())
                log_data_usage("Login", req_size, resp_size)

                self.log(f"[{resp.status.upper()}] {resp.message} (unread={resp.unread_count})")
                if resp.status == "success":
                    self.current_user = resp.username
                    self.start_subscription_thread()
            except Exception as e:
                self.log(f"[ERROR] {str(e)}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def logout_dialog(self):
        """Opens a dialog to confirm logout with fault tolerance."""
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

            if not self.connect():
                self.log("[ERROR] Could not connect to any server")
                return

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
        """Opens a dialog to send a message with fault tolerance."""
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

            if not self.connect():
                self.log("[ERROR] Could not connect to any server")
                return

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
        """Opens a dialog to list accounts with fault tolerance."""
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

            if not self.connect():
                self.log("[ERROR] Could not connect to any server")
                return

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
        """Opens a dialog to read messages with fault tolerance."""
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

            if not self.connect():
                self.log("[ERROR] Could not connect to any server")
                return

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
        """Opens a dialog to delete messages with fault tolerance."""
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

            if not self.connect():
                self.log("[ERROR] Could not connect to any server")
                return

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
        """Opens a dialog to confirm account deletion with fault tolerance."""
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

            if not self.connect():
                self.log("[ERROR] Could not connect to any server")
                return

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
        """Start the client with initial connection attempt."""
        if self.connect():
            self.log("Successfully connected to server")
        else:
            self.log("Failed to connect to any server. Will retry on operations.")
            
        self.root.mainloop()
        self.stop_subscription_thread()
        if self.channel:
            self.channel.close()


def main():
    """Main entry point with server list configuration."""
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

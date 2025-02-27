"""
client_grpc.py

This script defines a gRPC client with a Tkinter GUI interface for a chat service. 
It can create users, log in/out, send messages, list users, read messages, 
and delete users and messages. Data usage is logged to a local file.
"""

import tkinter as tk
import threading
import grpc
import argparse
import os

# from system_main import chat_pb2
# from system_main import chat_pb2_grpc
import chat_pb2_grpc
import chat_pb2
from utils import hash_password

CLIENT_LOG_FILE = "client_data_usage.log"

def log_data_usage(method_name: str, request_size: int, response_size: int):
    """
    Logs data usage (request_size, response_size) to a file.
    
    If CLIENT_LOG_FILE does not exist, creates it and writes a header:
    method_name,request_size,response_size
    
    Parameters:
    -----------
    method_name : str
        The name of the RPC method or command, e.g. "CreateUser"
    request_size : int
        The size of the serialized request in bytes
    response_size : int
        The size of the serialized response in bytes
    """
    file_exists = os.path.exists(CLIENT_LOG_FILE)
    if not file_exists:
        with open(CLIENT_LOG_FILE, "w") as f:
            f.write("method_name,request_size,response_size\n")

    with open(CLIENT_LOG_FILE, "a") as f:
        f.write(f"{method_name},{request_size},{response_size}\n")

class TkClientGRPC:
    """
    TkClientGRPC
    
    A Tkinter-based gRPC client for interacting with a chat server.
    Provides GUI dialogs for creating accounts, logging in, sending messages, etc.
    """

    def __init__(self, host="127.0.0.1", port=12345):
        """
        Constructor for the TkClientGRPC class.
        
        Parameters:
        -----------
        host : str
            The hostname or IP where the gRPC server is running.
        port : int
            The port number on which the gRPC server listens.
        """
        self.host = host
        self.port = port
        self.channel = None
        self.stub = None

        self.current_user = None
        self.subscribe_thread = None
        self.subscribe_stop_event = threading.Event()

        # GUI setup
        self.root = tk.Tk()
        self.root.title("gRPC Chat Client")

        self.text_area = tk.Text(self.root, state='disabled', width=80, height=20)
        self.text_area.pack()

        self.entry = tk.Entry(self.root, width=80)
        self.entry.pack()

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
        Establishes a gRPC channel to the specified server (host:port).
        Also creates a stub for RPC calls.
        """
        address = f"{self.host}:{self.port}"
        self.channel = grpc.insecure_channel(address)
        self.stub = chat_pb2_grpc.ChatServiceStub(self.channel)
        self.log(f"Connected to gRPC server at {address}")

    def log(self, msg):
        """
        Logs a message to the GUI's text area (visible to the user).
        
        Parameters:
        -----------
        msg : str
            The message to display in the text area.
        """
        self.text_area.config(state='normal')
        self.text_area.insert(tk.END, msg + "\n")
        self.text_area.config(state='disabled')
        self.text_area.see(tk.END)

    # ------------------ Subscription / Push Handling ------------------ #

    def start_subscription_thread(self):
        """
        Starts a background thread to receive streaming push messages 
        (Subscribe RPC) from the server.
        """
        if not self.current_user:
            return
        self.subscribe_stop_event.clear()

        def run_stream():
            """
            Continuously reads from the server's Subscribe() method
            until the user logs out or an error occurs.
            """
            request = chat_pb2.SubscribeRequest(username=self.current_user)
            try:
                for incoming in self.stub.Subscribe(request):
                    if self.subscribe_stop_event.is_set():
                        break
                    sender = incoming.sender
                    content = incoming.content
                    self.log(f"[New Message] from={sender}: {content}")
            except grpc.RpcError as e:
                self.log(f"[Subscription ended] {e.details()}")

        self.subscribe_thread = threading.Thread(target=run_stream, daemon=True)
        self.subscribe_thread.start()

    def stop_subscription_thread(self):
        """
        Signals the subscription thread to stop reading new push messages.
        """
        self.subscribe_stop_event.set()

    # ------------------ Dialog & Command Implementations ------------------ #

    def create_account_dialog(self):
        """
        Opens a Tkinter dialog to create a new user account. 
        Sends a CreateUser request to the server with the user inputs.
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
            """
            Collects user input, builds a CreateUser request, measures 
            request and response sizes, logs them, and displays result.
            """
            username = user_entry.get().strip()
            password = pass_entry.get()
            display = disp_entry.get()
            w.destroy()

            hashed_pw = hash_password(password)
            req = chat_pb2.CreateUserRequest(
                username=username,
                hashed_password=hashed_pw,
                display_name=display
            )
            req_size = len(req.SerializeToString())
            try:
                resp = self.stub.CreateUser(req)
                resp_size = len(resp.SerializeToString())
                log_data_usage("CreateUser", req_size, resp_size)

                self.log(f"[{resp.status.upper()}] {resp.message}")
            except grpc.RpcError as e:
                self.log(f"[ERROR] {e.details()}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def login_dialog(self):
        """
        Opens a Tkinter dialog to log in an existing user.
        Sends a Login request to the server with the user inputs.
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
            """
            Collects user input, builds a Login request, logs data usage,
            and if successful, starts the subscription thread.
            """
            username = user_entry.get().strip()
            password = pass_entry.get()
            w.destroy()

            hashed_pw = hash_password(password)
            req = chat_pb2.LoginRequest(username=username, hashed_password=hashed_pw)
            req_size = len(req.SerializeToString())
            try:
                resp = self.stub.Login(req)
                resp_size = len(resp.SerializeToString())
                log_data_usage("Login", req_size, resp_size)

                self.log(f"[{resp.status.upper()}] {resp.message} (unread={resp.unread_count})")
                if resp.status == "success":
                    self.current_user = resp.username
                    self.start_subscription_thread()
            except grpc.RpcError as e:
                self.log(f"[ERROR] {e.details()}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def logout_dialog(self):
        """
        Opens a dialog to confirm logout for the current user.
        Sends a Logout request to the server, and stops the subscription thread if successful.
        """
        if not self.current_user:
            self.log("[ERROR] No user is currently logged in.")
            return

        w = tk.Toplevel(self.root)
        w.title("Logout")
        tk.Label(w, text=f"Are you sure you want to logout {self.current_user}?").pack()

        def on_ok():
            """
            Sends the Logout request, logs data usage, and clears current_user on success.
            """
            w.destroy()
            self.stop_subscription_thread()

            req = chat_pb2.LogoutRequest(username=self.current_user)
            req_size = len(req.SerializeToString())
            try:
                resp = self.stub.Logout(req)
                resp_size = len(resp.SerializeToString())
                log_data_usage("Logout", req_size, resp_size)

                self.log(f"[{resp.status.upper()}] {resp.message}")
                if resp.status == "success":
                    self.current_user = None
            except grpc.RpcError as e:
                self.log(f"[ERROR] {e.details()}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def send_dialog(self):
        """
        Opens a dialog to send a message to another user. 
        Constructs a SendMessage request and logs data usage.
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
            """
            Sends the message to the server, measuring request and response sizes.
            """
            receiver = to_entry.get().strip()
            content = msg_entry.get()
            w.destroy()

            req = chat_pb2.SendMessageRequest(
                sender=self.current_user,
                receiver=receiver,
                content=content
            )
            req_size = len(req.SerializeToString())
            try:
                resp = self.stub.SendMessage(req)
                resp_size = len(resp.SerializeToString())
                log_data_usage("SendMessage", req_size, resp_size)

                self.log(f"[{resp.status.upper()}] {resp.message}")
            except grpc.RpcError as e:
                self.log(f"[ERROR] {e.details()}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def list_accounts_dialog(self):
        """
        Opens a dialog to list user accounts matching a pattern. 
        Sends a ListUsers request and logs data usage.
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
            """
            Sends the ListUsers request, logs data usage, and populates the listbox with results.
            """
            pat = pattern_entry.get().strip() or "*"
            req = chat_pb2.ListUsersRequest(username=self.current_user, pattern=pat)
            req_size = len(req.SerializeToString())
            try:
                resp = self.stub.ListUsers(req)
                resp_size = len(resp.SerializeToString())
                log_data_usage("ListUsers", req_size, resp_size)

                self.log(f"[{resp.status.upper()}] {resp.message}")
                account_listbox.delete(0, tk.END)
                for u in resp.users:
                    line = f"{u.username} ({u.display_name})"
                    self.log("  " + line)
                    account_listbox.insert(tk.END, line)
            except grpc.RpcError as e:
                self.log(f"[ERROR] {e.details()}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def read_messages_dialog(self):
        """
        Opens a dialog allowing the user to read messages (unread only or all),
        optionally limited by a certain number. Sends a ReadMessages request.
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
            """
            Builds and sends a ReadMessages request, measures data usage, 
            and logs the retrieved messages in the GUI.
            """
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

            req = chat_pb2.ReadMessagesRequest(
                username=self.current_user,
                only_unread=only_unread,
                limit=limit_val
            )
            req_size = len(req.SerializeToString())
            try:
                resp = self.stub.ReadMessages(req)
                resp_size = len(resp.SerializeToString())
                log_data_usage("ReadMessages", req_size, resp_size)

                self.log(f"[{resp.status.upper()}] {resp.message}")
                for m in resp.messages:
                    self.log(f"  ID={m.id}, from={m.sender_username}, content={m.content}")
            except grpc.RpcError as e:
                self.log(f"[ERROR] {e.details()}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def delete_msg_dialog(self):
        """
        Opens a dialog allowing the user to delete one or more messages by ID.
        Sends a DeleteMessages request, measuring data usage.
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
            """
            Parses comma-separated message IDs, builds a DeleteMessages request,
            logs usage, and displays the result.
            """
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

            req = chat_pb2.DeleteMessagesRequest(
                username=self.current_user,
                message_ids=msg_ids
            )
            req_size = len(req.SerializeToString())
            try:
                resp = self.stub.DeleteMessages(req)
                resp_size = len(resp.SerializeToString())
                log_data_usage("DeleteMessages", req_size, resp_size)

                self.log(f"[{resp.status.upper()}] {resp.message}, count={resp.deleted_count}")
            except grpc.RpcError as e:
                self.log(f"[ERROR] {e.details()}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def delete_account(self):
        """
        Opens a dialog to confirm account deletion. If confirmed, sends 
        a DeleteUser request and clears current_user on success.
        """
        if not self.current_user:
            self.log("[ERROR] You are not logged in.")
            return

        w = tk.Toplevel(self.root)
        w.title("Delete Account")
        tk.Label(w, text=f"Are you sure you want to delete your account '{self.current_user}'?").pack()

        def on_ok():
            """
            Sends the DeleteUser request, measures data usage, and resets 
            current_user on success.
            """
            w.destroy()
            self.stop_subscription_thread()

            req = chat_pb2.DeleteUserRequest(username=self.current_user)
            req_size = len(req.SerializeToString())
            try:
                resp = self.stub.DeleteUser(req)
                resp_size = len(resp.SerializeToString())
                log_data_usage("DeleteUser", req_size, resp_size)

                self.log(f"[{resp.status.upper()}] {resp.message}")
                if resp.status == "success":
                    self.current_user = None
            except grpc.RpcError as e:
                self.log(f"[ERROR] {e.details()}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def run(self):
        """
        Connects to the server and starts the Tkinter main loop.
        The subscription thread is stopped upon window close.
        """
        self.connect()
        self.root.mainloop()
        self.stop_subscription_thread()

def main():
    """
    Main entry point for running the gRPC chat client.
    Parses command-line arguments and instantiates TkClientGRPC.
    """
    parser = argparse.ArgumentParser(description="gRPC Chat Client")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Server host to connect to.")
    parser.add_argument("--port", type=int, default=12345,
                        help="Server port to connect to.")
    args = parser.parse_args()

    gui = TkClientGRPC(host=args.host, port=args.port)
    gui.run()

if __name__ == "__main__":
    main()

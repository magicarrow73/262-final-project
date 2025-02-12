import tkinter as tk
import socket
import threading
import json

class TkClient:
    def __init__(self, host="127.0.0.1", port=12345, use_json=True):
        '''
        Initialize the client with the host, port, and whether to use JSON.
        use_json: if True, the client will use JSON for communication. Otherwise, it will use a custom wire protocol.
        '''
        self.host = host
        self.port = port
        self.use_json = use_json
        self.sock = None

        # GUI setup
        self.root = tk.Tk()
        self.root.title("Chat Client")

        self.text_area = tk.Text(self.root, state='disabled', width=80, height=20)
        self.text_area.pack()

        self.entry = tk.Entry(self.root, width=80)
        self.entry.pack()
        self.entry.bind("<Return>", self.handle_enter)

        self.btn_frame = tk.Frame(self.root)
        self.btn_frame.pack()

        tk.Button(self.btn_frame, text="Create Account", command=self.create_account_dialog).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="Login", command=self.login_dialog).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="Send", command=self.send_dialog).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="List", command=self.list_accounts_dialog).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="Read", command=self.read_messages_dialog).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="Delete Msg", command=self.delete_msg_dialog).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="Del Account", command=self.delete_account).pack(side=tk.LEFT)

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.host, self.port))

        print("Connected to server")
        # Start a listener thread for push notifications and general responses
        listener = threading.Thread(target=self.listen_loop, daemon=True)
        listener.start()

    def listen_loop(self):
        """
        Continuously reads lines from server, which could be responses or push notifications.
        """
        buffer = b""
        while True:
            try:
                chunk = self.sock.recv(1024)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    self.handle_server_line(line.decode('utf-8'))
            except:
                self.log("Connection lost or error.")
                break

    def handle_server_line(self, line: str):
        """
        Handles incoming messages from the server, including updates to the list of users.
        """
        if self.use_json:
            try:
                obj = json.loads(line)
                status = obj.get("status")
                message = obj.get("message", "")

                if status == "success":
                    self.log(f"[SUCCESS] {message}")

                    # If the server returns a list of users, update the listbox
                    if "users" in obj and "pattern" in obj: 
                        pattern_str = obj["pattern"]
                        self.log(f"Listing Users Matching Pattern: {pattern_str}")
                        if hasattr(self, 'current_listbox'):  # Ensure reference exists
                            self.current_listbox.delete(0, tk.END)  # Clear previous entries
                        for u in obj["users"]:
                            user_info = f"{u['username']} ({u['display_name']})"
                            self.log(f"  {user_info}")
                            if hasattr(self, 'current_listbox'):
                                self.current_listbox.insert(tk.END, user_info)

                elif status == "error":
                    self.log(f"[ERROR] {message}")
                else:
                    self.log(f"[RESPONSE] {obj}")

            except json.JSONDecodeError:
                self.log(f"[Invalid JSON from server] {line}")
        else:
            # custom wire we have not implemented yet
            self.log(line)

    def log(self, msg):
        self.text_area.config(state='normal')
        self.text_area.insert(tk.END, msg + "\n")
        self.text_area.config(state='disabled')
        self.text_area.see(tk.END)

    def handle_enter(self, event):
        """
        If you want direct sending of typed lines (custom wire).
        """
        if not self.use_json:
            line = self.entry.get()
            self.entry.delete(0, tk.END)
            self.send_line(line)

    # ----------------------
    # Utility send methods
    # ----------------------
    def send_line(self, line: str):
        """
        For custom wire mode
        """
        try:
            self.sock.sendall((line + "\n").encode('utf-8'))
        except:
            self.log("[Error] Failed to send wire")

    def send_json(self, obj):
        """
        For JSON mode
        """
        try:
            line = json.dumps(obj) + "\n"
            self.sock.sendall(line.encode('utf-8'))
        except Exception as e:
            self.log(f"[Error] Failed to send JSON: {e}")

    # ----------------------
    # Commands
    # ----------------------
    def create_account_dialog(self):
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
            username = user_entry.get()
            password = pass_entry.get()
            display = disp_entry.get()
            w.destroy()
            if self.use_json:
                req = {
                    "command": "create_user",
                    "username": username,
                    "password": password,
                    "display_name": display
                }
                self.send_json(req)
            else:
                #custom protocol
                line = f"CREATE {username} {password} {display}"
                self.send_line(line)

        tk.Button(w, text="OK", command=on_ok).pack()

    def login_dialog(self):
        w = tk.Toplevel(self.root)
        w.title("Login")

        tk.Label(w, text="Username").pack()
        user_entry = tk.Entry(w)
        user_entry.pack()

        tk.Label(w, text="Password").pack()
        pass_entry = tk.Entry(w, show="*")
        pass_entry.pack()

        def on_ok():
            user = user_entry.get()
            pw = pass_entry.get()
            w.destroy()
            if self.use_json:
                req = {"command": "login", "username": user, "password": pw}
                self.send_json(req)
            else:
                self.send_line(f"LOGIN {user} {pw}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def send_dialog(self):
        w = tk.Toplevel(self.root)
        w.title("Send Message")

        tk.Label(w, text="To User").pack()
        to_entry = tk.Entry(w)
        to_entry.pack()

        tk.Label(w, text="Message").pack()
        msg_entry = tk.Entry(w)
        msg_entry.pack()

        def on_ok():
            to_user = to_entry.get()
            msg = msg_entry.get()
            w.destroy()
            if self.use_json:
                req = {"command": "send_message", "receiver": to_user, "content": msg}
                self.send_json(req)
            else:
                self.send_line(f"SEND {to_user} {msg}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def list_accounts_dialog(self):
        """
        Opens a dialog to request a list of accounts matching a pattern and displays the results in a scrollable list.
        """
        w = tk.Toplevel(self.root)
        w.title("List Accounts")

        tk.Label(w, text="Pattern to Match Accounts (if none, list all)").pack()

        pattern = tk.Entry(w)
        pattern.pack()

        list_frame = tk.Frame(w)
        list_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL)
        account_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, width=50, height=10)
        scrollbar.config(command=account_listbox.yview)

        account_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def on_ok():
            pattern_to_use = pattern.get()
            print(pattern_to_use)
            if not pattern_to_use:
                pattern_to_use = "*"
            if self.use_json:
                req = {"command": "list_users", "pattern": pattern_to_use}
                self.send_json(req)

                # Store reference to update later
                self.current_listbox = account_listbox  
            else:
                pass  # Implement if using a custom protocol

        tk.Button(w, text="OK", command=on_ok).pack()


    def read_messages_dialog(self):
        """
        Opens a dialog to show the total number of messages and unread messages.
        Allows the user to choose between reading all messages or only unread messages.
        Uses a scrollable list to display messages if there are too many.
        """
        # Create dialog
        w = tk.Toplevel(self.root)
        w.title("Read Messages")

        # Labels to show message statistics
        self.total_msg_label = tk.Label(w, text="Total Messages: Fetching...")
        self.total_msg_label.pack()

        self.unread_msg_label = tk.Label(w, text="Unread Messages: Fetching...")
        self.unread_msg_label.pack()

        # Radio buttons to choose between reading all or unread messages
        self.read_choice = tk.StringVar(value="all")
        tk.Radiobutton(w, text="Read All Messages", variable=self.read_choice, value="all").pack()
        tk.Radiobutton(w, text="Read Only Unread Messages", variable=self.read_choice, value="unread").pack()

        # Entry box to specify the number of messages to read
        tk.Label(w, text="How many messages to read? (Leave empty for all)").pack()
        self.num_msgs_entry = tk.Entry(w)
        self.num_msgs_entry.pack()

        # Scrollable message list
        list_frame = tk.Frame(w)
        list_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self.msg_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, width=80, height=10)
        scrollbar.config(command=self.msg_listbox.yview)

        self.msg_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Fetch message count when opening
        self.send_json({"command": "get_message_count"})

        def on_fetch():
            """ Fetch messages based on user selection """
            num_msgs = self.num_msgs_entry.get()
            try:
                num_msgs = int(num_msgs) if num_msgs else None
            except ValueError:
                self.log("[ERROR] Invalid number entered.")
                return

            req = {"command": "read_messages"}
            if self.read_choice.get() == "unread":
                req["only_unread"] = True
            if num_msgs:
                req["limit"] = num_msgs

            self.send_json(req)

        tk.Button(w, text="Fetch Messages", command=on_fetch).pack()

        # Store reference for updating later
        self.current_msg_listbox = self.msg_listbox  
        self.current_total_msg_label = self.total_msg_label
        self.current_unread_msg_label = self.unread_msg_label


    def delete_msg_dialog(self):
        w = tk.Toplevel(self.root)
        w.title("Delete Message")

        tk.Label(w, text="Message ID").pack()
        msg_id_entry = tk.Entry(w)
        msg_id_entry.pack()

        def on_ok():
            mid = msg_id_entry.get()
            w.destroy()
            if self.use_json:
                req = {"command": "delete_messages", "message_id": int(mid)}
                self.send_json(req)
            else:
                self.send_line(f"DELETE_MSG {mid}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def delete_account(self):
        if self.use_json:
            w = tk.Toplevel(self.root)
            w.title("Delete Account")

            tk.Label(w, text="Username to delete").pack()
            user_entry = tk.Entry(w)
            user_entry.pack()

            def on_ok():
                user = user_entry.get()
                w.destroy()
                req = {"command": "delete_user", "username": user}
                self.send_json(req)

            tk.Button(w, text="OK", command=on_ok).pack()
        else:
            self.send_line("DELETE_ACCOUNT")

    def run(self):
        self.connect()
        self.root.mainloop()

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run our messaging client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=12345)
    parser.add_argument("--json", action="store_true", default=False)
    args = parser.parse_args()

    gui = TkClient(host=args.host, port=args.port, use_json=args.json)
    gui.run()

if __name__ == "__main__":
    main()

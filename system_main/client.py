import tkinter as tk
import socket
import threading
import json

from .utils import hash_password

class TkClient:
    def __init__(self, host="127.0.0.1", port=12345, use_json=True):
        """
        Initialize the client with the host, port, and whether to use JSON.
        use_json: if True, the client will use JSON for communication. Otherwise, it will use a custom wire protocol.
        """

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
        tk.Button(self.btn_frame, text="Logout", command=self.logout_dialog).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="Send", command=self.send_dialog).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="List", command=self.list_accounts_dialog).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="Read", command=self.read_messages).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="Delete Msg", command=self.delete_msg_dialog).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="Delete Account", command=self.delete_account).pack(side=tk.LEFT)

    def connect(self):
        """
        Connect to the server and start a listener thread.
        """
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
                if status == "push":
                    push_type = obj.get("push_type")
                    if push_type == "incoming_message":
                        sender = obj.get("sender")
                        content = obj.get("content")
                        self.log(f"[New Message] from={sender}: {content}")
                    return
                
                message = obj.get("message", "")

                if status == "success":
                    self.log(f"[SUCCESS] {message}")

                    # in this case, both `users` and `pattern` are in obj
                    # here, the obj must be the server returning a list of users
                    if "users" in obj and "pattern" in obj:
                        pattern_str = obj["pattern"]
                        self.log(f"Listing Users Matching Pattern: {pattern_str}")
                        if hasattr(self, 'current_listbox'):
                            self.current_listbox.delete(0, tk.END)
                        for u in obj["users"]:
                            user_info = f"{u['username']} ({u['display_name']})"
                            self.log(f"  {user_info}")
                            if hasattr(self, 'current_listbox'):
                                self.current_listbox.insert(tk.END, user_info)

                    # in this case, `messages` is in obj
                    # here, if the server returns a list of messages
                    if "messages" in obj:
                        self.log("Messages:")
                        for m in obj["messages"]:
                            sender = m["sender_username"]
                            ts = m["timestamp"]
                            content = m["content"]
                            msg_id = m["id"]
                            self.log(f"  ID={msg_id}, from={sender}, time={ts}, content={content}")
                    
                    # in this case, `unread_count` is in obj
                    # here, the server returns the number of unread messages
                    if "unread_count" in obj:
                        self.log(f"You have {obj['unread_count']} unread messages.")
                    
                    # in this case, `deleted_count` is in obj
                    # here, the server returns the number of deleted messages
                    if "deleted_count" in obj:
                        self.log(f"Deleted {obj['deleted_count']} messages.")
                elif status == 'user_exists':
                    self.log(message)
                    existing_username = obj.get("username", "")
                    self.prompt_login_for_existing_user(existing_username)
                elif status == "error":
                    self.log(f"[ERROR] {message}")
                else:
                    # fallback in the case that we cannot recognize status
                    self.log(f"[RESPONSE] {obj}")

            except json.JSONDecodeError:
                self.log(f"[Invalid JSON from server] {line}")
        else:
            line = line.strip()
            if line.startswith("OK"):
                self.log("[SUCCESS] " + line[2:].strip())
            elif line.startswith("ERR"):
                self.log("[ERROR] " + line[3:].strip())
            elif line.startswith("MSG"):
                self.log("[MESSAGE] " + line[3:].strip())
            elif line.startswith("P "):
                tokens = line.split(" ", 2)
                if len(tokens) >= 3:
                    sender = tokens[1]
                    content = tokens[2]
                    self.log(f"[New Message] from={sender}: {content}")
            else:
                self.log("[RESPONSE] " + line)

    def log(self, msg):
        """
        Log a message to the text area.
        """
        self.text_area.config(state='normal')
        self.text_area.insert(tk.END, msg + "\n")
        self.text_area.config(state='disabled')
        self.text_area.see(tk.END)

    def handle_enter(self, event):
        """
        Directly send typed lines for custom wire
        """
        if not self.use_json:
            line = self.entry.get()
            self.entry.delete(0, tk.END)
            self.send_line(line)

    # ===== sending data =====
    
    def send_line(self, line: str):
        """
        Send a line of text to the server.
        """
        try:
            self.sock.sendall((line + "\n").encode('utf-8'))
        except:
            self.log("[Error] Failed to send wire")

    def send_json(self, obj):
        """
        Send a JSON object to the server.
        """

        try:
            line = json.dumps(obj) + "\n"
            self.sock.sendall(line.encode('utf-8'))
        except Exception as e:
            self.log(f"[Error] Failed to send JSON: {e}")

    # ===== dialogs =====

    def create_account_dialog(self):
        """
        Opens a dialog to create a new account with a username, password, and display name.
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
            username = user_entry.get().strip()
            password = pass_entry.get()
            display = disp_entry.get()

            hashed_password = hash_password(password)
            w.destroy()
            if self.use_json:
                req = {
                    "command": "create_user",
                    "username": username,
                    "hashed_password": hashed_password,
                    "display_name": display
                }
                self.send_json(req)
            else:
                #custom protocol
                line = f"CRE {username} {hashed_password} {display}"
                self.send_line(line)

        tk.Button(w, text="OK", command=on_ok).pack()

    def login_dialog(self):
        """
        Opens a dialog to log in with a username and password.
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
            user = user_entry.get()
            pw = pass_entry.get()
            hashed_password = hash_password(pw)
            w.destroy()
            if self.use_json:
                req = {"command": "login", "username": user, "hashed_password": hashed_password}
                self.send_json(req)
            else:
                line = f"LOG {user} {hashed_password}"
                self.send_line(line)
        tk.Button(w, text="OK", command=on_ok).pack()

    def logout_dialog(self):
        """
        Ask if the user wants to log out
        """
        w = tk.Toplevel(self.root)
        w.title("Logout")

        tk.Label(w, text="Are you sure you want to logout?").pack()

        def on_ok():
            w.destroy()
            if self.use_json:
                req = {"command": "logout"}
                self.send_json(req)
            else:
                self.send_line("LGO")

        tk.Button(w, text="OK", command=on_ok).pack()

    def prompt_login_for_existing_user(self, username):
        """
        Pops up a small dialog to let user log in with the known username.
        """
        w = tk.Toplevel(self.root)
        w.title(f"Login: {username} already exists")

        tk.Label(w, text=f"Username: {username}").pack()
        tk.Label(w, text="Password").pack()

        pass_entry = tk.Entry(w, show="*")
        pass_entry.pack()

        def on_ok():
            pw = pass_entry.get()
            hashed_password = hash_password(pw)
            w.destroy()
            if self.use_json:
                # send login command with known username
                req = {"command": "login", "username": username, "hashed_password": hashed_password}
                self.send_json(req)
            else:
                # custom protocol
                self.send_line(f"LOG {username} {hashed_password}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def send_dialog(self):
        """
        Opens a dialog to send a message to another user.
        """

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
                line = f"SND {to_user} {msg}"
                self.send_line(line)

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
            pattern_to_use = pattern.get().strip()
            print(pattern_to_use)
            if not pattern_to_use:
                pattern_to_use = "*"
            if self.use_json:
                req = {"command": "list_users", "pattern": pattern_to_use}
                self.send_json(req)
                self.current_listbox = account_listbox  
            else:
                line = f"LIS {pattern_to_use}"
                self.send_line(line)
                self.current_listbox = account_listbox

        tk.Button(w, text="OK", command=on_ok).pack()


    def read_messages(self):
        """
        Pop up a dialog that:
        1) Shows a checkbox to choose "unread only" versus all messages
        2) An entry field for how many messages to fetch
        3) Sends the request with those parameters to the server
        """
        w = tk.Toplevel(self.root)
        w.title("Read Messages")

        unread_var = tk.BooleanVar(value=False)
        chk = tk.Checkbutton(w, text="Only Unread?", variable=unread_var)
        chk.pack()

        tk.Label(w, text="How many messages (leave blank for all)").pack()
        limit_entry = tk.Entry(w)
        limit_entry.pack()

        def on_ok():
            only_unread = unread_var.get()
            limit_str = limit_entry.get().strip()
            w.destroy()

            if self.use_json:
                req = {"command": "read_messages"}
                if only_unread:
                    req["only_unread"] = True
                if limit_str:
                    try:
                        limit_val = int(limit_str)
                        req["limit"] = limit_val
                    except ValueError:
                        self.log("[Error] Invalid integer for limit.")
                        return
                self.send_json(req)
            else:
                parts = ["RD"]
                if only_unread:
                    parts.append("UNREAD")
                if limit_str:
                    try:
                        limit_val = int(limit_str)
                        parts.append("LIMIT")
                        parts.append(str(limit_val))
                    except ValueError:
                        self.log("[Error] Invalid integer for limit.")
                        return
                line = " ".join(parts)
                self.send_line(line)


        tk.Button(w, text="OK", command=on_ok).pack()

    def delete_msg_dialog(self):
        """
        Pop up a dialog that:
        1) Asks for a message ID or comma-separated list of message IDs
        2) Sends the request to the server to delete the message(s)
        """
        w = tk.Toplevel(self.root)
        w.title("Delete Message(s)")

        tk.Label(w, text="Message ID(s) (comma separated)").pack()
        msg_id_entry = tk.Entry(w)
        msg_id_entry.pack()

        def on_ok():
            raw_input = msg_id_entry.get().strip()
            w.destroy()
            if not raw_input:
                return

            if self.use_json:
                if "," in raw_input:
                    parts = [p.strip() for p in raw_input.split(",") if p.strip()]
                    try:
                        ids_list = [int(x) for x in parts]
                    except ValueError:
                        self.log("[Error] IDs must be numeric.")
                        return
                    req = {"command": "delete_messages", "message_ids": ids_list}
                else:
                    try:
                        single_id = int(raw_input)
                    except ValueError:
                        self.log("[Error] ID must be numeric.")
                        return
                    req = {"command": "delete_messages", "message_id": single_id}
                self.send_json(req)
            else:
                line = f"DELMSG {raw_input}"
                self.send_line(line)

        tk.Button(w, text="OK", command=on_ok).pack()

    def delete_account(self):
        """
        Pop up a dialog to confirm account deletion
        """
        w = tk.Toplevel(self.root)
        w.title("Delete Account")
        tk.Label(w, text="Are you sure you want to delete your account? Press OK to confirm.").pack()
        def on_ok():
            w.destroy()
            if self.use_json:
                req = {"command": "delete_user"}
                self.send_json(req)
            else:
                self.send_line("DELUSER")

        tk.Button(w, text="OK", command=on_ok).pack()

    # ===== run main loop =====
    def run(self):
        """
        Start the main loop and connect to the server.
        """
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

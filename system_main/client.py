import tkinter as tk
import socket
import threading
import json

class TkClient:
    def __init__(self, host="127.0.0.1", port=12345, use_json=True):
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
        tk.Button(self.btn_frame, text="List", command=self.list_accounts).pack(side=tk.LEFT)
        tk.Button(self.btn_frame, text="Read", command=self.read_messages).pack(side=tk.LEFT)
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
        if self.use_json:
            try:
                obj = json.loads(line)
                status = obj.get("status")
                message = obj.get("message", "")
                if status == "success":
                    self.log(f"[SUCCESS] {message}")
                    # If there are messages in the response, display them
                    if "messages" in obj:
                        self.log("Messages:")
                        for m in obj["messages"]:
                            self.log(f"  ID={m['id']}, from={m['sender_id']}, content={m['content']}")
                elif status == "error":
                    self.log(f"[ERROR] {message}")
                else:
                    # Fallback if there's no status or it's something else
                    self.log(f"[RESPONSE] {obj}")
            except json.JSONDecodeError:
                self.log(f"[Invalid JSON from server] {line}")
        else:
            # Custom wire wich we have not implemented yet
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
        except:
            self.log("[Error] Failed to send JSON")

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
                req = {"command": "send_message", "to": to_user, "content": msg}
                self.send_json(req)
            else:
                self.send_line(f"SEND {to_user} {msg}")

        tk.Button(w, text="OK", command=on_ok).pack()

    def list_accounts(self):
        if self.use_json:
            self.send_json({"command": "list_users"})
        else:
            self.send_line("LIST")

    def read_messages(self):
        if self.use_json:
            self.send_json({"command": "read_messages"})
        else:
            self.send_line("READ")

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
                req = {"command": "delete_messages", "id": int(mid)}
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

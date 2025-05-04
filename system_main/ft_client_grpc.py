#!/usr/bin/env python3
import tkinter as tk
from tkinter import simpledialog, messagebox
import grpc, argparse, time
import chat_pb2, chat_pb2_grpc
from utils import hash_password

class FTClient:
    def __init__(self, servers, max_retries=3, retry_delay=0.1):
        self.servers = servers
        self.idx = 0
        self.auth_stub = None
        self.auction_stub = None
        self.current_user = None
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Build UI…
        self.root = tk.Tk()
        self.root.title("FT Auction Client")
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(padx=10, pady=10)
        for (txt, cmd) in [
            ("Create User", self.create_user),
            ("Login", self.login),
            ("Start Auction", self.start_auction),
            ("Submit Bid", self.submit_bid),
            ("Get Winner", self.get_winner)
        ]:
            tk.Button(btn_frame, text=txt, width=12, command=cmd).pack(side=tk.LEFT, padx=5)
        self.log = tk.Text(self.root, state='disabled', width=70, height=15)
        self.log.pack(padx=10, pady=(0,10))

        self.connect()

    def log_msg(self, msg):
        self.log.config(state='normal')
        self.log.insert(tk.END, msg + "\n")
        self.log.config(state='disabled')
        self.log.see(tk.END)

    def connect(self):
        for _ in range(len(self.servers)):
            addr = self.servers[self.idx]
            try:
                ch = grpc.insecure_channel(addr)
                grpc.channel_ready_future(ch).result(timeout=5)
                auth = chat_pb2_grpc.AuthServiceStub(ch)
                auth.Login(
                    chat_pb2.LoginRequest(username="ping", hashed_password=hash_password("x")),
                    timeout=2
                )
                self.auth_stub = auth
                self.auction_stub = chat_pb2_grpc.AuctionServiceStub(ch)
                self.log_msg(f"Connected to {addr}")
                return
            except Exception as e:
                self.log_msg(f"Connect failed to {addr}: {e}")
                self.idx = (self.idx + 1) % len(self.servers)
        self.log_msg("ERROR: All servers unreachable")
        messagebox.showerror("Connection Error", "Could not connect to any server.")
        self.root.destroy()

    def safe_rpc(self, rpc_call, request):
        last_exc = None
        for _ in range(self.max_retries):
            try:
                return rpc_call(request)
            except grpc.RpcError as e:
                last_exc = e
                if e.code() == grpc.StatusCode.UNAVAILABLE:
                    self.log_msg("Leader unavailable—reconnecting…")
                    self.connect()
                    time.sleep(self.retry_delay)
                    continue
                break
        raise last_exc

    def create_user(self):
        u = simpledialog.askstring("Create User", "Username:")
        if not u: return
        pw = simpledialog.askstring("Create User", f"Password for {u}:", show="*")
        if pw is None: return
        req = chat_pb2.CreateUserRequest(username=u,
                                         hashed_password=hash_password(pw),
                                         display_name="")
        try:
            r = self.safe_rpc(self.auth_stub.CreateUser, req)
            self.log_msg(f"CreateUser → {r.status}: {r.message}")
        except Exception as e:
            self.log_msg(f"CreateUser error: {e}")

    def login(self):
        u = simpledialog.askstring("Login", "Username:")
        if not u: return
        pw = simpledialog.askstring("Login", f"Password for {u}:", show="*")
        if pw is None: return
        req = chat_pb2.LoginRequest(username=u, hashed_password=hash_password(pw))
        try:
            r = self.safe_rpc(self.auth_stub.Login, req)
            self.log_msg(f"Login → {r.status}")
            if r.status == "success":
                self.current_user = u
        except Exception as e:
            self.log_msg(f"Login error: {e}")

    def start_auction(self):
        aid = simpledialog.askstring("Start Auction", "Auction ID:")
        if not aid: return
        dl = int(time.time()) + 30
        req = chat_pb2.StartAuctionRequest(auction_id=aid, deadline_unix=dl)
        try:
            r = self.safe_rpc(self.auction_stub.StartAuction, req)
            self.log_msg(f"StartAuction → {r.status}")
        except Exception as e:
            self.log_msg(f"StartAuction error: {e}")

    def submit_bid(self):
        if not self.current_user:
            messagebox.showwarning("Not logged in", "Please log in first.")
            return
        aid = simpledialog.askstring("Submit Bid", "Auction ID:")
        if not aid: return
        amt = simpledialog.askfloat("Submit Bid", f"Bid amount for {self.current_user}:")
        if amt is None: return
        req = chat_pb2.SubmitBidRequest(auction_id=aid,
                                        bidder_id=self.current_user,
                                        amount=amt)
        try:
            r = self.safe_rpc(self.auction_stub.SubmitBid, req)
            self.log_msg(f"SubmitBid → {r.status}")
        except Exception as e:
            self.log_msg(f"SubmitBid error: {e}")

    def get_winner(self):
        aid = simpledialog.askstring("Get Winner", "Auction ID:")
        if not aid: return
        req = chat_pb2.GetWinnerRequest(auction_id=aid)
        try:
            r = self.safe_rpc(self.auction_stub.GetWinner, req)
            if r.status == "success":
                self.log_msg(f"Winner: {r.winner_id}, pays {r.price}")
            else:
                self.log_msg(f"GetWinner → {r.status}: {r.message}")
        except Exception as e:
            self.log_msg(f"GetWinner error: {e}")

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--servers",
                   default="127.0.0.1:50051,127.0.0.1:50052,127.0.0.1:50053",
                   help="comma-separated gRPC endpoints")
    args = p.parse_args()
    srv = args.servers.split(",")
    FTClient(srv).run()

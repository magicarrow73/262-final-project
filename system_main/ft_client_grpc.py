#!/usr/bin/env python3
import threading
import time
import tkinter as tk
from tkinter import simpledialog, messagebox
import grpc, argparse
import chat_pb2, chat_pb2_grpc
from google.protobuf import empty_pb2
from utils import hash_password

class FTClient:
    def __init__(self, servers, max_retries=3, retry_delay=0.1):
        self.servers = servers
        self.idx = 0
        self.auth_stub = None
        self.auction_stub = None
        self.channel = None
        self.current_user = None
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self.known_auctions     = {}  # auction_id → ended flag
        self.submitted_auctions = set()
        self.known_bundle_auctions = {}
        self.submitted_bundles = set()

        # Build UI
        self.root = tk.Tk()
        self.root.title("FT Auction Client")

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(padx=10, pady=10)
        for (txt, cmd) in [
            ("Create User",    self.create_user),
            ("Login",          self.login),
            ("Start Bundle Auction",   self.start_bundle),
            ("Join Bundle Auction",    self.join_bundle),
            ("List Bundle Auctions", self.list_bundle_auctions),
            # ("Start Single-Item Auction",  self.start_auction),
            # ("Submit Bid",     self.submit_bid),
            ("Get Winner",     self.get_winner),
            # ("List Auctions",  self.list_auctions),
        ]:
            tk.Button(btn_frame, text=txt, width=12, command=cmd).pack(side=tk.LEFT, padx=5)

        self.log = tk.Text(self.root, state='disabled', width=70, height=15)
        self.log.pack(padx=10, pady=(0,10))

        # Initial connection and start notification loop
        self.connect()
        self._start_notification_loop()

    def log_msg(self, msg):
        self.log.config(state='normal')
        self.log.insert(tk.END, msg + "\n")
        self.log.config(state='disabled')
        self.log.see(tk.END)

    def connect(self):
        """
        Try each server until one is reachable. Wait for channel readiness
        before issuing the ping Login RPC.
        """
        for _ in range(len(self.servers)):
            addr = self.servers[self.idx]
            try:
                ch = grpc.insecure_channel(addr)
                self.channel = ch
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
        """
        Try up to max_retries. On UNAVAILABLE, reconnect and retry.
        """
        for _ in range(self.max_retries):
            try:
                return rpc_call(request)
            except grpc.RpcError as e:
                if e.code() == grpc.StatusCode.UNAVAILABLE:
                    self.log_msg("Servers are reconfiguring—retrying...")
                    self.connect()
                    time.sleep(self.retry_delay)
                    continue
                # non‑transient
                details = e.details() if hasattr(e, 'details') else str(e)
                self.log_msg(f"Error: {details}")
                return None
        self.log_msg("Servers still reconfiguring—please try again later.")
        return None

    def create_user(self):
        u = simpledialog.askstring("Create User", "Username:")
        if not u: return
        pw = simpledialog.askstring("Create User", f"Password for {u}:", show="*")
        if pw is None: return
        req = chat_pb2.CreateUserRequest(
            username=u,
            hashed_password=hash_password(pw),
            display_name=""
        )
        r = self.safe_rpc(self.auth_stub.CreateUser, req)
        if r: self.log_msg(f"CreateUser → {r.status}: {r.message}")

    def login(self):
        u = simpledialog.askstring("Login", "Username:")
        if not u: return
        pw = simpledialog.askstring("Login", f"Password for {u}:", show="*")
        if pw is None: return
        req = chat_pb2.LoginRequest(username=u, hashed_password=hash_password(pw))
        r = self.safe_rpc(self.auth_stub.Login, req)
        if r:
            self.log_msg(f"Login → {r.status}")
            if r.status == "success":
                self.current_user = u

    def start_auction(self):
        aid = simpledialog.askstring("Start Auction", "Auction ID:")
        if not aid: return
        dur = simpledialog.askinteger("Start Auction", "Duration (seconds):")
        item = simpledialog.askstring("Start Auction", "Item name:")
        if dur is None: return
        req = chat_pb2.StartAuctionRequest(
            auction_id=aid,
            duration_seconds=dur,
            item_name=item or ""
        )
        r = self.safe_rpc(self.auction_stub.StartAuction, req)
        if r: self.log_msg(f"StartAuction → {r.status}")

    
    def start_bundle(self):
        aid = simpledialog.askstring("Bundle Auction", "Auction ID:")
        if not aid:
            return
        items_csv = simpledialog.askstring("Bundle Auction",
                                        "Comma-separated item names (CPU,GPU,…):")
        if not items_csv:
            return
        dur = simpledialog.askinteger("Bundle Auction", "Duration (seconds, 0 = untimed):", initialvalue=0)
        items = [s.strip() for s in items_csv.split(",") if s.strip()]
        req = chat_pb2.StartBundleAuctionRequest(
            auction_id=aid,
            creator_id=self.current_user or "anon",
            item_names=items,
            duration_seconds=dur or 0
        )
        r = self.safe_rpc(self.auction_stub.StartBundleAuction, req)
        if r:
            self.log_msg(f"StartBundleAuction → {r.status}: {r.message}")


    def join_bundle(self):
        aid = simpledialog.askstring("Join Bundle Auction", "Auction ID:")
        if not aid:
            return
        items_resp = self.safe_rpc(self.auction_stub.ListBundleItems,chat_pb2.ListBundleItemsRequest(auction_id=aid))
        if not items_resp:
            return
        items = list(items_resp.item_names)
        if not items:
            messagebox.showerror("No items", "Auction not found or has no items.")
            return

        win = tk.Toplevel(self.root)
        win.title(f"Bid on {aid}")
        vars_ = [tk.IntVar() for _ in items]
        for i, name in enumerate(items):
            tk.Checkbutton(win, text=name, variable=vars_[i]).grid(row=i, column=0, sticky="w")
        tk.Label(win, text="Value:").grid(row=0, column=1)
        val_entry = tk.Entry(win); val_entry.grid(row=0, column=2)

        def send_bid():
            try:
                value = float(val_entry.get())
                assert value > 0
            except Exception:
                messagebox.showerror("Bad value", "Enter a positive number.")
                return
            bundle = [i for i,v in enumerate(vars_) if v.get()]
            if not bundle:
                messagebox.showerror("No items", "Select at least one item.")
                return
            r = self.safe_rpc(self.auction_stub.SubmitBundleBid,
                chat_pb2.SingleMindedBid(
                    auction_id=aid,
                    bidder_id=self.current_user or "anon",
                    item_ids=bundle,
                    value=value
                ))
            if r is not None:
                self.log_msg(f"Bid accepted on {aid}: {bundle} @ {value}")
            win.destroy()

        tk.Button(win, text="Submit Bid", command=send_bid)\
        .grid(row=len(items), columnspan=3, pady=5)

        def run_now():
            res = self.safe_rpc(self.auction_stub.RunGreedyAuction,
                chat_pb2.RunGreedyAuctionRequest(auction_id=aid,requester_id=self.current_user or "anon"))
            if res:
                msg = "\n".join(
                    f"{w.bidder_id} wins {[items[i] for i in w.item_ids]} @ {w.payment:.2f}"
                    for w in res.winners)
                messagebox.showinfo("Results", msg or "No winners")
        tk.Button(win, text="Run Auction", command=run_now).\
        grid(row=len(items)+1, columnspan=3, pady=3)


    def submit_bid(self):
        if not self.current_user:
            messagebox.showwarning("Not logged in", "Please log in first.")
            return
        aid = simpledialog.askstring("Submit Bid", "Auction ID:")
        if not aid: return
        amt = simpledialog.askfloat("Submit Bid", f"Bid amount for {self.current_user}:")
        if amt is None: return
        req = chat_pb2.SubmitBidRequest(
            auction_id=aid,
            bidder_id=self.current_user,
            amount=amt
        )
        r = self.safe_rpc(self.auction_stub.SubmitBid, req)
        if r:
            self.log_msg(f"SubmitBid → {r.status}")
            if r.status == "success":
                self.submitted_auctions.add(aid)

    def get_winner(self):
        aid = simpledialog.askstring("Get Winner", "Auction ID:")
        if not aid: return

        # bundle auction
        br = self.safe_rpc(self.auction_stub.RunGreedyAuction, chat_pb2.RunGreedyAuctionRequest(auction_id = aid, requester_id = self.current_user or "anon"))
        if br and getattr(br, "winners", None):
            winners = ", ".join(
                f"{w.bidder_id} → ${w.payment:.2f}"
                for w in br.winners)
            self.log_msg(f"[Bundle] {aid} → {winners or 'no valid allocation'}")
            return
        
        # single item auction
        r = self.safe_rpc(self.auction_stub.GetWinner,chat_pb2.GetWinnerRequest(auction_id=aid))
        if r:
            if r.status == "success":
                self.log_msg(f"Winner: {r.winner_id}, pays {r.price}")
            else:
                self.log_msg(f"GetWinner → {r.status}: {r.message}")

    def list_auctions(self):
        r = self.safe_rpc(self.auction_stub.ListAuctions, empty_pb2.Empty())
        if not r: return
        self.log_msg("Auctions:")
        for a in r.auctions:
            status = "Ended" if a.ended else f"{a.time_left}s left"
            self.log_msg(f" • {a.auction_id}: {a.item_name} [{status}]")

    def list_bundle_auctions(self):
        r = self.safe_rpc(self.auction_stub.ListBundleAuctions, empty_pb2.Empty())
        if not r: return
        self.log_msg("Bundle Auctions:")

        for a in r.auctions:
            status = "Ended" if a.ended else f"{a.time_left}s left"
            names  = ", ".join(a.item_names)
            self.log_msg(f" • {a.auction_id}: [{names}]  {status}")
            if a.ended:
                res = self.safe_rpc(self.auction_stub.RunGreedyAuction,
                                    chat_pb2.RunGreedyAuctionRequest(
                                        auction_id=a.auction_id,
                                        requester_id=self.current_user or ""))
                if res:
                    for w in res.winners:
                        bundle = [a.item_names[i] for i in w.item_ids]
                        self.log_msg(f"      → {w.bidder_id} wins {bundle} @ {w.payment:.2f}")

    def _start_notification_loop(self):
        t = threading.Thread(target=self._notification_loop, daemon=True)
        t.start()

    def _notification_loop(self):
        while True:
            time.sleep(5)
            r = self.safe_rpc(self.auction_stub.ListAuctions, empty_pb2.Empty())
            if r:
                for a in r.auctions:
                    prev = self.known_auctions.get(a.auction_id)
                    if prev is None:
                        self.known_auctions[a.auction_id] = a.ended
                        continue
                    if not prev and a.ended:
                        msg = f"Auction {a.auction_id} ended: {a.item_name}"
                        if a.auction_id in self.submitted_auctions:
                            gr = self.safe_rpc(
                                self.auction_stub.GetWinner,
                                chat_pb2.GetWinnerRequest(auction_id=a.auction_id)
                            )
                            if gr and gr.status == "success":
                                if gr.winner_id == self.current_user:
                                    msg += f" — You won! Pay {gr.price}"
                                else:
                                    msg += f" — Winner: {gr.winner_id}, price: {gr.price}"
                        self.root.after(0, lambda m=msg: self.log_msg(m))
                    self.known_auctions[a.auction_id] = a.ended

            br = self.safe_rpc(self.auction_stub.ListBundleAuctions, empty_pb2.Empty())
            if not br: continue

            for b in br.auctions:
                prev = self.known_bundle_auctions.get(b.auction_id)
                if prev is None:
                    self.known_bundle_auctions[b.auction_id] = b.ended
                    continue
                if not prev and b.ended:
                    gr = self.safe_rpc(self.auction_stub.RunGreedyAuction, chat_pb2.RunGreedyAuctionRequest(auction_id=b.auction_id, requester_id=self.current_user or "anon"))
                    msg = f"Bundle auction {b.auction_id} ended."
                    if gr and gr.winners:
                        winners = ", ".join(f"{w.bidder_id} pays ${w.payment:.2f}" for w in gr.winners)
                        msg += " Winners → " + winners
                    self.root.after(0, lambda m=msg: self.log_msg(m))
                self.known_bundle_auctions[b.auction_id] = b.ended

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "--servers",
        default="127.0.0.1:50051,127.0.0.1:50052,127.0.0.1:50053",
        help="comma-separated gRPC endpoints"
    )
    args = p.parse_args()
    srv = args.servers.split(",")
    FTClient(srv).run()

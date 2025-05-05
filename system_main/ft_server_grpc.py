#!/usr/bin/env python3
"""
ft_server_grpc.py

Fault‑tolerant gRPC server using RaftDB for a 2nd‑price auction.
"""

import threading
import time
import signal
import sys
import os
import grpc
from concurrent import futures
import argparse

import chat_pb2
import chat_pb2_grpc
from raft_db import RaftDB
from utils import verify_password
from google.protobuf import empty_pb2
from system_main.greedy_vcg import Bid, greedy_vcg

SERVER_LOG_FILE = "server_data_usage.log"

def start_grpc_server(db, port: int, max_workers: int = 10):
    """
    Wrap AuthService + AuctionService around an existing RaftDB and
    start a gRPC server on the given port.  Returns the `grpc.Server`
    so callers can stop it later with `server.stop(grace)`.
    """
    from concurrent import futures
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    chat_pb2_grpc.add_AuthServiceServicer_to_server(AuthService(db), server)
    chat_pb2_grpc.add_AuctionServiceServicer_to_server(AuctionService(db), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    return server

def log_data_usage(method_name: str, request, response):
    header = "" if os.path.exists(SERVER_LOG_FILE) else "method,req_size,resp_size\n"
    with open(SERVER_LOG_FILE, "a") as f:
        f.write(header + f"{method_name},{len(request.SerializeToString())},{len(response.SerializeToString())}\n")

class AuthService(chat_pb2_grpc.AuthServiceServicer):
    def __init__(self, raft):
        self.raft = raft

    def CreateUser(self, req, ctx):
        existing = self.raft.get_user_by_username(req.username)
        if existing:
            resp = chat_pb2.CreateUserResponse(status="user_exists", message="already exists", username=req.username)
        else:
            ok = self.raft.create_user(req.username, req.hashed_password, req.display_name, sync=True)
            resp = chat_pb2.CreateUserResponse(
                status="success" if ok else "error",
                message="created" if ok else "db error",
                username=req.username
            )
        log_data_usage("CreateUser", req, resp)
        return resp

    def Login(self, req, ctx):
        user = self.raft.get_user_by_username(req.username)
        if not user or not verify_password(req.hashed_password, user["password_hash"]):
            resp = chat_pb2.LoginResponse(status="error", message="bad credentials")
        else:
            self.raft.user_login(req.username, sync=True)
            resp = chat_pb2.LoginResponse(status="success", message="logged in")
        log_data_usage("Login", req, resp)
        return resp

    def Logout(self, req, ctx):
        self.raft.user_logout(req.username, sync=True)
        resp = chat_pb2.LogoutResponse(status="success", message="logged out")
        log_data_usage("Logout", req, resp)
        return resp

class AuctionService(chat_pb2_grpc.AuctionServiceServicer):
    def __init__(self, raft):
        self.raft = raft

    def StartAuction(self, req, ctx):
        ok = self.raft.start_auction(
            req.auction_id,
            req.duration_seconds,
            req.item_name,
            sync=True
        )
        resp = chat_pb2.StartAuctionResponse(
            status="success" if ok else "error",
            message="started" if ok else "already exists"
        )
        log_data_usage("StartAuction", req, resp)
        return resp
    
    def StartBundleAuction(self, req, ctx):
        try:
            self.raft.execute(
                "INSERT INTO bundle_meta (auction_id,creator,deadline) VALUES (?,?,?)",
                (req.auction_id,
                req.creator_id,
                time.time()+req.duration_seconds if req.duration_seconds else None))
            for idx, name in enumerate(req.item_names):
                self.raft.execute(
                    "INSERT INTO bundle_item (auction_id,item_idx,item_name) VALUES (?,?,?)",
                    (req.auction_id, idx, name))
            return chat_pb2.StartBundleAuctionResponse(status="success", message="created")
        except Exception:
            return chat_pb2.StartBundleAuctionResponse(status="error",   message="exists")

    def ListBundleItems(self, req, ctx):
        rows = self.raft.query(
            "SELECT item_name FROM bundle_item WHERE auction_id=? ORDER BY item_idx",
            (req.auction_id,))
        if not rows:
            ctx.abort(grpc.StatusCode.NOT_FOUND, "auction unknown")
        return chat_pb2.ListBundleItemsResponse(item_names=[n for (n,) in rows])

    def ListBundleAuctions(self, req, ctx):
        resp = chat_pb2.ListBundleAuctionsResponse()
        now  = time.time()
        for aid, dl, ended in self.raft.query(
                "SELECT auction_id,deadline,ended FROM bundle_meta"):
            names = [n for (n,) in self.raft.query(
                "SELECT item_name FROM bundle_item WHERE auction_id=? ORDER BY item_idx",
                (aid,))]
            tleft = 0 if not dl else max(0, int(dl - now))
            resp.auctions.add(
                auction_id = aid,
                ended      = bool(ended),
                time_left  = tleft,
                item_names = names)
        return resp

    def SubmitBundleBid(self, req, ctx):
        row = self.raft.query_one(
            "SELECT ended FROM bundle_meta WHERE auction_id=?", (req.auction_id,))
        if not row or row[0]:
            ctx.abort(grpc.StatusCode.FAILED_PRECONDITION, "auction closed/unknown")

        mask = 0
        for i in req.item_ids:
            mask |= 1 << i

        self.raft.execute(
            "INSERT INTO bundle_bid (auction_id,bidder_id,bundlemask,value)"
            " VALUES (?,?,?,?)",
            (req.auction_id, req.bidder_id, mask, req.value))
        return empty_pb2.Empty()

    def EndAuction(self, req, ctx):
        ok = self.raft.end_auction(req.auction_id, sync=True)
        resp = chat_pb2.EndAuctionResponse(
            status="success" if ok else "error",
            message="ended" if ok else "no such or already ended"
        )
        log_data_usage("EndAuction", req, resp)
        return resp

    def GetWinner(self, req, ctx):
        res = self.raft.get_auction_result(req.auction_id)
        if not res:
            resp = chat_pb2.GetWinnerResponse(status="error", message="not closed or no such")
        else:
            w, wb, price = res
            resp = chat_pb2.GetWinnerResponse(
                status="success", message="ok",
                winner_id=w, winning_bid=wb, price=price
            )
        log_data_usage("GetWinner", req, resp)
        return resp

    def ListAuctions(self, req, ctx):
        resp = chat_pb2.ListAuctionsResponse()
        now = int(time.time())
        for aid, item, ended, deadline in self.raft.list_auctions():
            tleft = max(0, deadline - now)
            resp.auctions.add(
                auction_id=aid,
                item_name=item,
                ended=ended,
                time_left=tleft
            )
        return resp
    
    def RunGreedyAuction(self, req, ctx):
        creator, dl, ended = self.raft.query_one(
            "SELECT creator,deadline,ended FROM bundle_meta WHERE auction_id=?",
            (req.auction_id,))

        # permissions & timing
        if not ended:
            if dl and time.time() < dl:
                ctx.abort(grpc.StatusCode.FAILED_PRECONDITION, "deadline not reached")
            if req.requester_id != creator:
                ctx.abort(grpc.StatusCode.PERMISSION_DENIED, "only creator may close")

        # winners already cached?
        rows = self.raft.query(
            "SELECT bidder_id,bundlemask,payment FROM bundle_winner WHERE auction_id=?",
            (req.auction_id,))
        if rows:
            winners = [Bid(b,bm,0) for b,bm,_ in rows]
            pay = {b:p for b,_,p in rows}
        else:
            # fetch bids
            bids = [Bid(b,mask,v) for b,mask,v in
                    self.raft.query(
                        "SELECT bidder_id,bundlemask,value FROM bundle_bid WHERE auction_id=?",
                        (req.auction_id,))]
            item_count = self.raft.query_one(
                "SELECT COUNT(*) FROM bundle_item WHERE auction_id=?",
                (req.auction_id,))[0]

            winners, pay = greedy_vcg(bids, item_count)

            # persist results atomically
            self.raft.execute("BEGIN")
            self.raft.execute("UPDATE bundle_meta SET ended=1 WHERE auction_id=?",
                            (req.auction_id,))
            for w in winners:
                self.raft.execute(
                    "INSERT INTO bundle_winner (auction_id,bidder_id,bundlemask,payment)"
                    " VALUES (?,?,?,?)",
                    (req.auction_id, w.bidder_id, w.bundle, pay[w.bidder_id]))
            self.raft.execute("DELETE FROM bundle_bid WHERE auction_id=?",
                            (req.auction_id,))
            self.raft.execute("COMMIT")

        # build protobuf
        resp = chat_pb2.GreedyResult()
        for w in winners:
            bw = resp.winners.add()
            bw.bidder_id = w.bidder_id
            bw.item_ids.extend([i for i in range(w.bundle.bit_length()) if w.bundle & (1<<i)])
            bw.payment = pay[w.bidder_id]
        return resp

def serve(host, port, node_id, raft_port, peers):
    # initialize Raft-backed DB
    raft = RaftDB(f"{host}:{raft_port}", peers, f"node{node_id}.db")

    # bundle auction tables
    raft.execute("""
    CREATE TABLE IF NOT EXISTS bundle_meta (
      auction_id TEXT PRIMARY KEY,
      creator    TEXT NOT NULL,
      deadline   REAL,        -- NULL = untimed
      ended      INTEGER DEFAULT 0
    );
    """)
    raft.execute("""
    CREATE TABLE IF NOT EXISTS bundle_item (
      auction_id TEXT,
      item_idx   INTEGER,
      item_name  TEXT,
      PRIMARY KEY (auction_id,item_idx)
    );
    """)
    raft.execute("""
    CREATE TABLE IF NOT EXISTS bundle_bid (
      auction_id TEXT,
      bidder_id  TEXT,
      bundlemask INTEGER,
      value      REAL
    );
    """)
    raft.execute("""
    CREATE TABLE IF NOT EXISTS bundle_winner (
      auction_id TEXT,
      bidder_id  TEXT,
      bundlemask INTEGER,
      payment    REAL,
      PRIMARY KEY (auction_id,bidder_id)
    );
    """)

    # start debug thread
    def debug_raft():
        while True:
            st = raft.getStatus() or {}
            role = {0:"Follower",1:"Candidate",2:"Leader"}.get(st.get("state"), "Unknown")
            print(f"[DEBUG] Node{node_id} role={role}  leader={st.get('leader')}  quorum={st.get('has_quorum')}")
            time.sleep(5)
    threading.Thread(target=debug_raft, daemon=True).start()

    # wait for cluster to form
    time.sleep(5)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    auth_svc    = AuthService(raft)
    auction_svc = AuctionService(raft)
    chat_pb2_grpc.add_AuthServiceServicer_to_server(auth_svc, server)
    chat_pb2_grpc.add_AuctionServiceServicer_to_server(auction_svc, server)

    # background watcher to reliably end auctions
    def auction_watcher():
        while True:
            now = time.time()
            for aid, item, ended, deadline in raft.list_auctions():
                if not ended and deadline and now > deadline:
                    raft.end_auction(aid, sync=True)

            for aid, creator in raft.query(
                    "SELECT auction_id,creator FROM bundle_meta "
                    "WHERE ended=0 AND deadline IS NOT NULL AND deadline < ?",(now,)):
                try:
                    auction_svc.RunGreedyAuction(chat_pb2.RunGreedyAuctionRequest(auction_id=aid,requester_id=creator),None)
                except grpc.RpcError:
                    pass

            time.sleep(1)

    threading.Thread(target=auction_watcher, daemon=True).start()

    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print(f"Node{node_id} gRPC@[::]:{port}, Raft@{host}:{raft_port}")

    def handle_shutdown(signum, frame):
        print(f"Node{node_id} shutting down…")
        raft.close()
        server.stop(5)
        sys.exit(0)
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    server.wait_for_termination()

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--node-id",   type=int, required=True)
    p.add_argument("--host",      default="127.0.0.1")
    p.add_argument("--port",      type=int, required=True)
    p.add_argument("--raft-port", type=int, required=True)
    p.add_argument("--peers",     default="", help="comma-separated raft peer addresses")
    args = p.parse_args()

    peer_list = args.peers.split(",") if args.peers else []
    serve(args.host, args.port, args.node_id, args.raft_port, peer_list)

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

SERVER_LOG_FILE = "server_data_usage.log"

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
        ok = self.raft.start_auction(req.auction_id, req.deadline_unix, sync=True)

        # schedule the end on every node, not just leaders
        delay = max(0, req.deadline_unix - int(time.time()))
        threading.Timer(delay, lambda: self.raft.end_auction(req.auction_id, sync=True)).start()

        resp = chat_pb2.StartAuctionResponse(
            status="success" if ok else "error",
            message="started" if ok else "already exists"
        )
        log_data_usage("StartAuction", req, resp)
        return resp

    def SubmitBid(self, req, ctx):
        ok = self.raft.submit_bid(req.auction_id, req.bidder_id, req.amount, sync=True)
        resp = chat_pb2.SubmitBidResponse(
            status="success" if ok else "error",
            message="bid recorded" if ok else "auction closed or not found"
        )
        log_data_usage("SubmitBid", req, resp)
        return resp

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

def serve(host, port, node_id, raft_port, peers):
    # initialize Raft-backed DB
    raft = RaftDB(f"{host}:{raft_port}", peers, f"node{node_id}.db")

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
    chat_pb2_grpc.add_AuthServiceServicer_to_server(AuthService(raft), server)
    chat_pb2_grpc.add_AuctionServiceServicer_to_server(AuctionService(raft), server)

    # bind on all interfaces so IPv4 and IPv6 clients connect
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print(f"Node{node_id} gRPC@[::]:{port}, Raft@{host}:{raft_port}")

    # graceful shutdown on signals
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

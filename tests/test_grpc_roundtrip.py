import time, socket, grpc
from system_main.raft_db import RaftDB
from system_main.ft_server_grpc import start_grpc_server
from system_main import chat_pb2, chat_pb2_grpc


def _free_port(): s=socket.socket(); s.bind(('',0)); p=s.getsockname()[1]; s.close(); return p


def test_end_to_end_grpc(tmp_path):
    db   = RaftDB(f"localhost:{_free_port()}", [], str(tmp_path / "node.db"))
    port = _free_port()
    server = start_grpc_server(db, port)

    ch   = grpc.insecure_channel(f"localhost:{port}")
    grpc.channel_ready_future(ch).result(timeout=5)
    auth = chat_pb2_grpc.AuthServiceStub(ch)
    auc  = chat_pb2_grpc.AuctionServiceStub(ch)

    # user flow
    assert auth.CreateUser(chat_pb2.CreateUserRequest(
        username="amy", hashed_password="pw", display_name="Amy")).status == "success"

    aid = "111"; closes = int(time.time() + 0.3)
    assert auc.StartAuction(chat_pb2.StartAuctionRequest(
        auction_id=aid, duration_seconds=closes, item_name="TEST-ITEM")).status == "success"

    auc.SubmitBid(chat_pb2.SubmitBidRequest(auction_id=aid, bidder_id="amy", amount=30))
    time.sleep(0.35)
    auc.EndAuction(chat_pb2.EndAuctionRequest(auction_id=aid))
    res = auc.GetWinner(chat_pb2.GetWinnerRequest(auction_id=aid))

    assert res.winner_id == "amy" and res.winning_bid == 30 and res.price == 0
    server.stop(grace=None)

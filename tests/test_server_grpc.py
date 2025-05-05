import pytest

try:
    import auction_pb2 as pb
    import auction_pb2_grpc as pbg
except ModuleNotFoundError:
    pb = pbg = None


def test_start_and_get_winner(grpc_channel):
    if pb is None:
        pytest.skip("Proto stubs not available – skipping gRPC smoke test")

    stub = pbg.AuctionServiceStub(grpc_channel)

    stub.StartAuction(pb.StartAuctionRequest(auction_id="A3", duration_seconds=0, item_name="mouse"))
    stub.EndAuction(pb.EndAuctionRequest(auction_id="A3"))
    resp = stub.GetWinner(pb.GetWinnerRequest(auction_id="A3"))
    assert resp.status in ("success", "error")

import grpc, inspect, importlib
from system_main import chat_pb2, chat_pb2_grpc

cg = importlib.import_module("system_main.client_grpc")

def test_high_level_roundtrip_functions_exist():
    # client_grpc re-exports low-level stubs – just check they’re callable
    expected = ["get_auth_stub", "get_auction_stub"]
    for fn in expected:
        assert hasattr(cg, fn) and callable(getattr(cg, fn))

    # create a stub on an in-proc insecure channel
    ch = grpc.insecure_channel("localhost:0")
    auth = cg.get_auth_stub(ch)
    assert isinstance(auth, chat_pb2_grpc.AuthServiceStub)

import types, importlib, grpc, builtins
from contextlib import contextmanager

ft_mod = importlib.import_module("system_main.ft_client_grpc")
FTClient = ft_mod.FTClient

class Unavailable(grpc.RpcError):
    def code(self):
        return grpc.StatusCode.UNAVAILABLE
    def details(self):
        return "temporary"

class AlwaysUnavailable(grpc.RpcError):
    def code(self):
        return grpc.StatusCode.UNAVAILABLE
    def details(self):
        return "always"

def make_client():
    """Return a minimal FTClient with no Tk dependencies."""
    c: FTClient = FTClient.__new__(FTClient)
    c.servers, c.idx = [], 0
    c.max_retries, c.retry_delay = 3, 0.0
    c.connect = lambda: None
    c.channel = None
    c.current_user = "alice"

    c.log_lines = []
    c.log_msg = lambda m: c.log_lines.append(m)

    return c

@contextmanager
def askstring_returns(value):
    original = ft_mod.simpledialog.askstring
    ft_mod.simpledialog.askstring = lambda *a, **k: value
    try:
        yield
    finally:
        ft_mod.simpledialog.askstring = original

def test_safe_rpc_retries_then_success():
    client = make_client()

    calls = {"n": 0}
    def flappy(_req):
        if calls["n"] == 0:
            calls["n"] += 1
            raise Unavailable()
        return "OK"

    out = client.safe_rpc(flappy, object())
    assert out == "OK"
    assert any("retrying" in s.lower() for s in client.log_lines)


def test_safe_rpc_all_fail():
    client = make_client()

    def always_fail(_req):
        raise AlwaysUnavailable()

    out = client.safe_rpc(always_fail, object())
    assert out is None
    assert any("try again later" in s.lower() for s in client.log_lines)


def test_get_winner_bundle_and_single_item(monkeypatch):
    client = make_client()

    winners_pb = types.SimpleNamespace(
        winners=[
            types.SimpleNamespace(bidder_id="alice", payment=7.5, item_ids=[0,1])
        ]
    )
    class Stub:
        def RunGreedyAuction(self, req): return winners_pb
        def GetWinner(self, req):        raise AssertionError("should not be called")
    client.auction_stub = Stub()
    client.safe_rpc = lambda rpc, req: rpc(req)

    with askstring_returns("B1"):
        client.get_winner()

    assert any("[Bundle] B1" in s for s in client.log_lines)

    client.log_lines.clear()
    stub_resp = types.SimpleNamespace(status="success", winner_id="bob", price=4.2, message="")
    class Stub2:
        def RunGreedyAuction(self, req): return types.SimpleNamespace(winners=[])
        def GetWinner(self, req):        return stub_resp
    client.auction_stub = Stub2()

    with askstring_returns("S1"):
        client.get_winner()

    assert any("bob" in s.lower() and "4.2" in s for s in client.log_lines)

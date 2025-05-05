from types import SimpleNamespace
import importlib, itertools

ft = importlib.import_module("system_main.ft_client_grpc")
utils = importlib.import_module("system_main.utils")

class FakeAuthStub:
    def __init__(self): self.calls = []
    def CreateUser(self, req): self.calls.append(("CreateUser", req)); return SimpleNamespace(status="success", message="created")
    def Login     (self, req): self.calls.append(("Login", req));      return SimpleNamespace(status="success", message="logged")

class FakeAuctionStub:
    def __init__(self): self.calls = []
    def StartBundleAuction(self, req):
        self.calls.append(("StartBundleAuction", req))
        return SimpleNamespace(status="success", message="ok")
    def ListBundleAuctions(self, req):
        ai = SimpleNamespace(auction_id="B1", ended=False, time_left=30, item_names=["cpu","gpu"])
        return SimpleNamespace(auctions=[ai])
    def RunGreedyAuction(self, req):
        return SimpleNamespace(winners=[])
    def ListAuctions(self, req):
        return SimpleNamespace(auctions=[])

def make_headless_client():
    c = ft.FTClient.__new__(ft.FTClient)
    c.servers = []; c.idx = 0
    c.max_retries = 3; c.retry_delay = 0.0
    c.log_lines = []
    c.log_msg = lambda m: c.log_lines.append(m)
    c.safe_rpc = lambda rpc, req: rpc(req)
    c.auth_stub    = FakeAuthStub()
    c.auction_stub = FakeAuctionStub()
    c.current_user = None
    c.root = SimpleNamespace(after=lambda delay, fn, *a, **kw: fn(*a, **kw))
    return c

def patch_dialogs(monkeypatch, answers):
    answers_iter = iter(answers)
    monkeypatch.setattr(ft.simpledialog, "askstring",
        lambda *a, **kw: next(answers_iter))
    monkeypatch.setattr(ft.simpledialog, "askinteger",
        lambda *a, **kw: next(answers_iter))

def test_create_login_start_bundle_and_list(monkeypatch):
    client = make_headless_client()

    patch_dialogs(monkeypatch,
        ["alice", "pw123", "alice", "pw123", "B1", "cpu,gpu", 0])

    client.create_user()
    assert ("CreateUser",) == tuple(c[0] for c in client.auth_stub.calls[:1])

    client.login()
    assert ("Login",) == tuple(c[0] for c in client.auth_stub.calls[1:2])
    assert client.current_user == "alice"

    client.start_bundle()
    assert client.auction_stub.calls[-1][0] == "StartBundleAuction"

    client.list_bundle_auctions()
    assert any("Bundle Auctions:" in ln for ln in client.log_lines)
    assert any("B1" in ln and "cpu" in ln and "gpu" in ln for ln in client.log_lines)

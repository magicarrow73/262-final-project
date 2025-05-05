import socket, time, sys, importlib, pytest
from pathlib import Path
from system_main.raft_db import RaftDB

sys.modules.setdefault(
    "chat_pb2",
    importlib.import_module("system_main.chat_pb2")
)

sys.modules.setdefault(
    "chat_pb2_grpc",
    importlib.import_module("system_main.chat_pb2_grpc")
)

sys.modules.setdefault(
    "raft_db",
    importlib.import_module("system_main.raft_db")
)

sys.modules.setdefault(
    "utils",
    importlib.import_module("system_main.utils")
)


def _free_port() -> int:
    s = socket.socket(); s.bind(('', 0)); p = s.getsockname()[1]; s.close(); return p


def _wait_ready(db, timeout=3.0):
    t0 = time.time()
    while not db.isReady() and time.time() - t0 < timeout:
        time.sleep(0.01)
    assert db.isReady()


@pytest.fixture(scope="function")
def solo_db(tmp_path: Path):
    """One-node Raft instance backed by a throw-away SQLite file."""
    db = RaftDB(f"localhost:{_free_port()}", [], str(tmp_path / "node.db"))
    _wait_ready(db)
    yield db
    db.destroy()

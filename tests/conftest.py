import importlib
import os
import random
import sys
import tempfile
import threading
import time
from contextlib import contextmanager

sys.modules.setdefault(
    "auction_pb2",
    importlib.import_module("system_main.auction_pb2")
)

sys.modules.setdefault(
    "auction_pb2_grpc",
    importlib.import_module("system_main.auction_pb2_grpc")
)

sys.modules.setdefault(
    "raft_db",
    importlib.import_module("system_main.raft_db")
)

sys.modules.setdefault(
    "utils",
    importlib.import_module("system_main.utils")
)

import grpc
import pytest

from system_main import raft_db
@pytest.fixture(scope="function")
def local_raftdb():
    db = raft_db.RaftDB(
        self_address=f"localhost:{random.randint(40000, 50000)}",
        other_addresses=[],
        db_path=":memory:")
    yield db
    db.close()

@contextmanager
def _maybe_grpc_server():
    try:
        from system_main import ft_server_grpc  # local import keeps linter happy
    except ImportError:
        yield None, None
        return

    create_func = getattr(ft_server_grpc, "_create_server", None) or \
                  getattr(ft_server_grpc, "create_server", None)
    if create_func is None:
        yield None, None
        return

    raft_port   = random.randint(50060, 50100)
    public_port = random.randint(51000, 51100)

    srv, stop_evt = create_func(
        node_id="testnode",
        raft_port=raft_port,
        grpc_port=public_port,
        peer_raft_addrs=[],
        db_path=":memory:")

    t = threading.Thread(target=srv.start, daemon=True)
    t.start()
    try:
        time.sleep(0.4)
        yield f"localhost:{public_port}", stop_evt
    finally:
        stop_evt.set()
        srv.stop(grace=None)
        t.join(timeout=2)

@pytest.fixture(scope="function")
def grpc_channel():
    with _maybe_grpc_server() as (addr, stop_evt):
        if addr is None:
            pytest.skip("ft_server_grpc lacks a create_server helper – skipping gRPC tests")
        channel = grpc.insecure_channel(addr)
        yield channel
        channel.close()
        stop_evt.set()

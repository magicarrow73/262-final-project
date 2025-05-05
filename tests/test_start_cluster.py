import importlib
import sys
import types

def test_start_server_and_main(monkeypatch):
    events = {"terminate_calls": 0, "kill_calls": 0}

    class DummyProc:
        def __init__(self, cmd):
            self.cmd = cmd

        def terminate(self):
            events["terminate_calls"] += 1

        def kill(self):
            events["kill_calls"] += 1

        def poll(self):
            return None

    monkeypatch.setattr("subprocess.Popen", DummyProc, raising=True)

    call_cnt = {"n": 0}
    def fast_sleep(_):
        if call_cnt["n"] == 0:
            call_cnt["n"] += 1
            return
        if call_cnt["n"] == 1:
            call_cnt["n"] += 1
            raise KeyboardInterrupt
        import time as _t
        _t.sleep(_)

    monkeypatch.setattr("time.sleep", fast_sleep, raising=True)

    argv_orig = sys.argv
    sys.argv = ["start_cluster.py", "--servers", "2", "--base-port", "6000", "--base-raft-port", "6100"]

    start_cluster = importlib.reload(importlib.import_module("system_main.start_cluster"))

    addr = start_cluster.start_server(0, 2, "127.0.0.1", 6000, 6100)
    assert addr == "127.0.0.1:6000"
    proc = start_cluster.running_procs[0]
    assert "--port" in proc.cmd and "6000" in proc.cmd
    assert "--raft-port" in proc.cmd and "6100" in proc.cmd
    assert len(start_cluster.running_procs) == 1

    try:
        start_cluster.main()
    except KeyboardInterrupt:
        pass

    start_cluster.cleanup()
    assert events["terminate_calls"] >= 1 or events["kill_calls"] >= 1

    sys.argv = argv_orig

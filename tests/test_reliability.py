import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import oh_my_hummod.server as server


def test_export_path_never_reuses_existing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "OUTDIR", str(tmp_path))
    first = tmp_path / "same.SOL"
    first.write_text("old experiment", encoding="utf-8")
    chosen = server._unique_export_path("same", ".SOL")
    assert chosen != str(first)
    assert not os.path.exists(chosen)
    second = server._unique_export_path("same", ".SOL")
    assert second != chosen
    fresh_a = server._unique_export_path("fresh", ".SOL")
    fresh_b = server._unique_export_path("fresh", ".SOL")
    assert fresh_a != fresh_b


def test_engines_json_has_no_machine_specific_paths():
    root = os.path.join(os.path.dirname(__file__), "..")
    # The portable upstream layout deliberately does not track this file;
    # users copy the example locally and .gitignore keeps absolute paths out.
    assert not os.path.exists(os.path.join(root, "engines.json"))
    assert "engines.json" in open(os.path.join(root, ".gitignore"), encoding="utf-8").read()


def test_async_go_response_has_truthful_counts(monkeypatch):
    class FakeNode:
        cmd_id = 1

    class FakeTree:
        def walk(self, path):
            return FakeNode()

    class FakeBridge:
        def __init__(self):
            self.commands = 0
        def menu_tree(self): return FakeTree()
        def status_text(self): return ""
        def command(self, _): self.commands += 1

    class FakeProfile:
        stop_cmd_id = 1

    bridge = FakeBridge()
    monkeypatch.setattr(server, "get_bridge", lambda _engine: (bridge, FakeProfile()))
    def wait_slow(*a, **k):
        time.sleep(0.1)
        return {"started": True, "elapsed": 0}
    monkeypatch.setattr(server, "_wait_done", wait_slow)
    out = json.loads(server.hummod_go("10 Sec", times=3, wait=False, engine="lifecycle"))
    assert out["requested_times"] == 3
    assert out["dispatched_times"] == 1
    assert out["started_times"] == 0
    assert out["completed_times"] == 0
    assert out["state"] == "running"
    assert out["job_id"]
    blocked = json.loads(server.hummod_go("10 Sec", times=1, wait=True, engine="lifecycle"))
    assert blocked["ok"] is False
    assert "busy with another operation" in blocked["error"]

    deadline = time.time() + 3
    while time.time() < deadline:
        with server._ASYNC_GO_LOCK:
            job = next(j for j in server._ASYNC_GO_JOBS.values()
                       if j["job_id"] == out["job_id"])
            snapshot = dict(job)
        if snapshot["state"] == "completed":
            break
        time.sleep(0.02)
    assert snapshot["state"] == "completed"
    assert snapshot["dispatched_times"] == 3
    assert snapshot["started_times"] == 3
    assert snapshot["completed_times"] == 3
    assert bridge.commands == 3


def test_async_go_checks_each_run_and_reports_partial_failure(monkeypatch):
    class Node:
        cmd_id = 1
    class Tree:
        def walk(self, _): return Node()
    class Bridge:
        def menu_tree(self): return Tree()
        def status_text(self): return ""
        def command(self, _): pass
    class Profile: stop_cmd_id = 1

    results = iter([
        {"started": True, "signal": "idle", "elapsed": 0},
        {"started": False, "signal": "never-started", "elapsed": 0},
    ])
    monkeypatch.setattr(server, "get_bridge", lambda _engine: (Bridge(), Profile()))
    monkeypatch.setattr(server, "_wait_done", lambda *a, **k: next(results))
    out = json.loads(server.hummod_go("10 Sec", times=3, wait=False, engine="partial-failure"))
    deadline = time.time() + 2
    while time.time() < deadline:
        with server._ASYNC_GO_LOCK:
            job = next(j for j in server._ASYNC_GO_JOBS.values()
                       if j["job_id"] == out["job_id"])
            snapshot = dict(job)
        if snapshot["state"] == "failed":
            break
        time.sleep(0.01)
    assert snapshot["state"] == "failed"
    assert snapshot["dispatched_times"] == 2
    assert snapshot["started_times"] == 1
    assert snapshot["completed_times"] == 1
    assert "run 2" in snapshot["failed"]


def test_async_go_verifies_model_clock_before_completion(monkeypatch):
    class Node:
        cmd_id = 1
    class Tree:
        def walk(self, _): return Node()
    class Bridge:
        def menu_tree(self): return Tree()
        def status_text(self): return ""
        def command(self, _): pass
    class Profile: stop_cmd_id = 1

    clock = iter([100.0, 130.0])
    monkeypatch.setattr(server, "get_bridge", lambda _engine: (Bridge(), Profile()))
    monkeypatch.setattr(server, "_sim_time", lambda *a, **k: next(clock))
    monkeypatch.setattr(server, "_wait_done", lambda *a, **k: {"started": True, "elapsed": 0})
    out = json.loads(server.hummod_go("10 Sec", times=2, wait=False,
                                      verify=True, engine="clock-ok"))
    deadline = time.time() + 2
    while time.time() < deadline:
        with server._ASYNC_GO_LOCK:
            job = next(j for j in server._ASYNC_GO_JOBS.values()
                       if j["job_id"] == out["job_id"])
            snapshot = dict(job)
        if snapshot["state"] == "completed":
            break
        time.sleep(0.01)
    assert snapshot["state"] == "completed"
    assert snapshot["verification"] == "verified"
    assert snapshot["sim_time_before"] == 100.0
    assert snapshot["sim_time_after"] == 130.0
    assert snapshot["sim_minutes_advanced"] == 30.0


def test_restart_conflicts_with_async_go(monkeypatch):
    class Node:
        cmd_id = 1
    class Tree:
        def walk(self, _): return Node()
    class Bridge:
        def menu_tree(self): return Tree()
        def status_text(self): return ""
        def command(self, _): pass
    class Profile: stop_cmd_id = 1

    gate = threading.Event()
    monkeypatch.setattr(server, "get_bridge", lambda _engine: (Bridge(), Profile()))
    def wait_blocked(*a, **k):
        gate.wait(2)
        return {"started": True, "elapsed": 0}
    monkeypatch.setattr(server, "_wait_done", wait_blocked)
    out = json.loads(server.hummod_go("10 Sec", wait=False, engine="restart-conflict"))
    blocked = json.loads(server.hummod_restart(engine="restart-conflict"))
    assert blocked["ok"] is False
    assert "busy with another operation" in blocked["error"]
    gate.set()

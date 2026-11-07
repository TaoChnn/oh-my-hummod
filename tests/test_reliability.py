import json
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import oh_my_hummod.server as server
from oh_my_hummod.bridge import Bridge


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


def test_failed_export_releases_reservation(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "OUTDIR", str(tmp_path))

    class FailingBridge:
        def save_file_dialog(self, *args, **kwargs):
            open(args[1], "w", encoding="utf-8").write("partial")
            raise RuntimeError("dialog failed")

    profile = SimpleNamespace(file={"save_sol": 1}, dialog_edit_ids=())
    with pytest.raises(RuntimeError, match="dialog failed"):
        server._export_snapshot(FailingBridge(), profile, "failed-export")
    with server._EXPORT_LOCK:
        assert not any("failed-export" in p for p in server._RESERVED_EXPORTS)
    assert not list(tmp_path.glob("failed-export*"))


def test_bridge_never_overwrites_existing_export(tmp_path):
    path = tmp_path / "existing.SOL"
    path.write_text("keep me", encoding="utf-8")
    bridge = Bridge.__new__(Bridge)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        bridge.save_file_dialog(1, str(path))
    assert path.read_text(encoding="utf-8") == "keep me"


def test_edit_reports_message_sent_without_model_verification(monkeypatch):
    class Control:
        def __init__(self, cls, ctrl_id, text=""):
            self.cls, self.ctrl_id, self.text, self.hwnd = cls, ctrl_id, text, ctrl_id
    class Bridge:
        def controls(self):
            return [Control("Edit", 10), Control("Button", 11, ">")]
        def set_text(self, *_): pass
        def press(self, *_): pass
    class Profile: pass
    monkeypatch.setattr(server, "get_bridge", lambda _engine: (Bridge(), Profile()))
    monkeypatch.setattr(server, "_navigate", lambda *_: 1)
    out = json.loads(server.hummod_edit("Panel", 0, "42", engine="edit-state"))
    assert out["ok"] is True
    assert out["state"] == "message_sent_unverified"
    assert out["verified"] is False


def test_engines_json_has_no_machine_specific_paths():
    root = os.path.join(os.path.dirname(__file__), "..")
    # A user may create engines.json locally; only the repository must keep it
    # untracked so absolute machine paths cannot enter the PR.
    assert "engines.json" in open(os.path.join(root, ".gitignore"), encoding="utf-8").read()
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "engines.json"],
        cwd=root, capture_output=True, text=True)
    assert tracked.returncode != 0


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


def test_async_go_fails_when_verified_clock_does_not_advance(monkeypatch):
    class Node:
        cmd_id = 1
    class Tree:
        def walk(self, _): return Node()
    class Bridge:
        def menu_tree(self): return Tree()
        def status_text(self): return ""
        def command(self, _): pass
    class Profile: stop_cmd_id = 1

    monkeypatch.setattr(server, "get_bridge", lambda _engine: (Bridge(), Profile()))
    monkeypatch.setattr(server, "_sim_time", lambda *a, **k: 100.0)
    monkeypatch.setattr(server, "_wait_done", lambda *a, **k: {"started": True, "elapsed": 0})
    out = json.loads(server.hummod_go("10 Sec", wait=False,
                                      verify=True, engine="clock-stalled"))
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
    assert snapshot["verification"] == "failed"
    assert "clock did not advance" in snapshot["failed"]


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


def test_engine_aliases_share_operation_lock(monkeypatch):
    monkeypatch.setitem(server._ENGINES, "alias-a", {"dir": r"C:\\same-engine", "profile": None})
    monkeypatch.setitem(server._ENGINES, "alias-b", {"dir": r"C:\\same-engine\\.", "profile": None})
    lock = server._claim_engine_operation("alias-a", "test")
    try:
        with pytest.raises(RuntimeError, match="busy with another operation"):
            server._claim_engine_operation("alias-b", "test")
    finally:
        lock.release()


def test_mutating_tools_reject_alias_conflict(monkeypatch):
    monkeypatch.setitem(server._ENGINES, "alias-a-menu", {"dir": r"C:\\same-engine", "profile": None})
    monkeypatch.setitem(server._ENGINES, "alias-b-menu", {"dir": r"C:\\same-engine\\.", "profile": None})
    lock = server._claim_engine_operation("alias-a-menu", "test")
    try:
        menu = json.loads(server.hummod_menu_command(
            item_path="Go/10 Sec", engine="alias-b-menu"))
        start = json.loads(server.hummod_start(key="alias-b-menu"))
        assert menu["ok"] is False and "busy with another operation" in menu["error"]
        assert start["ok"] is False and "busy with another operation" in start["error"]
    finally:
        lock.release()


def test_go_releases_operation_lock_when_clock_probe_raises(monkeypatch):
    class Node:
        cmd_id = 1
    class Tree:
        def walk(self, _): return Node()
    class Bridge:
        def menu_tree(self): return Tree()
        def status_text(self): return ""
        def command(self, _): pass
    class Profile: stop_cmd_id = 1

    monkeypatch.setattr(server, "get_bridge", lambda _engine: (Bridge(), Profile()))
    monkeypatch.setattr(server, "_sim_time", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("probe")))
    failed = json.loads(server.hummod_go("10 Sec", verify=True, engine="clock-probe-error"))
    assert failed["ok"] is False

    monkeypatch.setattr(server, "_sim_time", lambda *a, **k: 10.0)
    monkeypatch.setattr(server, "_wait_done", lambda *a, **k: {"started": True, "elapsed": 0})
    recovered = json.loads(server.hummod_go("10 Sec", verify=False, engine="clock-probe-error"))
    assert recovered["ok"] is True


def test_async_timeout_releases_operation_lock(monkeypatch):
    class Node:
        cmd_id = 1
    class Tree:
        def walk(self, _): return Node()
    class Bridge:
        def menu_tree(self): return Tree()
        def status_text(self): return ""
        def command(self, _): pass
    class Profile: stop_cmd_id = 1

    monkeypatch.setattr(server, "get_bridge", lambda _engine: (Bridge(), Profile()))
    monkeypatch.setattr(server, "_wait_done", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("timeout")))
    out = json.loads(server.hummod_go("10 Sec", wait=False, engine="timeout-release"))
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
    assert "timeout" in snapshot["failed"]

    monkeypatch.setattr(server, "_wait_done", lambda *a, **k: {"started": True, "elapsed": 0})
    recovered = json.loads(server.hummod_go("10 Sec", wait=True, engine="timeout-release"))
    assert recovered["ok"] is True

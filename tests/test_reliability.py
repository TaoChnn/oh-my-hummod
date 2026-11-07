import json
import os
import sys
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
    with open(os.path.join(os.path.dirname(__file__), "..", "engines.json"), encoding="utf-8") as f:
        assert json.load(f) == {}


def test_async_go_response_has_truthful_counts(monkeypatch):
    class FakeNode:
        cmd_id = 1

    class FakeTree:
        def walk(self, path):
            return FakeNode()

    class FakeBridge:
        def menu_tree(self): return FakeTree()
        def status_text(self): return ""
        def command(self, _): pass

    class FakeProfile:
        stop_cmd_id = 1

    monkeypatch.setattr(server, "get_bridge", lambda _engine: (FakeBridge(), FakeProfile()))
    def wait_slow(*a, **k):
        time.sleep(0.1)
        return {"started": True, "elapsed": 0}
    monkeypatch.setattr(server, "_wait_done", wait_slow)
    out = json.loads(server.hummod_go("10 Sec", times=3, wait=False))
    assert out["requested_times"] == 3
    assert out["started_times"] == 1
    assert out["completed_times"] == 0
    assert out["state"] == "running"
    assert out["job_id"]
    blocked = json.loads(server.hummod_go("10 Sec", times=1, wait=False))
    assert blocked["ok"] is False
    assert "already has async Go job" in blocked["error"]

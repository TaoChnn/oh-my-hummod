# Parameterized engine smoke test: validates a profile against a live engine.
# Usage:
#   python tests/engine_smoke.py --engine DIR --profile NAME [--panel "Clinic/Hemorrhage"]
# Checks: attach, model binding, menu discovery, page navigation, radio toggle
# (verified via SOL), a 1 Min run, and restart settle.
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from oh_my_hummod.bridge import Bridge      # noqa: E402
from oh_my_hummod.profile import Profile    # noqa: E402
from oh_my_hummod.solver import parse_sol   # noqa: E402


def find_panel(tree, needle, path=""):
    """DFS for a menu item whose label contains needle; returns its path."""
    for child in tree.children:
        p = f"{path}/{child.label}" if path else child.label
        if needle.lower() in child.label.lower() and child.cmd_id is not None:
            return p
        if child.children:
            hit = find_panel(child, needle, p)
            if hit:
                return hit
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--panel", default=None, help="panel path to toggle (default: search 'Hemorrhage')")
    ap.add_argument("--out", default=r"C:/path/to/out\engine_smoke")
    args = ap.parse_args()

    p = Profile.load(args.profile)
    b = Bridge(args.engine, exe_name=p.exe_names[0])
    if not b.attach():
        print("engine not running; starting...")
        print("pid:", b.start())
    b.wait_ready(p.bind_marker)
    print(f"attached pid={b.pid} profile={p.name}")

    tree = b.menu_tree()
    top = [(c.label, c.cmd_id) for c in tree.children]
    print("\ntop-level menu:")
    for label, cid in top:
        print(f"  {label!r:20} id={cid}")

    # stop semantics check against profile
    stop_item = tree.find("Stop")
    assert stop_item is not None and stop_item.cmd_id == p.stop_cmd_id, \
        f"Stop mismatch: discovered {stop_item.cmd_id if stop_item else None} vs profile {p.stop_cmd_id}"
    print(f"\nStop cmd_id matches profile: {p.stop_cmd_id}")

    # locate the test panel
    panel = args.panel or (p.panels.get("hemorrhage") if p.panels else None) or find_panel(tree, "Hemorrhage")
    if not panel:
        raise SystemExit("no hemorrhage panel found; pass --panel")
    node = tree.walk(panel)
    print(f"panel {panel!r} -> cmd_id={node.cmd_id}")
    b.navigate(node.cmd_id)
    time.sleep(0.5)

    radios = sorted([c for c in b.controls() if c.is_radio], key=lambda c: c.ctrl_id)
    print(f"radios on page: {[(r.ctrl_id, r.checked) for r in radios]}")
    if len(radios) < 2:
        raise SystemExit("expected >=2 radios on the panel")

    os.makedirs(args.out, exist_ok=True)
    def snap(name, want):
        path = os.path.join(args.out, f"{args.profile}_{name}.SOL")
        b.save_file_dialog(p.file["save_sol"], path, tuple(p.dialog_edit_ids))
        vals = parse_sol(path, want)
        print(f"  {name}: {vals}")
        return vals

    def want(sw="hemorrhage.switch", x="system.x"):
        return {sw, x}

    # On/Off from profile semantics (owner-drawn radios carry no check state);
    # fall back to the first pair convention.
    sem = (p.radio_semantics.get(panel) or {})
    on_i, off_i = sem.get("on"), sem.get("off")
    if on_i is None or off_i is None:
        on_i, off_i = 0, 1
    on_target, off_target = radios[on_i], radios[off_i]
    print(f"\ntoggling ON (radio[{on_i}], ctrl_id={on_target.ctrl_id})...")
    b.press(on_target.hwnd)
    time.sleep(0.6)
    v_on = snap("on", want())

    print("toggling OFF (ctrl_id=%d)..." % off_target.ctrl_id)
    b.press(off_target.hwnd)
    time.sleep(0.6)
    v_off = snap("off", want())

    sw_key = next((k for k in v_on if "switch" in k.lower()), None)
    assert sw_key and v_on[sw_key] == 1.0, f"Switch On failed: {v_on}"
    assert sw_key in v_off and v_off[sw_key] == 0.0, f"Switch Off failed: {v_off}"

    # 1 Min run
    go = tree.walk("Go/1 Min")
    b.command(go.cmd_id)
    wall = b.wait_idle(p.stop_cmd_id, 120)
    print(f"\nGo 1 Min settled in {wall:.1f}s")

    # restart settles
    b.command(tree.walk("Restart").cmd_id)
    b.wait_idle(p.stop_cmd_id, 60)
    print("restart settled")

    print(f"\nENGINE_SMOKE_OK [{p.name}]")


if __name__ == "__main__":
    main()

# Discover a new engine: launch, enumerate menus, infer profile facts.
# Usage: python tests/discover.py --engine DIR [--exe HumMod.EXE] [--top N]
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from oh_my_hummod.bridge import Bridge  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--exe", default="HumMod.EXE")
    ap.add_argument("--already-running", action="store_true")
    args = ap.parse_args()

    b = Bridge(args.engine, exe_name=args.exe)
    if not args.already_running:
        if not b.attach():
            print("starting...", b.start())
    b.wait_ready_timeout = 60
    # generic binding wait: menu count stable across two polls
    deadline = time.time() + 60
    last = -1
    stable = 0
    tree = None
    while time.time() < deadline:
        try:
            tree = b.menu_tree()
        except RuntimeError:
            time.sleep(0.5)
            continue
        if len(tree.children) == last and len(tree.children) > 5:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        last = len(tree.children)
        time.sleep(0.5)
    if tree is None:
        raise SystemExit("no menu tree")

    print(f"pid={b.pid} top_level={len(tree.children)}")
    print("\nTOP-LEVEL:")
    for c in tree.children:
        print(f"  {c.label!r:24} id={c.cmd_id} children={len(c.children)} enabled={c.enabled}")

    # infer Stop
    stop = tree.find("Stop")
    print(f"\nStop -> id={stop.cmd_id if stop else None} enabled={stop.enabled if stop else None}")

    # infer Go durations
    go = tree.find("Go")
    if go:
        print("Go durations:", [(c.label, c.cmd_id) for c in go.children if c.label])
    else:
        print("No 'Go' submenu!")

    # continue / restart markers
    for label in ("Continue", "Restart"):
        item = tree.find(label)
        if item:
            print(f"{label} -> id={item.cmd_id}")

    # search hemorrhage anywhere
    def dfs(node, path=""):
        for c in node.children:
            p = f"{path}/{c.label}" if path else c.label
            if "hemorrhage" in c.label.lower():
                yield p, c.cmd_id
            yield from dfs(c, p)

    hits = list(dfs(tree))
    print("\nHEMORRHAGE panels:", hits or "none found")

    # print full tree paths for panels that are leaves under non-File menus
    print("\nLEAF SAMPLE (first 40 paths):")
    count = 0
    for p, cid in dfs(tree):
        if cid:
            print(f"  {p} -> {cid}")
            count += 1
            if count >= 40:
                break

    print("\nDISCOVER_DONE")


if __name__ == "__main__":
    main()

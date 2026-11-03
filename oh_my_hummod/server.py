"""Oh My HumMod MCP server - profile-aware, discovery-first.

At attach time the bridge enumerates the engine's menu tree, so menu actions
are resolved by *label* ("Restart", "Go/10 Min", "Trauma/Hemorrhage") rather
than hard-coded ids. A version profile supplies only what discovery cannot:
completion semantics, file-dialog control ids and known engine quirks.

Run:  oh-my-hummod  (console entry)  or  python -m oh_my_hummod.server
Env:  HUMMOD_ENGINE_DIR  folder holding the engine EXE + model XML
      HUMMOD_PROFILE     profile name/path (default: auto-detect by EXE name)
      HUMMOD_OUTDIR      where snapshot exports are written (default ./mcp-exports)
"""
from __future__ import annotations

import functools
import json
import os
import re
import sys
import time
from datetime import datetime

from mcp.server.mcpserver import MCPServer

try:
    from .bridge import Bridge
    from .profile import Profile
    from .solver import parse_export, parse_sol, parse_sol_history
except ImportError:  # run as a plain script: python oh_my_hummod/server.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from oh_my_hummod.bridge import Bridge
    from oh_my_hummod.profile import Profile
    from oh_my_hummod.solver import parse_export, parse_sol, parse_sol_history

ENGINE_DIR = os.environ.get("HUMMOD_ENGINE_DIR", os.path.join(os.getcwd(), "engine"))
PROFILE_NAME = os.environ.get("HUMMOD_PROFILE", "")
OUTDIR = os.environ.get("HUMMOD_OUTDIR", os.path.join(os.getcwd(), "mcp-exports"))

server = MCPServer("hummod")


def _load_engines() -> dict[str, str]:
    """Engine registry: key -> engine folder.

    Sources (later wins): env HUMMOD_ENGINES (JSON), engines.json in the repo
    root, and HUMMOD_ENGINE_DIR as the "default" entry.
    """
    engines: dict[str, str] = {}
    for cand in (os.path.join(os.getcwd(), "engines.json"),
                 os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engines.json")):
        if os.path.exists(cand):
            with open(cand, encoding="utf-8") as f:
                engines.update(json.load(f))
            break
    raw = os.environ.get("HUMMOD_ENGINES")
    if raw:
        engines.update(json.loads(raw))
    engines["default"] = ENGINE_DIR
    return engines


_ENGINES = _load_engines()
_bridges: dict[str, tuple[Bridge, Profile]] = {}


def _detect_profile(b: Bridge) -> Profile:
    """Identify the engine build from its live top-level menu (discovery-first)."""
    top = {c.label for c in b.menu_tree().children}
    if "Startup" in top and "Clinic" in top:
        return Profile.load("hummod_1.6.1")
    if "Trauma" in top or "Sizing" in top:
        return Profile.load("hummod_3.0.4")
    if "Continue" in top or "View" in top:
        return Profile.load("qcp_2005")
    raise RuntimeError(f"cannot identify engine build; top-level menu: {sorted(t for t in top if t)}")


def get_bridge(engine: str = "default") -> tuple[Bridge, Profile]:
    if engine in _bridges and _bridges[engine][0].main:
        return _bridges[engine]
    if engine not in _ENGINES:
        raise RuntimeError(f"unknown engine {engine!r}; known: {sorted(_ENGINES)}")
    d = _ENGINES[engine]
    if PROFILE_NAME and engine == "default":
        p = Profile.load(PROFILE_NAME)
        b = Bridge(d, exe_name=p.exe_names[0])
        if not b.attach():
            raise RuntimeError(f"engine {engine!r} not running; call hummod_start first")
        p = p  # explicit override wins even if the menu disagrees
    else:
        b = Bridge(d)  # exe name discovered from the running process
        if not b.attach():
            raise RuntimeError(f"engine {engine!r} not running; call hummod_start first")
        p = _detect_profile(b)
    b.wait_ready(p.bind_marker)
    _bridges[engine] = (b, p)
    return b, p


def safe(fn):
    @functools.wraps(fn)
    def w(*a, **k):
        try:
            return fn(*a, **k)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})
    return w


def _navigate(panel_path: str, engine: str = "default") -> int:
    b, _ = get_bridge(engine)
    tree = b.menu_tree()
    node = tree.walk(panel_path)
    if node.cmd_id is None:
        kids = ", ".join(c.label for c in node.children)
        raise RuntimeError(f"'{panel_path}' is a submenu; pick one of: {kids}")
    b.navigate(node.cmd_id)
    return node.cmd_id


def _wait_done(engine: str = "default", cap: float = 900.0) -> float:
    b, p = get_bridge(engine)
    stop_id = p.stop_cmd_id
    if stop_id is None:  # discovery fallback: find the item labelled Stop
        stop_id = b.menu_tree().find("Stop").cmd_id
    return b.wait_idle(stop_id, cap)


@server.tool()
@safe
def hummod_engines() -> str:
    """List all registered engines (from engines.json) with running state and detected profile."""
    out = {}
    for key, d in _ENGINES.items():
        entry: dict = {"dir": d}
        try:
            b, p = get_bridge(key)
            entry.update({"running": True, "pid": b.pid, "profile": p.name})
        except Exception as e:
            entry.update({"running": False, "error": str(e)})
        out[key] = entry
    return json.dumps({"engines": out, "default": "default"})


@server.tool()
@safe
def hummod_status(engine: str = "default") -> str:
    """Check whether an engine is running; returns profile, pid and engine dir."""
    try:
        b, p = get_bridge(engine)
        return json.dumps({"running": True, "pid": b.pid, "profile": p.name,
                           "engine": engine, "engine_dir": _ENGINES[engine]})
    except Exception as e:
        return json.dumps({"running": False, "error": str(e),
                           "engine": engine, "engine_dir": _ENGINES.get(engine)})


@server.tool()
@safe
def hummod_start(key: str = "default") -> str:
    """Start an engine (hidden window) if not running. Key comes from engines.json."""
    if key not in _ENGINES:
        raise RuntimeError(f"unknown engine {key!r}; known: {sorted(_ENGINES)}")
    if key in _bridges and _bridges[key][0].main:
        return json.dumps({"ok": True, "pid": _bridges[key][0].pid, "note": "already running"})
    b = Bridge(_ENGINES[key])  # exe name discovered from the folder
    pid = b.start()
    p = _detect_profile(b)
    b.wait_ready(p.bind_marker)
    _bridges[key] = (b, p)
    return json.dumps({"ok": True, "pid": pid, "profile": p.name})


@server.tool()
@safe
def hummod_restart(engine: str = "default") -> str:
    """Reset the model to its initial state (label-discovered Restart command). Waits until settled."""
    b, _ = get_bridge(engine)
    cmd = b.menu_tree().walk("Restart").cmd_id
    b.command(cmd)
    _wait_done(60)
    return json.dumps({"ok": True, "action": "restart"})


@server.tool()
@safe
def hummod_inspect(max_chars: int = 20000, engine: str = "default") -> str:
    """Dump the engine's full menu tree (labels + command ids) and the current page's controls as JSON. Use it to find panel paths and control ordinals."""
    b, p = get_bridge(engine)
    menu = b.menu_tree()

    def ser(n):
        d = {"label": n.label, "id": n.cmd_id, "enabled": n.enabled}
        if n.children:
            d["children"] = [ser(c) for c in n.children]
        return d

    controls = [{"cls": c.cls, "id": c.ctrl_id, "text": c.text[:120], "enabled": c.enabled,
                 "radio": c.is_radio, "checkbox": c.is_checkbox, "pos": c.scroll_pos}
                for c in b.controls()]
    return json.dumps({"profile": p.name, "menu": ser(menu), "controls": controls})[:max_chars]


@server.tool()
@safe
def hummod_navigate(panel_path: str, engine: str = "default") -> str:
    """Switch the engine to a panel page by menu path, e.g. 'Trauma/Hemorrhage' or 'Diagnosis/Chart'."""
    mid = _navigate(panel_path, engine)
    return json.dumps({"ok": True, "navigated": panel_path, "menu_id": mid})


@server.tool()
@safe
def hummod_go(duration_label: str, engine: str = "default") -> str:
    """Run the simulation for a Go-menu duration ('1 Min', '10 Min', 'To Next Hour', '1 Day', '30 Days', ...). Waits for completion (Stop grays) and returns wall seconds."""
    b, _ = get_bridge(engine)
    label = duration_label.strip()
    if label.lower().startswith("go/"):
        label = label.split("/", 1)[1]  # tolerate "Go/1 Min" as well as "1 Min"
    node = b.menu_tree().walk("Go/" + label)
    if node.cmd_id is None:
        raise RuntimeError(f"'{label}' is not a runnable Go entry")
    t0 = time.time()
    b.command(node.cmd_id)
    wall = _wait_done(engine)
    return json.dumps({"ok": True, "ran": duration_label,
                       "wall_seconds": round(time.time() - t0, 1),
                       "stop_poll_seconds": round(wall, 1)})


@server.tool()
@safe
def hummod_menu_command(item_path: str, engine: str = "default") -> str:
    """Press any menu entry by path, e.g. 'Restart', 'File/Save Initial Conditions', 'Go/5 Min' (does not wait; use hummod_go for durations)."""
    b, _ = get_bridge(engine)
    node = b.menu_tree().walk(item_path)
    if node.cmd_id is None:
        raise RuntimeError(f"'{item_path}' has no command id (submenu)")
    b.command(node.cmd_id)
    return json.dumps({"ok": True, "pressed": item_path, "menu_id": node.cmd_id})


@server.tool()
@safe
def hummod_radio(panel_path: str, ordinal: int | None = None, expected: int | None = None, value: str | None = None, engine: str = "default") -> str:
    """Click a radio button on a panel page. Prefer value='On'/'Off' (label semantics from the profile); or ordinal among radios sorted by control id (expected = total count guardrail)."""
    b, p = get_bridge(engine)
    _navigate(panel_path, engine)
    radios = sorted([c for c in b.controls() if c.is_radio], key=lambda c: c.ctrl_id)
    if expected is not None and len(radios) != expected:
        raise RuntimeError(f"radio count mismatch: found {len(radios)}, expected {expected}")
    target = None
    if value is not None:
        # native radios are unlabeled and their Off/On captions are owner-drawn
        # (WM_GETTEXT returns empty), so label semantics come from the profile.
        sem = p.radio_semantics.get(panel_path, {})
        want = value.strip().lower()
        ordinal = sem.get(want) if sem else None
        if ordinal is None:
            raise RuntimeError(
                f"label {value!r} not mapped for {panel_path}; "
                f"use ordinal (0..{len(radios)-1}) or add radio_semantics to the profile")
        if ordinal < 0 or ordinal >= len(radios):
            raise RuntimeError(f"ordinal {ordinal} out of range ({len(radios)} radios)")
        target = radios[ordinal]
    elif ordinal is not None:
        if ordinal < 0 or ordinal >= len(radios):
            raise RuntimeError(f"ordinal {ordinal} out of range ({len(radios)} radios)")
        target = radios[ordinal]
    else:
        raise RuntimeError("provide value='On'/'Off' or ordinal")
    b.press(target.hwnd)
    time.sleep(0.15)
    fresh = sorted([c for c in b.controls() if c.is_radio], key=lambda c: c.ctrl_id)
    return json.dumps({"ok": True,
                       "pressed": f"{panel_path} radio[{radios.index(target)}]"
                                  + (f" ({value})" if value else ""),
                       "count": len(radios),
                       "checked": [i for i, c in enumerate(fresh) if c.checked]})


@server.tool()
@safe
def hummod_action(panel_path: str, ordinal: int, expected: int | None = None, engine: str = "default") -> str:
    """Click an action button on a panel page - the canvas triggers drawn as '!'
    buttons (e.g. CPR Draw Blood / Shock Now on Intervention/CPR and
    Trauma/Ventricular Fibrillation). Ordinal among action buttons sorted by
    control id; expected = total count (guardrail). Counts and meanings per
    panel live in profile radio_semantics/action notes."""
    b, _ = get_bridge(engine)
    _navigate(panel_path, engine)
    actions = sorted([c for c in b.controls()
                      if c.cls == "Button" and c.text.strip() == "!"],
                     key=lambda c: c.ctrl_id)
    if expected is not None and len(actions) != expected:
        raise RuntimeError(f"action count mismatch: found {len(actions)}, expected {expected}")
    if ordinal < 0 or ordinal >= len(actions):
        raise RuntimeError(f"ordinal {ordinal} out of range ({len(actions)} action buttons)")
    b.press(actions[ordinal].hwnd)
    time.sleep(0.15)
    return json.dumps({"ok": True, "panel": panel_path,
                       "action_ordinal": ordinal, "count": len(actions)})


@server.tool()
@safe
def hummod_edit(panel_path: str, ordinal: int, value: str, expected: int | None = None, engine: str = "default") -> str:
    """Set an Edit (text) control on a panel page and click its apply button ("> button adjacent by control id). Ords per page from hummod_inspect; expected = total edit count (guardrail)."""
    b, _ = get_bridge(engine)
    _navigate(panel_path, engine)
    edits = sorted([c for c in b.controls() if c.cls == "Edit"], key=lambda c: c.ctrl_id)
    if expected is not None and len(edits) != expected:
        raise RuntimeError(f"edit count mismatch: found {len(edits)}, expected {expected}")
    if ordinal < 0 or ordinal >= len(edits):
        raise RuntimeError(f"ordinal {ordinal} out of range ({len(edits)} edits)")
    e = edits[ordinal]
    apply_btn = None
    for c in b.controls():
        if c.cls == "Button" and c.ctrl_id == e.ctrl_id + 1 and c.text.strip() == ">":
            apply_btn = c
            break
    if apply_btn is None:
        raise RuntimeError("apply button (adjacent '>') not found")
    b.set_text(e.hwnd, value)
    b.press(apply_btn.hwnd)
    time.sleep(0.15)
    return json.dumps({"ok": True, "panel": panel_path, "edit_ordinal": ordinal, "value": value})


@server.tool()
@safe
def hummod_slider(panel_path: str, ordinal: int, pos: int, expected: int, engine: str = "default") -> str:
    """Move a slider on a panel page. WARNING: some engines (3.0.4) accept the thumb move but do not commit the model value - verify via hummod_snapshot and prefer XML parm edits there."""
    b, p = get_bridge(engine)
    _navigate(panel_path, engine)
    sliders = sorted([c for c in b.controls() if c.cls == "ScrollBar"], key=lambda c: c.ctrl_id)
    if len(sliders) != expected:
        raise RuntimeError(f"slider count mismatch: found {len(sliders)}, expected {expected}")
    s = sliders[ordinal]
    b.set_slider(s.hwnd, _parent_of(s.hwnd), pos,
                 commit_endscroll=True)
    note = None
    if p.quirks.get("slider_commits") is False:
        note = p.quirks.get("slider_note")
    return json.dumps({"ok": True, "pos": pos, "verify": "snapshot the model value", "quirk": note})


def _parent_of(hwnd: int) -> int:
    from .bridge import user32
    return user32.GetParent(hwnd)


@server.tool()
@safe
def hummod_snapshot(name: str, vars: list[str] | None = None, engine: str = "default") -> str:
    """Export engine state (HumMod: File > Save Solution .SOL; QCP: File > Save Initial Conditions .ICS) into the MCP output dir; optionally parse named variables. Returns path + values (System.X = sim time on HumMod)."""
    b, p = get_bridge(engine)
    os.makedirs(OUTDIR, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    save_id = p.file.get("save_sol")
    if save_id is not None:
        path = os.path.join(OUTDIR, safe_name + (".SOL" if not safe_name.lower().endswith(".sol") else ""))
        if os.path.exists(path):
            path = os.path.join(OUTDIR, safe_name + "_" + datetime.now().strftime("%H%M%S") + ".SOL")
        b.save_file_dialog(save_id, path, tuple(p.dialog_edit_ids),
                           tail_markers=("</solution>",))
    else:  # QCP family: ICs snapshot instead of SOL
        save_id = p.file.get("save_ics")
        if save_id is None:
            save_id = b.menu_tree().walk("File/Save Initial Conditions").cmd_id
        path = os.path.join(OUTDIR, safe_name + (".ICS" if not safe_name.lower().endswith(".ics") else ""))
        if os.path.exists(path):
            path = os.path.join(OUTDIR, safe_name + "_" + datetime.now().strftime("%H%M%S") + ".ICS")
        b.save_file_dialog(save_id, path, tuple(p.dialog_edit_ids), tail_markers=())
    want = {v.lower() for v in (vars or [])}
    if not want and p.file.get("save_sol") is not None:
        want = {"system.x"}  # default sim-time probe for HumMod SOLs
    vals = parse_export(path, want or None)
    return json.dumps({"ok": True, "path": path, "values": vals})


@server.tool()
@safe
def hummod_get_vars(sol_path: str, names: list[str]) -> str:
    """Read current (last sample) variable values from a .SOL file, e.g. 'BloodVol.Vol'. Returns {values, missing}."""
    want = {n.lower() for n in names}
    vals = parse_sol(sol_path, want)
    return json.dumps({"values": vals, "missing": [n for n in names if n.lower() not in vals]})


@server.tool()
@safe
def hummod_history(sol_path: str, vars: list[str], max_points: int = 500) -> str:
    """Time series from a .SOL export: simulation-time axis (System.X) plus one series per requested variable (e.g. 'BloodVol.Vol'), downsampled to max_points (latest sample always included). Plot-ready."""
    try:
        hist = parse_sol_history(sol_path, set(vars), max_points=max_points)
        return json.dumps({"ok": True, **hist})
    except KeyError as e:
        return json.dumps({"ok": False,
                           "error": f"{e}; note: history requires HumMod .SOL (QCP .ICS has no time series)"})


@server.tool()
@safe
def hummod_dismiss_modal(engine: str = "default") -> str:
    """Close any engine modal dialog (e.g. Tech window) that blocks automation."""
    b, _ = get_bridge(engine)
    return json.dumps({"dismissed": [hex(h) for h in b.dismiss_modals()]})


@server.tool()
@safe
def hummod_profile(engine: str = "default") -> str:
    """Return the active engine profile: file menu ids, stop semantics and quirks."""
    _, p = get_bridge(engine)
    return json.dumps({"name": p.name, "file": p.file, "stop_cmd_id": p.stop_cmd_id,
                       "quirks": p.quirks, "page_ids": p.page_ids})


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()

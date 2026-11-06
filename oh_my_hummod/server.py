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

import ctypes
import functools
import inspect
import json
import os
import re
import sys
import time
import typing
from datetime import datetime

from mcp.server.mcpserver import MCPServer

try:
    from .bridge import Bridge, MenuItem, user32
    from .guide import INSTRUCTIONS, RESOURCES
    from .profile import Profile
    from .solver import parse_export, parse_sol, parse_sol_history
except ImportError:  # run as a plain script: python oh_my_hummod/server.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from oh_my_hummod.bridge import Bridge, MenuItem, user32
    from oh_my_hummod.guide import INSTRUCTIONS, RESOURCES
    from oh_my_hummod.profile import Profile
    from oh_my_hummod.solver import parse_export, parse_sol, parse_sol_history

ENGINE_DIR = os.environ.get("HUMMOD_ENGINE_DIR", os.path.join(os.getcwd(), "engine"))
PROFILE_NAME = os.environ.get("HUMMOD_PROFILE", "")
OUTDIR = os.environ.get("HUMMOD_OUTDIR", os.path.join(os.getcwd(), "mcp-exports"))

# instructions: returned in the MCP handshake (InitializeResult.instructions).
# A client MAY fold it into the system prompt - the wording stays compact and
# points at the resources for the long version.
server = MCPServer("hummod", instructions=INSTRUCTIONS)


# The long-form manual, published as MCP resources. Every client must support
# resources/read, so this is the portable channel - unlike `instructions`,
# which a client is free to ignore.
def _register_resources() -> None:
    def _reader(text: str):
        """Build a zero-argument resource handler (the SDK checks that the
        handler's parameters match the URI template, so the text has to be
        captured, not passed in)."""
        async def _read() -> str:
            return text
        return _read

    for uri, (desc, text) in RESOURCES.items():
        handler = _reader(text)
        handler.__name__ = "read_" + uri.rsplit("/", 1)[-1].replace("-", "_")
        server.resource(uri, name=desc, description=desc,
                        mime_type="text/markdown")(handler)


_register_resources()


def _load_engines() -> dict[str, dict]:
    """Engine registry: key -> {"dir": <folder>, "profile": <profile name or None>}.

    Sources (later wins): env HUMMOD_ENGINES (JSON), engines.json in the repo
    root, and HUMMOD_ENGINE_DIR as the "default" entry.

    An entry may be a plain folder string or an object:
        {"bat": "C:/path"}                       -> profile auto-detected
        {"bat": {"dir": "C:/path",
                 "profile": "hummod_bat"}}       -> profile pinned

    The object form matters for builds that share an EXE (HumMod-BAT and
    Clemmer Salt 3.0.4 ship the *same* HumMod.EXE), where menu-based detection
    cannot tell them apart and would silently pick the wrong profile.
    """
    raw: dict = {}
    for cand in (os.path.join(os.getcwd(), "engines.json"),
                 os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engines.json")):
        if os.path.exists(cand):
            with open(cand, encoding="utf-8") as f:
                raw.update(json.load(f))
            break
    env = os.environ.get("HUMMOD_ENGINES")
    if env:
        raw.update(json.loads(env))
    raw["default"] = ENGINE_DIR

    engines: dict[str, dict] = {}
    for key, val in raw.items():
        if isinstance(val, dict):
            engines[key] = {"dir": val.get("dir", ""), "profile": val.get("profile") or None}
        else:
            engines[key] = {"dir": val, "profile": None}
    return engines


_ENGINES = _load_engines()
_bridges: dict[str, tuple[Bridge, Profile]] = {}


def _profile_from_engine_dir(engine_dir: str) -> Profile | None:
    """Identify the engine build from its VERSION file (exact, race-free).

    Standalone HumMod folders ship a VERSION file (e.g. VERSION="1.6.1").
    When a builtin profile named hummod_<version> exists, it wins: the live
    top-level menu is unreliable during process startup - on HumMod 1.6.1 the
    menu tree populates progressively and the detection loop can observe a
    partial menu, misclassifying the build (observed: 1.6.1 detected as 3.0.4,
    after which the wrong profile stayed cached for the process lifetime).
    """
    try:
        with open(os.path.join(engine_dir, "VERSION"), encoding="utf-8", errors="replace") as f:
            raw = f.read().strip()
        # VERSION file may be a bare version ("1.6.1") or KEY=VALUE (VERSION="1.6.1")
        version = raw.split("=", 1)[1] if "=" in raw else raw
        version = version.strip().strip('"').strip("'").strip()
        if version:
            return Profile.load(f"hummod_{version}")
    except (OSError, ValueError, TypeError):
        pass  # unreadable/unknown version -> fall back to menu detection
    return None


def _detect_profile(b: Bridge, pinned: str | None = None) -> Profile:
    """Identify the engine build: pinned name first, then VERSION file, then the live top-level menu."""
    if pinned:
        return Profile.load(pinned)
    p = _profile_from_engine_dir(b.engine_dir)
    if p is not None:
        return p
    top = {c.label for c in b.menu_tree().children}
    if "Startup" in top and "Clinic" in top:
        return Profile.load("hummod_1.6.1")
    if "Trauma" in top or "Sizing" in top:
        return Profile.load("hummod_3.0.4")
    if "Continue" in top or "View" in top:
        return Profile.load("qcp_2005")
    raise RuntimeError(f"cannot identify engine build; top-level menu: {sorted(t for t in top if t)}")


def get_bridge(engine: str = "default") -> tuple[Bridge, Profile]:
    if engine in _bridges:
        b0, p0 = _bridges[engine]
        # the engine process may have been restarted (or crashed) since the
        # bridge was cached - a dead window handle must not be reused
        if b0.main and user32.IsWindow(b0.main):
            return b0, p0
        _bridges.pop(engine, None)
    if engine not in _ENGINES:
        raise RuntimeError(f"unknown engine {engine!r}; known: {sorted(_ENGINES)}")
    d = _ENGINES[engine]["dir"]
    pinned = _ENGINES[engine]["profile"]
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
        p = _detect_profile(b, pinned)
    b.wait_ready(p.bind_marker)
    _bridges[engine] = (b, p)
    return b, p


def _coerce_scalar(value, want: str):
    """Coerce a JSON scalar that a client may have marshalled as a string."""
    if value is None:
        return None
    if want == "int":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        text = str(value).strip()
        try:
            return int(text)
        except ValueError:
            return int(float(text))   # "100.0" -> 100
    if want == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off", ""):
            return False
        raise ValueError(f"expected a boolean, got {value!r}")
    return value


def _coerce_list(value):
    """Accept the several shapes clients use for "a list of names".

    ZCode's MCP client marshals a JSON array as {"item": [...]} (a one-element
    array arrives as {"item": "x"}); other clients send a bare string for a
    single name. All of them mean the same thing here.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        if "item" in value:
            return _coerce_list(value["item"])
        if len(value) == 1:
            return _coerce_list(next(iter(value.values())))
        raise ValueError(f"expected a list of names, got {value!r}")
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    raise ValueError(f"expected a list of names, got {value!r}")


def _coerce_arguments(fn, args, kwargs):
    """Coerce the declared parameters to the type the tool documents.

    The advertised JSON schema is what an MCP client validates against, so a
    tool that declares a plain `int` is rejected by clients that marshal
    numbers as strings, and a tool that declares a plain `list[str]` is
    rejected by clients that wrap arrays in {"item": [...]}. Declaring those
    parameters as unions and coercing them here keeps every client working.
    """
    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        return args, kwargs
    try:
        bound = inspect.signature(fn).bind(*args, **kwargs)
    except TypeError:
        return args, kwargs
    for name, value in list(bound.arguments.items()):
        if value is None:
            continue
        ann = hints.get(name)
        if ann is None:
            continue
        members = {t for t in getattr(ann, "__args__", (ann,)) if t is not type(None)}
        # a generic alias (list[str]) is not the bare `list` - compare origins
        origins = {typing.get_origin(t) or t for t in members}
        if int in members and str in members:
            bound.arguments[name] = _coerce_scalar(value, "int")
        elif bool in members and str in members:
            bound.arguments[name] = _coerce_scalar(value, "bool")
        elif list in origins and dict in origins:
            bound.arguments[name] = _coerce_list(value)
    return bound.args, bound.kwargs


def safe(fn):
    @functools.wraps(fn)
    def w(*a, **k):
        try:
            a, k = _coerce_arguments(fn, a, k)
            return fn(*a, **k)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})
    return w


def _resolve_panel(tree, path: str, profile: Profile):
    """Resolve a panel path, applying profile aliases and fuzzy fallback.

    Build-to-build differences (e.g. 'Respiration/Thorax' vs 'Physiology/Lungs/
    Thorax') are handled by profile.menu_aliases; a near-miss path returns the
    closest candidates instead of a bare KeyError.
    """
    # 1) exact
    try:
        return tree.walk(path), path
    except KeyError:
        pass
    # 2) profile alias: canonical -> build-specific
    alias = profile.menu_aliases.get(path)
    if alias:
        try:
            return tree.walk(alias), alias
        except KeyError:
            pass
    # 3) alias by leaf label: any path whose last segment matches
    leaf = path.rsplit("/", 1)[-1].strip().lower()
    candidates = []

    def dfs(node, prefix=""):
        for c in node.children:
            p = f"{prefix}/{c.label}" if prefix else c.label
            if c.cmd_id is not None:
                if c.label.strip().lower() == leaf:
                    candidates.append((p, c))
                elif leaf and leaf in c.label.strip().lower():
                    candidates.append((p, c))
            if c.children:
                dfs(c, p)

    dfs(tree)
    if candidates:
        # prefer the shortest path (least ambiguity)
        candidates.sort(key=lambda pc: len(pc[0]))
        # Return the node itself: the accumulated path is not necessarily
        # walk()-able (a menu item under an unlabelled submenu would need an
        # empty path segment, which walk() filters out).
        return candidates[0][1], candidates[0][0]
    # 4) profile page_ids: curated panel name -> command id (engines whose
    #    pages are owner-drawn buttons have no usable menu label at all)
    pid = profile.page_ids.get(path)
    if pid is not None:
        return MenuItem(label=path, cmd_id=int(pid), position=-1, enabled=True), path
    raise KeyError(f"menu path not found: {path!r}")


def _navigate(panel_path: str, engine: str = "default") -> int:
    b, p = get_bridge(engine)
    tree = b.menu_tree()
    try:
        node, resolved = _resolve_panel(tree, panel_path, p)
    except KeyError as e:
        # list siblings that share the first segment, to help the caller correct
        first = panel_path.split("/")[0].strip().lower()
        near = []
        for c in tree.children:
            if first and (first in c.label.strip().lower()):
                for k in c.children:
                    near.append(f"{c.label}/{k.label}")
        hint = ("; did you mean one of: " + ", ".join(near[:12])) if near else ""
        raise RuntimeError(f"{e}{hint}")
    if node.cmd_id is None:
        kids = ", ".join(c.label for c in node.children)
        raise RuntimeError(f"'{resolved}' is a submenu; pick one of: {kids}")
    b.navigate(node.cmd_id)
    return node.cmd_id


def _wait_done(engine: str = "default", cap: float = 900.0,
               before_status: str | None = None) -> dict:
    b, p = get_bridge(engine)
    stop_id = p.stop_cmd_id
    if stop_id is None:  # discovery fallback: find the item labelled Stop
        stop_id = b.menu_tree().find("Stop").cmd_id
    return b.wait_idle(stop_id, cap, before_status=before_status)


@server.tool()
@safe
def hummod_engines() -> str:
    """List all registered engines (from engines.json) with running state and detected profile."""
    out = {}
    for key, d in _ENGINES.items():
        entry: dict = {"dir": d["dir"]}
        if d["profile"]:
            entry["profile_pinned"] = d["profile"]
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
                           "engine": engine, "engine_dir": _ENGINES[engine]["dir"]})
    except Exception as e:
        return json.dumps({"running": False, "error": str(e),
                           "engine": engine,
                           "engine_dir": (_ENGINES.get(engine) or {}).get("dir")})


@server.tool()
@safe
def hummod_start(key: str = "default", hidden: bool | str = True,
                 engine: str | None = None) -> str:
    """Start an engine if not running. Key comes from engines.json.

    hidden=True (default) starts with a hidden window, which suits HumMod 3.x.
    QCP 2005 exits within seconds when started hidden (observed repeatedly),
    so start it with hidden=False; the MCP tools attach to the visible window
    just as well.

    `engine` is accepted as an alias for `key` (every other tool in this
    server names the argument `engine`, so callers reasonably pass that).
    Without the alias a mistyped/ignored argument silently started the
    DEFAULT engine instead of the requested one - the wrong model then
    answers every later call (observed with QCP: engine="qcp" launched
    C:/path/to/engine\\HumMod.EXE).
    """
    if engine:
        if key not in ("default", engine):
            raise RuntimeError(
                f"conflicting engine keys: key={key!r} engine={engine!r}; pass only one")
        key = engine
    if key not in _ENGINES:
        raise RuntimeError(f"unknown engine {key!r}; known: {sorted(_ENGINES)}")
    if key in _bridges and _bridges[key][0].main and user32.IsWindow(_bridges[key][0].main):
        return json.dumps({"ok": True, "pid": _bridges[key][0].pid, "note": "already running"})
    b = Bridge(_ENGINES[key]["dir"])  # exe name discovered from the folder
    pid = b.start(hidden=hidden)
    # HUMMOD_PROFILE is the *default* engine's profile override (it only ever
    # described the HUMMOD_ENGINE_DIR build). Applying it to NAMED engine keys
    # made hummod_start return a wrong profile (and skip menu-based detection)
    # whenever a named engine happened to be a different build - which is also
    # how a wrong-dir start used to go unnoticed. Mirror get_bridge: the
    # override wins only for the default key.
    if PROFILE_NAME and key == "default":  # explicit env profile avoids _detect_profile's menu race
        p = Profile.load(PROFILE_NAME)
    else:
        p = None
        for _ in range(30):  # page rows appear only after "Starting Model ... Binding ..."
            try:
                p = _detect_profile(b, _ENGINES[key]["profile"])
                break
            except RuntimeError:
                time.sleep(1.0)
        if p is None:
            raise RuntimeError("engine started but its build menu never appeared")
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
    _wait_done(engine, 60)
    return json.dumps({"ok": True, "action": "restart"})


@server.tool()
@safe
def hummod_restart_engine(engine: str = "default") -> str:
    """Relaunch the engine PROCESS so edited model XML (Structure/*.DES) takes effect.

    hummod_restart only resets the in-memory model state - it does NOT re-read
    the model files, so a <parm> injected into the XML stays invisible until the
    process is restarted. This tool closes the engine and starts a fresh copy of
    the same engine directory, then waits for the model to bind again.

    Only the named engine is touched; other registered engines keep running.
    """
    if engine not in _ENGINES:
        raise RuntimeError(f"unknown engine {engine!r}; known: {sorted(_ENGINES)}")
    d = _ENGINES[engine]["dir"]
    pinned = _ENGINES[engine]["profile"]
    exe_name = None
    old = _bridges.get(engine)
    if old is not None:
        exe_name = old[0].exe_name
    closed = False
    if old is not None and old[0].main:
        closed = old[0].terminate()
    else:
        probe = Bridge(d, exe_name=exe_name)
        if probe.attach():
            exe_name = probe.exe_name
            closed = probe.terminate()
    _bridges.pop(engine, None)
    b = Bridge(d, exe_name=exe_name)
    pid = b.start()
    if PROFILE_NAME and engine == "default":
        p = Profile.load(PROFILE_NAME)
    else:
        p = None
        for _ in range(30):
            try:
                p = _detect_profile(b, pinned)
                break
            except RuntimeError:
                time.sleep(1.0)
        if p is None:
            raise RuntimeError("engine restarted but its build menu never appeared")
    b.wait_ready(p.bind_marker)
    _bridges[engine] = (b, p)
    return json.dumps({"ok": True, "action": "restart_engine", "pid": pid,
                       "profile": p.name, "old_process_closed": closed,
                       "engine_dir": d})


@server.tool()
@safe
def hummod_inspect(max_chars: int | str = 20000, engine: str = "default",
                   mode: str = "both", panel_path: str | None = None) -> str:
    """Inspect the engine: mode='menu' (menu tree with command ids and full paths),
    mode='controls' (current page's widgets only), mode='both' (default).
    panel_path optionally navigates first and returns that page's widgets.
    The menu tree alone can be long - prefer mode='controls' when you only need widgets."""
    b, p = get_bridge(engine)
    if panel_path:
        _navigate(panel_path, engine)

    def ser(n, path=""):
        full = f"{path}/{n.label}" if path and n.label else (path or n.label)
        d = {"label": n.label, "path": full, "id": n.cmd_id, "enabled": n.enabled}
        if n.children:
            d["children"] = [ser(c, full) for c in n.children]
        return d

    out: dict = {"profile": p.name}
    if mode in ("menu", "both"):
        out["menu"] = ser(b.menu_tree())
    if mode in ("controls", "both"):
        controls = [{"cls": c.cls, "id": c.ctrl_id, "text": c.text[:120],
                     "enabled": c.enabled, "visible": c.visible,
                     "shown": c.own_visible,
                     "radio": c.is_radio, "checkbox": c.is_checkbox,
                     "action": c.cls == "Button" and c.text.strip() == "!",
                     "button": c.cls == "Button",
                     "checked": c.checked if c.check_state_readable else None,
                     "check_readable": c.check_state_readable,
                     "button_type": c.button_type if c.cls == "Button" else None,
                     "style": hex(c.style) if c.cls == "Button" else None,
                     "pos": c.scroll_pos, "min": c.scroll_min, "max": c.scroll_max,
                     "rect": [c.left, c.top, c.right, c.bottom]}
                    for c in b.controls()]
        out["controls"] = controls
        out["control_summary"] = {
            "radios": sum(1 for c in controls if c["radio"]),
            "actions": sum(1 for c in controls if c["action"]),
            "edits": sum(1 for c in controls if c["cls"] == "Edit"),
            "sliders": sum(1 for c in controls if c["cls"] == "ScrollBar"),
            "buttons": sum(1 for c in controls if c["button"]),
            "checked": [i for i, c in enumerate(controls) if c["checked"]],
        }
        out["button_captions"] = [c["text"] for c in controls
                                   if c["button"] and c["text"].strip()
                                   and c["text"].strip() != "!"]
        out["visibility_note"] = (
            "'visible' is IsWindowVisible, which is false for every control when "
            "the engine window itself is hidden (the MCP server starts it with "
            "SW_HIDE). 'shown' is the control's own WS_VISIBLE bit and says "
            "whether the widget is part of the page.")
    # Keep the response valid JSON: trim the control list instead of cutting
    # the serialized string (a cut string is unparsable for the caller).
    txt = json.dumps(out, ensure_ascii=False)
    if len(txt) > max_chars:
        trimmed = dict(out)
        ctrl = out.get("controls", [])
        keep = max(0, len(ctrl) // 2)
        while keep > 0:
            trimmed["controls"] = ctrl[:keep]
            candidate = json.dumps(trimmed, ensure_ascii=False)
            if len(candidate) <= max_chars:
                break
            keep //= 2
        trimmed["controls"] = ctrl[:keep]
        trimmed["truncated"] = {
            "controls_total": len(ctrl), "controls_shown": keep,
            "hint": "raise max_chars, or narrow the page, to see the rest"}
        txt = json.dumps(trimmed, ensure_ascii=False)
    return txt


@server.tool()
@safe
def hummod_view_group(group: str, want: bool | str = True, engine: str = "default") -> str:
    """Show/hide a View-menu toolbar group (e.g. 'View/Basic Physiology').

    QCP keeps its pages on canvas-drawn toolbar buttons; a group only exists
    in the menu tree while it is displayed, so its page commands appear and
    disappear with it. Toggling is reported by the change in menu size.

    The entries the group added/removed are returned as `pages_added` /
    `pages_removed` (cmd_id + label): a group whose pages are not in the
    menu tree yet cannot be reached otherwise, and dumping the whole menu
    tree just to learn those ids is expensive.
    """
    b, _ = get_bridge(engine)

    def entries():
        """(cmd_id, label) of every menu entry, in tree order."""
        out = []

        def w(node):
            for c in node.children:
                out.append((c.cmd_id, c.label))
                w(c)
        w(b.menu_tree())
        return out

    node = b.menu_tree().walk(group)
    before = entries()
    b.command(node.cmd_id)
    time.sleep(0.6)
    after = entries()
    note = None
    if (len(after) > len(before)) != want:
        # The toggle moved the group AWAY from the wanted state, i.e. it was
        # already in that state: toggle back and the wanted state is restored.
        b.command(node.cmd_id)
        time.sleep(0.6)
        after = entries()
        note = "toggled twice to reach the wanted state"
    before_set, after_set = set(before), set(after)
    return json.dumps({
        "ok": True, "group": group, "state": "on" if want else "off",
        "menu_entries": len(after),
        "pages_added": [{"cmd_id": i, "label": l} for i, l in after if (i, l) not in before_set],
        "pages_removed": [{"cmd_id": i, "label": l} for i, l in before if (i, l) not in after_set],
        **({"note": note} if note else {}),
    })


@server.tool()
@safe
def hummod_navigate(panel_path: str | None = None, engine: str = "default",
                    menu_id: int | str | None = None) -> str:
    """Switch the engine to a panel page by menu path, e.g. 'Trauma/Hemorrhage' or 'Diagnosis/Chart'.
    Pass menu_id=<cmd id> for pages whose menu label is empty (QCP's owner-drawn toolbar buttons)."""
    if menu_id is not None:
        b, _ = get_bridge(engine)
        b.navigate(int(menu_id))
        return json.dumps({"ok": True, "navigated": f"menu_id={menu_id}", "menu_id": int(menu_id)})
    if not panel_path:
        raise RuntimeError("provide panel_path or menu_id")
    mid = _navigate(panel_path, engine)
    return json.dumps({"ok": True, "navigated": panel_path, "menu_id": mid})


@server.tool()
@safe
def hummod_stop_state(engine: str = "default") -> str:
    """Report whether the Stop menu item is enabled (True = simulation currently running)."""
    b, p = get_bridge(engine)
    stop_id = p.stop_cmd_id
    if stop_id is None:
        stop_id = b.menu_tree().find("Stop").cmd_id
    return json.dumps({"stop_enabled": bool(b.menu_item_enabled(stop_id))})


def _csv_list(s: str | None) -> list[str]:
    """Split a comma-separated string into a list of non-empty items."""
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def _bool_str(s: str | None) -> bool | None:
    """Parse a boolean given as a string ('1'/'true'/'yes'/'on' vs '0'/'false'/'no'/'off')."""
    if s is None or s == "":
        return None
    return s.strip().lower() in ("1", "true", "yes", "on")


@server.tool()
@safe
def hummod_go(duration_label: str, times: int | str = 1, verify: bool | str = False,
              wait: bool | str = True, engine: str = "default",
              times_str: str = "", verify_str: str = "") -> str:
    """Run the simulation for a Go-menu duration ('1 Min', '10 Min', 'To Next Hour', '1 Day', '30 Days', ...). Waits for completion and returns wall seconds.

    times repeats the same Go step (the Go menu has no '30 Sec' entry, so 30 s = times=3 of '10 Sec').
    verify=True additionally reads the model clock (System.X) before and after, which
    proves the run really advanced the simulation.

    wait=False returns as soon as the run has been started instead of waiting for
    it to finish. Use it for runs that take longer than the MCP client's request
    timeout (30 s by default): a 3-week step needs several minutes, and a
    blocking call is aborted by the client while the engine keeps simulating.
    Poll with hummod_stop_state (stop_enabled=false means finished) and
    hummod_busy, then read the result with hummod_snapshot.

    Completion is detected from the engine's UI thread (the model solves on it) plus
    the Stop menu item - on HumMod 3.0.4 the Stop item stays gray even while the
    model is running, so it alone cannot tell 'finished' from 'still running'.

    times_str / verify_str are string-typed escape hatches for MCP clients that
    cannot express a JSON number or boolean (some clients quote every scalar):
    times_str='3' means times=3, verify_str='true' means verify=True. They take
    precedence over the typed arguments when given.
    """
    b, p = get_bridge(engine)
    label = duration_label.strip()
    if label.lower().startswith("go/"):
        label = label.split("/", 1)[1]  # tolerate "Go/1 Min" as well as "1 Min"
    node = b.menu_tree().walk("Go/" + label)
    if node.cmd_id is None:
        raise RuntimeError(f"'{label}' is not a runnable Go entry")
    if times_str:
        try:
            times = int(str(times_str).strip())
        except ValueError:
            raise RuntimeError(f"times_str={times_str!r} is not an integer")
    if verify_str:
        v = _bool_str(verify_str)
        if v is None:
            raise RuntimeError(f"verify_str={verify_str!r} is not a boolean")
        verify = v
    times = max(1, int(times))
    t_before = _sim_time(b, p) if verify else None
    t0 = time.time()
    started_all = True
    signals = []
    polls = 0.0
    for i in range(times):
        before_status = b.status_text()
        b.command(node.cmd_id)
        if not wait:
            out = {"ok": True, "ran": duration_label, "times": times,
                   "waited": False,
                   "note": ("run started; poll hummod_stop_state / hummod_busy until "
                            "the engine is idle, then hummod_snapshot for the state"),
                   "wall_seconds": round(time.time() - t0, 1)}
            if verify:
                out["sim_time_before"] = t_before
            return json.dumps(out)
        res = _wait_done(engine, before_status=before_status)
        polls += res.get("elapsed", 0.0)
        signals.append(res.get("signal", "?"))
        started_all = started_all and res.get("started", False)
    out = {"ok": True, "ran": duration_label, "times": times,
           "wall_seconds": round(time.time() - t0, 1),
           "stop_poll_seconds": round(polls, 1),
           "started": started_all,
           "signal": signals[0] if len(set(signals)) == 1 else signals}
    if not started_all:
        out["note"] = ("the engine never showed as busy - the run may have completed "
                       "before the first probe; use verify=True to confirm the "
                       "simulation clock moved")
    if verify:
        t_after = _sim_time(b, p)
        out["sim_time_before"] = t_before
        out["sim_time_after"] = t_after
        out["sim_minutes_advanced"] = (None if (t_before is None or t_after is None)
                                       else round(t_after - t_before, 4))
    return json.dumps(out)


@server.tool()
@safe
def hummod_busy(engine: str = "default") -> str:
    """Report whether the engine is still working.

    Combines the signals that matter: the UI thread's responsiveness (the model
    solves on the UI thread, so the window stops answering while busy), the Stop
    menu item and the status-bar text. Useful to confirm that a run has really
    finished before exporting a snapshot."""
    b, p = get_bridge(engine)
    stop_id = p.stop_cmd_id
    if stop_id is None:
        stop_id = b.menu_tree().find("Stop").cmd_id
    responsive = b.ui_responsive(500)
    stop_enabled = bool(b.menu_item_enabled(stop_id))
    text = b.status_text() or ""
    # 3.0.4 field trial: the UI thread stays responsive while the model runs,
    # so "not responsive" alone misses whole runs - weight the other signals.
    solving = "solving" in text.lower() and "done" not in text.lower()
    return json.dumps({"ok": True,
                       "busy": (not responsive) or solving or stop_enabled,
                       "ui_responsive": responsive,
                       "stop_enabled": stop_enabled,
                       "status_text": text})


def _sim_time(b: Bridge, p: Profile) -> float | None:
    """Read the model clock (System.X, in minutes) from the engine.

    HumMod exports it as "System.X"; the QCP family saves ICs where the clock
    variable is plain "X" - accept both spellings or the clock read returns
    None for every QCP snapshot.
    """
    try:
        path = _export_snapshot(b, p, "_simtime_" + datetime.now().strftime("%H%M%S%f"))
        vals = parse_export(path, {"system.x", "x"})
        for k, v in sorted(vals.items(), key=lambda kv: kv[0].lower() != "system.x"):
            if k.lower() in ("system.x", "x"):
                return float(v)
    except Exception:
        return None
    return None


@server.tool()
@safe
def hummod_button(panel_path: str, caption: str, engine: str = "default") -> str:
    """Click a *labelled* panel button by its caption, e.g. 'Neurological Signs' on Diagnosis/Evaluation.

    hummod_action only covers the canvas-drawn '!' triggers; plain buttons with a
    caption (page sub-navigation, graph tabs) had no way to be pressed. The caption
    is matched case-insensitively, first exactly, then as a substring."""
    b, _ = get_bridge(engine)
    _navigate(panel_path, engine)
    want = caption.strip().lower()
    buttons = [c for c in b.controls() if c.cls == "Button" and c.text.strip()]
    exact = [c for c in buttons if c.text.strip().lower() == want]
    partial = [c for c in buttons if want in c.text.strip().lower()]
    hits = exact or partial
    if not hits:
        avail = sorted({c.text.strip() for c in buttons})
        raise RuntimeError(f"no button captioned {caption!r} on {panel_path}; available: {avail[:20]}")
    if len(hits) > 1 and not exact:
        raise RuntimeError(f"caption {caption!r} is ambiguous ({len(hits)} matches); use a longer caption")
    target = hits[0]
    b.press(target.hwnd)
    time.sleep(0.3)
    return json.dumps({"ok": True, "panel": panel_path, "caption": target.text.strip(),
                       "ctrl_id": target.ctrl_id, "matches": len(hits)})


@server.tool()
@safe
def hummod_menu_command(item_path: str | None = None, engine: str = "default",
                        menu_id: int | str | None = None) -> str:
    """Press any menu entry by path, e.g. 'Restart', 'File/Save Initial Conditions', 'Go/5 Min' (does not wait; use hummod_go for durations).
    Pass menu_id=<cmd id> instead of item_path for entries whose label is empty (owner-drawn toolbar/popup buttons)."""
    b, _ = get_bridge(engine)
    if menu_id is not None:
        b.command(int(menu_id))
        return json.dumps({"ok": True, "pressed": f"menu_id={menu_id}", "menu_id": int(menu_id)})
    if not item_path:
        raise RuntimeError("provide item_path or menu_id")
    b_, p_ = get_bridge(engine)
    # resolve like a panel path so that owner-drawn / nested menu entries
    # (QCP's canvas toolbar buttons) can be pressed by their label
    node, resolved = _resolve_panel(b_.menu_tree(), item_path, p_)
    if node.cmd_id is None:
        raise RuntimeError(f"'{item_path}' has no command id (submenu)")
    b.command(node.cmd_id)
    return json.dumps({"ok": True, "pressed": item_path, "resolved": resolved,
                       "menu_id": node.cmd_id})


@server.tool()
@safe
def hummod_shot(name: str, engine: str = "default", restore: bool | str = True) -> str:
    """Screenshot the engine window to a PNG in the MCP output dir.

    Essential for canvas-drawn engines (QCP) where the panels have no widget
    tree - the picture is the only view of the current page. Returns the path
    and the image size; coordinates in the picture are window-relative and can
    be passed straight back to hummod_click / hummod_drag."""
    b, _ = get_bridge(engine)
    os.makedirs(OUTDIR, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    path = os.path.join(OUTDIR, safe_name + (".png" if not safe_name.lower().endswith(".png") else ""))
    if os.path.exists(path):
        path = os.path.join(OUTDIR, safe_name + "_" + datetime.now().strftime("%H%M%S") + ".png")
    if restore:
        b.restore_window()
    w, h = b.capture_png(path)
    return json.dumps({"ok": True, "path": path, "size": [w, h],
                       "origin": "window-relative (x right, y down)",
                       "window_rect": list(b.window_rect()),
                       "client_origin": list(b.client_origin())})


@server.tool()
@safe
def hummod_dialogs(engine: str = "default") -> str:
    """List the engine's visible modal dialogs (#32770) and their child controls.

    Use it to find the file-save / Find / parameter dialogs that QCP-style
    engines open, and to see their Edit + OK controls."""
    b, _ = get_bridge(engine)
    out = []
    for d in b._visible_dialogs():
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(d, buf, 256)
        kids = b._dialog_children(d)
        out.append({"hwnd": hex(d), "title": buf.value,
                    "controls": [{"cls": k.cls, "id": k.ctrl_id, "text": k.text[:80],
                                  "visible": k.visible, "enabled": k.enabled,
                                  "rect": [k.left, k.top, k.right, k.bottom]} for k in kids]})
    return json.dumps({"ok": True, "dialogs": out})


@server.tool()
@safe
def hummod_popup(engine: str = "default") -> str:
    """List visible popup menus (#32768) with their items and command ids.

    QCP opens its panel pickers (Blood / Hormones / Kidney ...) as popup menus
    that are not part of the menu bar; while one is open this returns its
    entries so the caller can pick one by id."""
    b, _ = get_bridge(engine)
    return json.dumps({"ok": True, "popups": b.popup_menus()})


@server.tool()
@safe
def hummod_listbox(dialog_title: str, control_id: int | str, engine: str = "default",
                   select: int | str | None = None, select_text: str | None = None) -> str:
    """Read the items and the current selection of a list box inside an open dialog.

    select / select_text pick an item (by index or by substring) and notify the
    dialog, which is how QCP's 'Find Variable's Panel' populates the Item and
    Panel lists from the Category list."""
    b, _ = get_bridge(engine)
    dlg = b.dialog_with_text(dialog_title) or b.dialog_by_title(dialog_title)
    if dlg is None:
        raise RuntimeError(f"no dialog matching {dialog_title!r}")
    for k in b._dialog_children(dlg):
        if k.cls == "ListBox" and k.ctrl_id == control_id:
            if select is None and select_text is None:
                return json.dumps({"ok": True, "items": b.listbox_items(k.hwnd),
                                   "selected": b.listbox_selected(k.hwnd)})
            items = b.listbox_items(k.hwnd)
            idx = select
            if idx is None:
                idx = next((i for i, it in enumerate(items)
                            if select_text.strip().lower() in it.strip().lower()), None)
                if idx is None:
                    raise RuntimeError(f"no item matching {select_text!r}; "
                                       f"available: {items[:40]}")
            res = b.listbox_select(k.hwnd, idx)
            return json.dumps({"ok": True, "selected_item": items[idx],
                               "selection": res,
                               "items": b.listbox_items(k.hwnd)})
    raise RuntimeError(f"no list box with control id {control_id} in {dialog_title!r}")


@server.tool()
@safe
def hummod_dialog_button(dialog_title: str, caption: str, engine: str = "default") -> str:
    """Press a button of an open dialog by its caption (e.g. 'View Panel', 'Close')."""
    b, _ = get_bridge(engine)
    dlg = b.dialog_with_text(dialog_title) or b.dialog_by_title(dialog_title)
    if dlg is None:
        raise RuntimeError(f"no dialog matching {dialog_title!r}")
    if not b.press_dialog_button(dlg, caption):
        raise RuntimeError(f"no button captioned {caption!r}")
    time.sleep(0.3)
    return json.dumps({"ok": True, "pressed": caption, "dialog": hex(dlg)})


@server.tool()
@safe
def hummod_open_panel(variable: str, engine: str = "default",
                       category: str | None = None,
                       panel: str | None = None) -> str:
    """Open the panel that shows a variable, via the engine's own Find dialog.

    QCP's pages are canvas-drawn and are not reachable through the menu tree,
    so this is the reliable way to switch panels: Find -> Category -> Item ->
    Panel -> 'View Panel'. `variable` may be the full variable name or a unique
    substring; `category` optionally narrows the search."""
    b, _ = get_bridge(engine)
    dlg = b.dialog_with_text("FIND VARIABLE'S PANEL")
    if dlg is None:
        b.command(b.menu_tree().walk("Find").cmd_id)
        time.sleep(1.0)
        dlg = b.dialog_with_text("FIND VARIABLE'S PANEL")
    if dlg is None:
        raise RuntimeError("the Find dialog did not open")
    lbs = {k.ctrl_id: k.hwnd for k in b._dialog_children(dlg) if k.cls == "ListBox"}
    if 10 not in lbs or 20 not in lbs:
        raise RuntimeError(f"unexpected Find dialog layout: {sorted(lbs)}")
    cats = b.listbox_items(lbs[10])
    want = variable.strip().lower()
    tried = []
    for ci, cname in enumerate(cats):
        if category and category.strip().lower() not in cname.strip().lower():
            continue
        b.listbox_select(lbs[10], ci)
        items = b.listbox_items(lbs[20])
        hit = next((i for i, it in enumerate(items) if want in it.strip().lower()), None)
        if hit is None:
            tried.append({"category": cname, "n_items": len(items)})
            continue
        b.listbox_select(lbs[20], hit)
        pi = 0
        panels = b.listbox_items(lbs[30]) if 30 in lbs else []
        if panels:
            pi = 0
            if panel:
                pi = next((k for k, pn in enumerate(panels)
                           if panel.strip().lower() in pn.strip().lower()), 0)
            b.listbox_select(lbs[30], pi)
            panels = b.listbox_items(lbs[30])
        b.press_dialog_button(dlg, "View Panel")
        time.sleep(0.4)
        b.press_dialog_button(dlg, "Close")
        return json.dumps({"ok": True, "variable": variable, "category": cname,
                           "item": items[hit], "panels": panels,
                           "panel_opened": panels[pi] if panels else None})
    # QCP's Find dialog lists ~445 categories; echoing all of them made a
    # failed lookup return a multi-kilobyte payload that drowns the actual
    # error. Report a short sample plus the count instead.
    return json.dumps({"ok": False, "error": f"variable {variable!r} not found",
                       "n_categories": len(cats),
                       "categories_sample": cats[:25],
                       "tried": tried})


@server.tool()
@safe
def hummod_click(x: int | str, y: int | str, engine: str = "default", button: str = "left",
                 double: bool | str = False, method: str = "message") -> str:
    """Click at window-relative (x, y) - the coordinate space of hummod_shot.

    method='message' (default) sends WM_LBUTTON*/WM_RBUTTON* to the window and
    works for owner-drawn canvases; method='mouse' moves the real cursor."""
    b, _ = get_bridge(engine)
    info = b.click(int(x), int(y), button=button, double=double, method=method)
    return json.dumps({"ok": True, **info})


@server.tool()
@safe
def hummod_drag(x1: int | str, y1: int | str, x2: int | str, y2: int | str,
                engine: str = "default", steps: int | str = 20) -> str:
    """Drag from (x1,y1) to (x2,y2) in window coordinates - canvas slidebars."""
    b, _ = get_bridge(engine)
    return json.dumps({"ok": True, **b.drag(int(x1), int(y1), int(x2), int(y2), steps=steps)})


@server.tool()
@safe
def hummod_radio(panel_path: str, ordinal: int | str | None = None,
                 expected: int | str | None = None,
                 value: str | None = None, probe_vars: list[str] | dict | None = None,
                 engine: str = "default", probe_vars_csv: str = "") -> str:
    """Click a radio button on a panel page. Prefer value='On'/'Off' (label semantics from the profile); or ordinal among radios sorted by control id (expected = total count guardrail).

    probe_vars optionally names model variables to read back after the click, so
    the effect can be verified at model level (e.g. ['RespiratoryCenter-Integration.TotalDrive'])
    - the only reliable confirmation when the widget's own check state is not exposed.

    probe_vars_csv is the string-typed equivalent ('A,B,C') for MCP clients that
    cannot express a JSON array; it takes precedence when given.
    """
    b, p = get_bridge(engine)
    if probe_vars_csv:
        probe_vars = _csv_list(probe_vars_csv)
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
    time.sleep(0.2)
    fresh = sorted([c for c in b.controls() if c.is_radio], key=lambda c: c.ctrl_id)
    raw = [i for i, c in enumerate(fresh) if c.checked]
    style_ok = all(c.check_state_readable for c in fresh)
    # A radio group that reports no selection although its style supports a
    # check state means the engine keeps the switch in the model, not in the
    # widget (HumMod does exactly this) - say so instead of claiming "off".
    if raw:
        readable = True
    elif not style_ok:
        readable = False
    else:
        readable = None
    out = {"ok": True,
           "pressed": f"{panel_path} radio[{radios.index(target)}]"
                      + (f" ({value})" if value else ""),
           "count": len(radios),
           "state_readable": readable,
           "checked": raw if readable is True else None}
    if readable is not True:
        out["note"] = ("the widget does not expose its check state (the engine keeps "
                       "the switch in the model); pass probe_vars to verify the effect "
                       "on model variables")
    if probe_vars:
        out["probe_values"] = _probe_model(b, p, probe_vars)
    return json.dumps(out)


def _probe_model(b: Bridge, p: Profile, probe_vars: list[str]) -> dict:
    """Export the current state and read the given model variables back."""
    os.makedirs(OUTDIR, exist_ok=True)
    name = "_probe_" + datetime.now().strftime("%H%M%S%f")
    path = _export_snapshot(b, p, name)
    want = {v.lower() for v in probe_vars}
    vals = parse_export(path, want)
    return {k: vals[k] for k in vals}


@server.tool()
@safe
def hummod_action(panel_path: str, ordinal: int | str,
                  expected: int | str | None = None, engine: str = "default") -> str:
    """Click an action button on a panel page - the canvas triggers drawn as '!'
    buttons (e.g. CPR Draw Blood / Shock Now on Intervention/CPR and
    Trauma/Ventricular Fibrillation). Ordinal among action buttons sorted by
    control id; expected = total count (guardrail). Counts and meanings per
    panel live in profile radio_semantics/action notes.

    panel_path='current' skips menu navigation and presses on whichever page
    the engine currently shows - needed for Find-dialog pages that are not in
    the menu tree (e.g. QCP's treadmill Exercise page)."""
    b, _ = get_bridge(engine)
    if panel_path.strip().lower() not in ("", ".", "current"):
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
def hummod_probe_radio(panel_path: str, probe_vars: list[str] | dict,
                       engine: str = "default") -> str:
    """Discover radio-button semantics automatically.

    Presses each radio on the page in turn and reads probe_vars from a snapshot
    after every press, so the caller can tell which radio means On/Off even
    though the native buttons carry no text. Returns per-ordinal observed
    values plus a ready-to-paste profile snippet for radio_semantics.
    """
    b, p = get_bridge(engine)
    _navigate(panel_path, engine)
    radios = sorted([c for c in b.controls() if c.is_radio], key=lambda c: c.ctrl_id)
    if not radios:
        raise RuntimeError("no radio buttons on this page")
    os.makedirs(OUTDIR, exist_ok=True)
    want = {v.lower() for v in probe_vars}
    results = []
    for i, r in enumerate(radios):
        b.press(r.hwnd)
        time.sleep(0.4)
        sol = os.path.join(OUTDIR, f"probe_{panel_path.replace('/', '_')}_{i}.SOL")
        if os.path.exists(sol):
            os.remove(sol)
        b.save_file_dialog(p.file["save_sol"], sol, tuple(p.dialog_edit_ids))
        vals = parse_export(sol, want)
        results.append({"ordinal": i, "ctrl_id": r.ctrl_id, "values": vals})
    # restore: press the first radio again (usually Off) and reset the model
    b.press(radios[0].hwnd)
    time.sleep(0.2)
    snippet = {panel_path: {f"radio{i}": "?" for i in range(len(radios))}}
    return json.dumps({"ok": True, "panel": panel_path, "count": len(radios),
                       "probes": results,
                       "profile_snippet_template": snippet,
                       "note": "radio captions are owner-drawn; label each ordinal from the "
                               "observed value change (e.g. the one raising a switch to 1 = 'on')"})


@server.tool()
@safe
def hummod_edit(panel_path: str, ordinal: int | str, value: str,
                expected: int | str | None = None, engine: str = "default") -> str:
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
def hummod_slider(panel_path: str, ordinal: int | str | None = None, pos: int | str = 0,
                  expected: int | str | None = None, engine: str = "default",
                  ctrl_id: int | str | None = None, label: str | None = None,
                  value: float | str | None = None) -> str:
    """Move a slider on a panel page.

    Locate the slider by ordinal (order by control id), by ctrl_id, or by label
    (the caption printed next to it - matched against the page's static texts,
    so owner-drawn sliders are addressable too).
    Pages often mix parameter sliders with plain scroll bars; hummod_inspect
    lists both with ctrl_id, rect and position.
    value= asks for the parameter VALUE instead of a raw scroll index: the
    engine-specific index->value table from the profile (slider_value_lists)
    is used to find the matching index.  That is the only way to hit a
    non-default value on engines whose steppers have an irregular scale
    (AVP v3.1.0 Lifestyle/Diet/Goal: index 11 -> 20, 30 -> 210, 60 -> 1500).
    WARNING: some engines (3.0.4) accept the thumb move but do not commit the
    model value - verify via hummod_snapshot and prefer XML parm edits there.
    """
    b, p = get_bridge(engine)
    _navigate(panel_path, engine)
    sliders = sorted([c for c in b.controls() if c.cls == "ScrollBar"],
                     key=lambda c: c.ctrl_id)
    if expected is not None and len(sliders) != expected:
        raise RuntimeError(f"slider count mismatch: found {len(sliders)}, expected {expected}")
    if not sliders:
        raise RuntimeError("no ScrollBar controls on this page")

    target = None
    how = None
    if ctrl_id is not None:
        target = next((c for c in sliders if c.ctrl_id == ctrl_id), None)
        how = "ctrl_id"
        if target is None:
            raise RuntimeError(f"no slider with ctrl_id {ctrl_id}; available: "
                               f"{[(c.ctrl_id, c.scroll_pos) for c in sliders]}")
    elif label is not None:
        want = label.strip().lower()
        statics = [c for c in b.controls() if c.cls == "Static" and c.text.strip()]
        best = None
        for c in sliders:
            for s in statics:
                if want in s.text.strip().lower() and (
                        abs(s.y_center - c.y_center) <= 24 or s.left > c.right):
                    d = abs(s.y_center - c.y_center)
                    if best is None or d < best[0]:
                        best = (d, c)
                    break
        if best is None:
            listing = [{"ordinal": i, "ctrl_id": c.ctrl_id, "pos": c.scroll_pos,
                        "rect": [c.left, c.top, c.right, c.bottom]}
                       for i, c in enumerate(sliders)]
            raise RuntimeError(
                f"no slider found near a label matching {label!r}; "
                f"sliders on this page: {listing}. "
                + ("This engine draws its captions on the canvas, so text matching "
                   "cannot work here - address the slider by ordinal or ctrl_id, "
                   "or use hummod_shot to see which one is which."
                   if not statics else
                   "page labels: " + str([s.text.strip() for s in statics][:20])))
        target, how = best[1], "label"
    elif ordinal is not None:
        if ordinal < 0 or ordinal >= len(sliders):
            raise RuntimeError(f"ordinal {ordinal} out of range ({len(sliders)} sliders)")
        target, how = sliders[ordinal], "ordinal"
    else:
        raise RuntimeError("provide ordinal, ctrl_id or label")

    resolved_value = None
    if value is not None:
        want = float(value)
        pos, resolved_value = _pos_for_value(p, panel_path, target.ctrl_id, want)
        how = f"{how}+value"

    b.set_slider(target.hwnd, _parent_of(target.hwnd), pos, commit_endscroll=True)
    note = None
    if p.quirks.get("slider_commits") is False:
        note = p.quirks.get("slider_note")
    out = {"ok": True, "pos": pos, "located_by": how,
           "ctrl_id": target.ctrl_id, "slider_count": len(sliders),
           "verify": "snapshot the model value", "quirk": note}
    if resolved_value is not None:
        out["requested_value"] = float(value)
        out["value_at_pos"] = resolved_value
    return json.dumps(out)


def _pos_for_value(p: Profile, panel_path: str, ctrl_id: int, want: float):
    """Map a requested parameter value to a scroll index via the profile table.

    The profile carries, per panel and per scroll-bar control id, the list of
    values the engine produces for each scroll index (measured, because the
    scale is engine-specific and irregular).  Returns (index, value_at_index).
    """
    table = (p.slider_value_lists or {}).get(panel_path, {})
    entry = table.get(str(ctrl_id)) or table.get(ctrl_id)
    if not entry:
        raise RuntimeError(
            f"no slider value table for {panel_path!r} ctrl_id {ctrl_id}; "
            f"known: {sorted(table)}")
    values = entry.get("values") if isinstance(entry, dict) else entry
    if not values:
        raise RuntimeError(f"empty slider value table for {panel_path!r} ctrl_id {ctrl_id}")
    exact = [i for i, v in enumerate(values) if abs(float(v) - want) < 1e-9]
    if exact:
        return exact[0], float(values[exact[0]])
    best = min(range(len(values)), key=lambda i: abs(float(values[i]) - want))
    return best, float(values[best])


@server.tool()
@safe
def hummod_set_param(panel_path: str, name: str, value: float | str,
                     engine: str = "default", exact: bool | str = False) -> str:
    """Set a named model parameter through the panel's own stepper.

    `name` is the parameter label as printed on the page (e.g. 'Salt',
    'Block (%)'); the profile's param_slots maps it to the page's scroll-bar
    control id, and slider_value_lists maps that control id to the
    index->value scale, so the stepper can be driven to the requested VALUE
    without knowing the raw index.  This is what makes AVP v3.1.0's
    Lifestyle/Diet/Goal electrolyte goals settable from the GUI.
    """
    b, p = get_bridge(engine)
    _navigate(panel_path, engine)
    slots = (p.param_slots or {}).get(panel_path, {})
    key = None
    for k in slots:
        if k.strip().lower() == name.strip().lower():
            key = k
            break
    if key is None:
        raise RuntimeError(f"parameter {name!r} not known on {panel_path!r}; "
                           f"known: {sorted(slots)}")
    slot = slots[key]
    ctrl_id = int(slot["ctrl_id"])
    want = float(value)
    pos, got = _pos_for_value(p, panel_path, ctrl_id, want)
    if exact and abs(got - want) > 1e-9:
        raise RuntimeError(f"value {want!r} is not reachable on {key!r} "
                           f"(closest {got!r} at index {pos})")
    sliders = sorted([c for c in b.controls() if c.cls == "ScrollBar"],
                     key=lambda c: c.ctrl_id)
    target = next((c for c in sliders if c.ctrl_id == ctrl_id), None)
    if target is None:
        raise RuntimeError(f"control {ctrl_id} not found on {panel_path!r}")
    b.set_slider(target.hwnd, _parent_of(target.hwnd), pos, commit_endscroll=True)
    return json.dumps({"ok": True, "panel": panel_path, "param": key,
                       "requested_value": want, "value_at_pos": got, "pos": pos,
                       "ctrl_id": ctrl_id, "var": slot.get("var"),
                       "verify": f"snapshot {slot.get('var')!r}"})


def _parent_of(hwnd: int) -> int:
    return user32.GetParent(hwnd)


def _export_snapshot(b: Bridge, p: Profile, name: str) -> str:
    """Export the engine state (HumMod .SOL / QCP .ICS) into OUTDIR; return the path."""
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
    return path


@server.tool()
@safe
def hummod_snapshot(name: str, vars: list[str] | dict | None = None,
                    engine: str = "default", vars_csv: str = "") -> str:
    """Export engine state (HumMod: File > Save Solution .SOL; QCP: File > Save Initial Conditions .ICS) into the MCP output dir; optionally parse named variables.

    The simulation clock (System.X on HumMod, X on QCP) is always included in
    'values', so every snapshot tells you which model time it was taken at.
    Requested names that do not exist in the model are listed under 'missing'
    instead of being silently dropped.

    vars_csv is the string-typed equivalent ('A,B,C') for MCP clients that cannot
    express a JSON array; it takes precedence when given. Omitting both exports
    the full solution and returns only the clock."""
    b, p = get_bridge(engine)
    if vars_csv:
        vars = _csv_list(vars_csv)
    path = _export_snapshot(b, p, name)
    want = {v.lower() for v in (vars or [])}
    clock = "system.x" if p.file.get("save_sol") is not None else "x"
    want.add(clock)  # always report the model clock
    vals = parse_export(path, want)
    have = {k.lower() for k in vals}
    missing = [v for v in (vars or []) if v.lower() not in have]
    return json.dumps({"ok": True, "path": path, "values": vals, "missing": missing})


@server.tool()
@safe
def hummod_save_ics(name: str, engine: str = "default") -> str:
    """Save Initial Conditions (.ICS) via File > Save Initial Conditions.

    Unlike hummod_snapshot (which always exports the .SOL solution on HumMod),
    this drives the engine's own ICs save, so the file can later be reloaded
    with hummod_load_ics to restore the exact scenario. The file is written to
    the MCP output dir as <name>.ICS."""
    b, p = get_bridge(engine)
    os.makedirs(OUTDIR, exist_ok=True)
    save_id = p.file.get("save_ics")
    if save_id is None:
        save_id = b.menu_tree().walk("File/Save Initial Conditions").cmd_id
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    path = os.path.join(OUTDIR, safe_name + (".ICS" if not safe_name.lower().endswith(".ics") else ""))
    if os.path.exists(path):
        path = os.path.join(OUTDIR, safe_name + "_" + datetime.now().strftime("%H%M%S") + ".ICS")
    b.save_file_dialog(save_id, path, tuple(p.dialog_edit_ids), tail_markers=())
    return json.dumps({"ok": True, "path": path})


@server.tool()
@safe
def hummod_load_ics(path: str, engine: str = "default") -> str:
    """Load Initial Conditions (.ICS) via File > Load Initial Conditions.

    `path` may be absolute or a file name inside the MCP output dir. Restores
    the scenario previously stored with hummod_save_ics. Note: on HumMod a
    subsequent in-memory Restart returns to the model defaults, NOT to the
    loaded ICs - reload explicitly when needed."""
    b, p = get_bridge(engine)
    cand = path if os.path.isabs(path) else os.path.join(OUTDIR, path)
    if not os.path.exists(cand) and not cand.lower().endswith(".ics") and os.path.exists(cand + ".ICS"):
        cand += ".ICS"
    load_id = p.file.get("load_ics")
    if load_id is None:
        load_id = b.menu_tree().walk("File/Load Initial Conditions").cmd_id
    b.load_file_dialog(load_id, cand, tuple(p.dialog_edit_ids))
    return json.dumps({"ok": True, "path": cand})


@server.tool()
@safe
def hummod_get_vars(sol_path: str, names: list[str] | dict,
                    names_csv: str = "") -> str:
    """Read current (last sample) variable values from an exported file.

    HumMod exports .SOL (XML) and QCP exports .ICS (text key-value); the
    format is detected from the file head, so both work here.
    Returns {values, missing}.

    names_csv is the string-typed equivalent ('A,B,C') for MCP clients that
    cannot express a JSON array; it takes precedence when given."""
    if names_csv:
        names = _csv_list(names_csv)
    want = {n.lower() for n in names}
    vals = parse_export(sol_path, want)
    have = {k.lower() for k in vals}
    return json.dumps({"values": vals, "missing": [n for n in names if n.lower() not in have]})


@server.tool()
@safe
def hummod_history(sol_path: str, vars: list[str] | dict, max_points: int | str = 500,
                   vars_csv: str = "") -> str:
    """Time series from a .SOL export: simulation-time axis (System.X) plus one series per requested variable (e.g. 'BloodVol.Vol'), downsampled to max_points (latest sample always included). Plot-ready.

    vars_csv is the string-typed equivalent ('A,B,C') for MCP clients that cannot
    express a JSON array; it takes precedence when given."""
    if vars_csv:
        vars = _csv_list(vars_csv)
    try:
        hist = parse_sol_history(sol_path, set(vars), max_points=max_points)
        return json.dumps({"ok": True, **hist})
    except KeyError as e:
        return json.dumps({"ok": False,
                           "error": f"{e}; note: history requires HumMod .SOL (QCP .ICS has no time series)"})


@server.tool()
@safe
def hummod_dismiss_modal(engine: str = "default", prefer: int | str = 6) -> str:
    """Close any engine modal dialog (e.g. Tech window) that blocks automation.

    `prefer` is the button id to click when the dialog offers it (6 = IDYES,
    i.e. answer "yes / continue"; 1 = IDOK). HumMod 1.6.1 raises MessageBox
    popups whose buttons are IDYES(6)/IDNO(7) - e.g. 'The ECG shows V-Fib!
    Continue?' - so the button that is actually there has to be clicked.
    Returns the dialogs that were found, their text, and whether they closed."""
    b, _ = get_bridge(engine)
    before = b.dialog_info()
    found = b.dismiss_modals(prefer=prefer)
    after = b.dialog_info()
    return json.dumps({
        "dismissed": [{"hwnd": hex(h), "text": next(
            (d["message"] for d in before if d["hwnd"] == hex(h)), "")}
            for h in found],
        "still_open": after,
        "ok": not after,
    })


@server.tool()
@safe
def hummod_modals(engine: str = "default") -> str:
    """List the modal dialogs the engine currently has open (title, message, buttons).

    Use this when a command fails with 'engine still blocked by a modal
    dialog': it says *what* the engine is asking instead of only *that* it is
    blocked."""
    b, _ = get_bridge(engine)
    dialogs = b.dialog_info()
    return json.dumps({"count": len(dialogs), "dialogs": dialogs,
                       "busy": b.busy()})


def _server_version() -> str:
    """The package version, for the citation. Falls back to a constant when
    pyproject.toml is not next to the package (e.g. a vendored copy)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pyproject = os.path.join(root, "pyproject.toml")
    try:
        with open(pyproject, encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("version"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return "0.1.0"


@server.tool()
@safe
def hummod_profile(engine: str = "default") -> str:
    """Return the active engine profile: file menu ids, stop semantics and quirks."""
    _, p = get_bridge(engine)
    return json.dumps({"name": p.name, "file": p.file, "stop_cmd_id": p.stop_cmd_id,
                       "quirks": p.quirks, "page_ids": p.page_ids})


@server.tool()
@safe
def hummod_integrity_statement(ai_contributions: list[str] | dict | None = None,
                               human_contributions: list[str] | dict | None = None,
                               author: str = "", date: str = "",
                               ai_contributions_csv: str = "",
                               human_contributions_csv: str = "") -> str:
    """Build the academic-integrity statement that MUST be appended to any report
    produced with this tool.

    Returns ready-to-paste markdown with the citation filled in. Call this
    before delivering the final report and append the returned 'statement'
    verbatim at the very end of the report.

    ai_contributions   what the AI actually did (e.g. "drove the engine through
                       the hummod_* tools", "parsed the exported SOL files")
    human_contributions what the human did (e.g. "designed the protocol",
                       "interpreted the results", "wrote the report")
    author             the student's name, if they want it in the statement
    date               accessed date; defaults to today

    The statement also states the project's position: this tool is meant to
    automate execution and data handling, not to replace experimental design
    or interpretation - completely outsourcing an assignment to AI is not
    endorsed."""
    if ai_contributions_csv:
        ai_contributions = _csv_list(ai_contributions_csv)
    if human_contributions_csv:
        human_contributions = _csv_list(human_contributions_csv)
    ai = [str(x) for x in (ai_contributions or [])]
    human = [str(x) for x in (human_contributions or [])]
    stamp = (date or datetime.now().strftime("%Y-%m-%d")).strip()
    version = _server_version()
    cite = (f"TaoChnn. *Oh My HumMod* (v{version}). MCP server driving HumMod / "
            f"QCP physiology engines via window messages. "
            f"https://github.com/TaoChnn/oh-my-hummod (accessed {stamp}).")
    bibtex = (
        "@misc{ohmyhummod2026,\n"
        "  author       = {TaoChnn},\n"
        "  title        = {Oh My HumMod: an MCP server driving HumMod / QCP "
        "physiology\n"
        "                  engines via window messages},\n"
        "  howpublished = {\\url{https://github.com/TaoChnn/oh-my-hummod}},\n"
        "  year         = {2026},\n"
        "  note         = {v" + version + ", accessed " + stamp + "}\n"
        "}")
    ai_txt = "; ".join(ai) if ai else (
        "[请填写：AI 实际承担的工作，例如驱动引擎执行参数设定与仿真、"
        "解析导出文件并生成图表与派生指标]")
    human_txt = "; ".join(human) if human else (
        "[请填写：本人独立完成的工作，例如实验方案设计、参数取值与范围确定、"
        "数据合理性判断与结果解释、报告撰写]")
    author_txt = f"（作者：{author}）" if author.strip() else ""

    statement = (
        "## 学术诚信与 AI 使用声明\n\n"
        f"{author_txt}\n\n"
        "本实验的部分仿真操作与数据处理使用了开源工具 **oh-my-hummod**"
        f"（TaoChnn, v{version}, https://github.com/TaoChnn/oh-my-hummod）完成。"
        "该工具通过操作系统窗口消息驱动 HumMod / QCP 引擎，并解析引擎自身的"
        "导出文件（.SOL / .ICS），不修改引擎程序本身。\n\n"
        f"- **由 AI 助手完成的部分**：{ai_txt}\n"
        f"- **由本人独立完成的部分**：{human_txt}\n\n"
        f"**引用**：{cite}\n\n"
        "**关于 AI 参与程度的说明**：本工具的定位是自动化实验的*执行*与"
        "*数据处理*，以节省重复性操作的时间；实验方案设计、参数取值与范围确定、"
        "对数据合理性的判断、结果的生理学解释与报告撰写，仍应由本人完成。"
        "仿真结果中可能包含引擎自身的建模缺陷（例如部分版本不计算 EPO、"
        "停搏后酸碱计算出现代数假象等），这些需要使用者具备相应领域知识才能识别。"
        "**本项目不鼓励、也不支持将作业整体交由 AI 代为完成。**\n\n"
        "*本声明用于说明工具使用范围与作者贡献边界，不作为规避课程 AI 使用规范的"
        "依据；使用者应同时遵守所在课程与学校的相关规定。*\n\n"
        "```bibtex\n" + bibtex + "\n```"
    )
    return json.dumps({
        "ok": True,
        "statement": statement,
        "citation": cite,
        "bibtex": bibtex,
        "version": version,
        "date": stamp,
        "reminder": ("Append this statement verbatim at the END of the final "
                     "report, and fill in every [请填写] placeholder."),
    })


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()

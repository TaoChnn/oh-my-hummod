"""Engine profiles: version-specific facts that cannot be discovered at runtime.

Discovery (bridge.menu_tree / bridge.controls) reads everything else live, so a
profile only records semantics and quirks:
  - exe_names           how to recognise the engine process
  - file                File-menu command ids for SOL/ICS dialogs (dialog automation
                        also needs the native dialog's Edit control ids)
  - stop_cmd_id         Stop-menu command id (the completion-signal fallback
                        for engines without a status-bar run signal, e.g. QCP)
  - quirks              engine behaviours that change tool behaviour
Profiles are plain JSON so users can add a new engine without touching code.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields


@dataclass
class Profile:
    name: str
    exe_names: list[str]
    file: dict            # {"load_ics": id, "save_ics": id, "load_sol": id|None, "save_sol": id, "exit": id}
    dialog_edit_ids: list[int]
    stop_cmd_id: int
    bind_marker: str = "Sizing"   # top-level menu label that appears once the model is bound
    quirks: dict = field(default_factory=dict)
    page_ids: dict = field(default_factory=dict)   # optional curated panel path -> cmd id
    slider_maps: dict = field(default_factory=dict)  # panel path -> pos->value semantics for canvas sliders
    slider_value_lists: dict = field(default_factory=dict)  # panel path -> ctrl_id -> {"values": [v0, v1, ...]}
    param_slots: dict = field(default_factory=dict)  # panel path -> parameter label -> {"ctrl_id": n, "var": name}
    radio_semantics: dict = field(default_factory=dict)  # panel path -> {"on": ordinal, "off": ordinal, ...}
    action_semantics: dict = field(default_factory=dict)  # panel path -> {"0": "meaning", ...}
    menu_aliases: dict = field(default_factory=dict)  # canonical path -> build-specific path
    panels: dict = field(default_factory=dict)     # version-specific panel paths for tests/demos
    extra: dict = field(default_factory=dict)      # profile keys this library does not know yet

    @classmethod
    def load(cls, path_or_name: str) -> "Profile":
        if not os.path.exists(path_or_name):
            builtin = os.path.join(os.path.dirname(__file__), "profiles", path_or_name + ".json")
            if os.path.exists(builtin):
                path_or_name = builtin
            elif os.path.exists(builtin + ".json"):
                path_or_name = builtin
        with open(path_or_name, encoding="utf-8") as f:
            data = json.load(f)
        # Unknown keys are kept, not fatal: a profile may record facts that a
        # newer library does not consume yet (field trials add them as they
        # are discovered). Silently dropping them would lose that evidence.
        known = {f.name for f in fields(cls)}
        extra = {k: v for k, v in data.items() if k not in known}
        obj = cls(**{k: v for k, v in data.items() if k in known})
        obj.extra = extra
        return obj

"""Engine profiles: version-specific facts that cannot be discovered at runtime.

Discovery (bridge.menu_tree / bridge.controls) reads everything else live, so a
profile only records semantics and quirks:
  - exe_names           how to recognise the engine process
  - file                File-menu command ids for SOL/ICS dialogs (dialog automation
                        also needs the native dialog's Edit control ids)
  - stop_cmd_id         completion semantics: grayed Stop = finished
  - quirks              engine behaviours that change tool behaviour
Profiles are plain JSON so users can add a new engine without touching code.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


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
    radio_semantics: dict = field(default_factory=dict)  # panel path -> {"on": ordinal, "off": ordinal, ...}
    action_semantics: dict = field(default_factory=dict)  # panel path -> {"0": "meaning", ...}
    menu_aliases: dict = field(default_factory=dict)  # canonical path -> build-specific path
    panels: dict = field(default_factory=dict)     # version-specific panel paths for tests/demos

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
        return cls(**data)

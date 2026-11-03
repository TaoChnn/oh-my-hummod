# oh-my-hummod

Drive **HumMod / QCP** physiology simulation engines from any MCP client
(ZCode, Claude, ...) — window messages only, **no engine source required, no
reverse engineering**. The engine cannot tell these messages from a user's
mouse.

```
MCP client ──stdio──> oh-my-hummod server ──Win32 messages──> engine EXE (3.0.4 / 1.6.1 / QCP 2005)
                                └── parses .SOL exports (10,346 variables)
```

## Design: discovery first, profiles for the rest

At attach time the bridge enumerates the engine's **live menu tree**, so menu
actions are resolved by *label* (`"Restart"`, `"Go/10 Min"`, `"Trauma/Hemorrhage"`)
— no hard-coded ids. A small per-version JSON profile supplies only what cannot
be discovered:

| Profile field | Purpose |
|---|---|
| `file` | File-menu command ids for the SOL/ICS save/load dialogs |
| `dialog_edit_ids` | native file-dialog filename Edit control ids |
| `stop_cmd_id` | completion semantics: grayed Stop = simulation finished |
| `radio_semantics` | unlabeled radio buttons (owner-drawn captions) → meaning |
| `quirks` | engine behaviours that change tool behaviour (slider commit, EPO, model noise) |

Adding a new engine version = run `hummod_inspect` against it, note the
differences, drop a JSON in `profiles/`. No code changes.

## Install & run

```
pip install -e .            # deps: mcp (pywin32 not required - pure ctypes)
```

Register with an MCP client (ZCode `~/.zcode/cli/config.json`):

```json
{
  "mcp": {
    "servers": {
      "hummod": {
        "command": "python",
        "args": ["-m", "oh_my_hummod.server"],
        "env": {
          "HUMMOD_ENGINE_DIR": "C:\\HumMod",
          "HUMMOD_PROFILE": "hummod_3.0.4",
          "HUMMOD_OUTDIR": "C:\\hummod-exports"
        }
      }
    }
  }
}
```

`HUMMOD_PROFILE` may be omitted — the server auto-detects the engine by its
EXE name.

## Tools

`hummod_status` `hummod_start` `hummod_restart` `hummod_inspect`
`hummod_navigate` `hummod_menu_command` `hummod_go` (waits for completion)
`hummod_radio` (by profile label **or** ordinal, returns checked states)
`hummod_edit` `hummod_slider` `hummod_snapshot` (SOL export + variable
parsing) `hummod_get_vars` `hummod_dismiss_modal` `hummod_profile`.

Errors return one-line JSON; unknown menu paths list the available siblings so
agents can self-correct.

## Validated profiles

| Engine | Status |
|---|---|
| HumMod Clemmer Salt **3.0.4** | ✅ full protocol driven end-to-end (hemorrhage 4.3.1, five time points) |
| HumMod standalone **1.6.1** | profile drafted, validation pending (menu ids confirmed identical - same code lineage) |
| **QCP 2005** | experimental stub - different UI framework, needs a discovery pass |

## Tests

With an engine running:

```
set HUMMOD_ENGINE_DIR=C:\path\to\engine
python tests\smoke.py       # bridge-level: attach, menus, radio, SOL export
python tests\mcp_smoke.py   # MCP-protocol level: tools over stdio
```

## Licensing

This project is original code (MIT). Engine EXEs are untouched; model XML files
are GPL-2.0 (editable). Compatible with HumMod's published terms: personal,
educational and research use.

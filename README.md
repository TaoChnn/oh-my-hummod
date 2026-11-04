# oh-my-hummod

Drive **HumMod / QCP** physiology simulation engines from any MCP client
(ZCode, Claude, ...) — window messages only, **no engine source required, no
reverse engineering**. The engine cannot tell these messages from a user's
mouse.

```
MCP client ──stdio──> oh-my-hummod server ──Win32 messages──> engine EXE
                                └── parses .SOL / .ICS exports (10,000+ variables)
```

**Validated engines:** HumMod Clemmer Salt 3.0.4 ✅ · HumMod-BAT ✅ ·
avphummod (Modular) ✅ · HumMod standalone 1.6.1 ✅ · QCP 2005 ✅ (core)

## Quick start (fresh Windows machine)

Requirements: **Windows 10/11**, **Python 3.10+**, and an engine folder
(download HumMod/QCP from hummod.org or your course materials — this project
ships no engine).

```bat
:: 1) get the code
git clone https://github.com/TaoChnn/oh-my-hummod.git
cd oh-my-hummod

:: 2) install (pulls in the `mcp` package)
pip install -e .

:: 3) sanity check with your engine folder
set HUMMOD_ENGINE_DIR=C:\HumMod
python tests\engine_smoke.py --engine C:\HumMod --profile hummod_3.0.4
::   expect: ENGINE_SMOKE_OK

:: 4) register with your MCP client (see snippet below), restart the client,
::    and the hummod_* tools appear in the tool list
```

The profile is auto-detected from the engine EXE in `HUMMOD_ENGINE_DIR`
(`hummod_3.0.4` / `hummod_1.6.1` / `qcp_2005` / `hummod_bat` / `avphummod`).
`tests\discover.py --engine C:\Some\Other\Build` prints everything needed to
add a profile for an unknown build.

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
| `bind_marker` | top-level menu label that signals the model finished binding |
| `radio_semantics` | unlabeled radio buttons (owner-drawn captions) → meaning |
| `quirks` | engine behaviours that change tool behaviour (slider commit, EPO, model noise) |

Adding a new engine version = run `tests/discover.py` against it, note the
differences, drop a JSON in `profiles/`. No code changes.

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

`hummod_status` `hummod_start` `hummod_restart` `hummod_inspect` `hummod_engines`
`hummod_navigate` `hummod_menu_command` `hummod_go` (waits for completion)
`hummod_radio` (by profile label **or** ordinal, returns checked states) `hummod_action` (canvas "!" triggers, e.g. CPR defibrillation - must run during simulation)
`hummod_edit` `hummod_slider` `hummod_snapshot` (SOL export + variable
parsing) `hummod_get_vars` `hummod_history` (time series, plot-ready)
`hummod_probe_radio` (auto-discovers radio semantics) `hummod_dismiss_modal` `hummod_profile`.

Every tool takes an optional `engine=` key, so one server can drive several
engine builds at once (see `engines.json`); `hummod_engines` lists them with
running state and detected profile.

Notes that came out of multi-engine field trials:
- `hummod_inspect` takes `mode="menu"|"controls"|"both"` and an optional
  `panel_path=`; ask for `mode="controls"` when you only need widgets - the
  menu tree alone is long and drowns the widget list.
- Panel paths resolve by label, with build-specific aliases from the profile
  (`"Physiology/Lungs/Thorax"` -> `"Respiration/Thorax"` on the 3.x family)
  and a fuzzy fallback that lists near-misses.
- Event modals that some engines pop on parameter changes are dismissed
  automatically before the next command.
- `hummod_probe_radio` presses each radio in turn and snapshots a probe
  variable, so On/Off ordinals are discovered rather than guessed.

Errors return one-line JSON; unknown menu paths list the available siblings so
agents can self-correct.

## Validated profiles

| Engine build | Profile | Status |
|---|---|---|
| HumMod Clemmer Salt **3.0.4** | `hummod_3.0.4` | ✅ full protocol end-to-end (hemorrhage 4.3.1, five time points, SOL-verified) |
| **HumMod-BAT** (2018 custom build) | `hummod_bat` | ✅ engine_smoke passed - menu skeleton identical to 3.0.4, profile reuses it |
| **avphummod** (Modular AVP build) | `avphummod` | ✅ engine_smoke passed - same lineage; ships Model Solver.exe + ScriptedController.exe |
| HumMod standalone **1.6.1** | `hummod_1.6.1` | ✅ engine_smoke passed (Clinic/Hemorrhage, SOL-verified radio toggle, Go 1 Min) |
| **QCP 2005** | `qcp_2005` | ✅ core validated over MCP (navigate View pages, Go with two-phase stop semantics, ICS snapshots); hemorrhage lives on the Clinical-Buttons canvas and is not yet mapped |

Same-lineage builds (the whole 3.x custom family) share the 3.0.4 menu
skeleton and cost **zero code** to add - a thin profile JSON at most.
Heterogeneous engines (1.6.1, QCP) need one profile each. To qualify an
unknown build, run `python tests/discover.py --engine C:\path\to\build`.

## Tests

With an engine running:

```
set HUMMOD_ENGINE_DIR=C:\path\to\engine
python tests\engine_smoke.py --engine C:\path\to\engine --profile hummod_3.0.4
                             # full: attach, binding, menus, radio (SOL-verified), run
python tests\mcp_smoke.py    # MCP-protocol level: tools over stdio
python tests\multi_engine_test.py   # one session across every registered engine
python tests\improvements_test.py   # inspect modes, modal handling, aliases, radio probe
python tests\test_solver.py  # parser unit tests (fixtures included, no engine needed)
```

## Licensing

This project is original code (MIT). Engine EXEs are untouched; model XML files
are GPL-2.0 (editable). Compatible with HumMod's published terms: personal,
educational and research use.

## Citation

If your laboratory or research uses this tool, please cite the repository:

> TaoChnn. *Oh My HumMod* (v0.1.0). MCP server driving HumMod / QCP
> physiology engines via window messages.
> https://github.com/TaoChnn/oh-my-hummod (accessed <date>).

BibTeX:

```bibtex
@misc{ohmyhummod2026,
  author       = {TaoChnn},
  title        = {Oh My HumMod: an MCP server driving HumMod / QCP physiology
                  engines via window messages},
  howpublished = {\url{https://github.com/TaoChnn/oh-my-hummod}},
  year         = {2026},
  note         = {v0.1.0, accessed <date>}
}
```


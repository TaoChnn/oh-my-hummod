# oh-my-hummod

Drive **HumMod / QCP** physiology simulation engines from any MCP client —
window messages only, **no engine source required, no reverse engineering**.
The engine cannot tell these messages from a user's mouse.

Tested with **Claude Code**, **Codex CLI** and **ZCode**.

```
MCP client ──stdio──> oh-my-hummod server ──Win32 messages──> engine EXE
                                └── parses .SOL / .ICS exports (10,000+ variables)
```

**Validated engines:** HumMod Clemmer Salt 3.0.4 ✅ · HumMod-BAT ✅ ·
avphummod (Modular) ✅ · HumMod standalone 1.6.1 ✅ · QCP 2005 ✅ (core)

## One Prompt to Start

Copy this to your local agent (Claude Code / Codex CLI / ZCode, etc.).
It will clone the repo, read the README, ask you for the few things it
cannot detect, then install, register and smoke-test the server.

```text
Please set up the "oh-my-hummod" MCP server for me on this Windows machine.

Repo: https://github.com/TaoChnn/oh-my-hummod.git

First, clone the repo and read its README.md carefully. Follow it, but
ask me before guessing any of the following local details:

1. Engine directory — where is my HumMod / QCP engine folder?
   (e.g. C:\HumMod). If I don't know, help me locate the engine EXE.
2. Engine build — HumMod 3.0.4 / 1.6.1 / HumMod-BAT / avphummod / QCP 2005?
   If unsure, detect it from the EXE name and confirm with me.
3. MCP client — Claude Code, Codex CLI, or ZCode? (so you register it
   in the right config file)
4. Python — should we use a local venv? Use its absolute python.exe
   when registering the server.
5. Export directory — where should .SOL/.ICS exports go?
   (e.g. C:\hummod-exports, must be writable)

Then:
1. Create a venv, `pip install -e .` in the repo.
2. Set HUMMOD_ENGINE_DIR and HUMMOD_OUTDIR.
3. Copy `engines.example.json` to `engines.json` and fill in the folders
   where the engine builds live on THIS machine (`engines.json` is
   git-ignored - it holds local paths and must not be committed).
4. Run `python tests\engine_smoke.py --engine <engine dir> --profile <profile>`
   and confirm it prints ENGINE_SMOKE_OK. If it fails, show me the exact
   command, error output and detected profile before continuing.
5. Register the MCP server with my client using the venv's absolute
   python.exe and the env vars above.
6. Restart the client and verify the hummod tools are listed.
7. Run a read-only check: `hummod_status` and `hummod_engines`.

Rules:
- Do not modify engine binaries or model files.
- Do not run long simulations; a short `hummod_go` or status check is enough.
- Do not click/drag blindly in the engine window.
- If any step is ambiguous, ask me instead of guessing.
- At the end, summarize what you changed and the exact commands you ran.
```

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
```

The profile is auto-detected from the engine EXE in `HUMMOD_ENGINE_DIR`
(`hummod_3.0.4` / `hummod_1.6.1` / `qcp_2005` / `hummod_bat` / `avphummod`).
`tests\discover.py --engine C:\Some\Other\Build` prints everything needed to
add a profile for an unknown build.

## Register with your MCP client

The server is a plain console program over stdio, so every client needs the
same three things: the **command** that starts it, its **arguments**, and the
**environment** it reads.

### Claude Code

```bash
claude mcp add hummod \
  --env HUMMOD_ENGINE_DIR=C:\HumMod \
  --env HUMMOD_OUTDIR=C:\hummod-exports \
  -- python -m oh_my_hummod.server
```

Add `--scope project` (shared via `.mcp.json` in the repo) or `--scope user`
(all projects). The same thing by hand, in `.mcp.json` or `~/.claude.json`:

```json
{
  "mcpServers": {
    "hummod": {
      "command": "python",
      "args": ["-m", "oh_my_hummod.server"],
      "env": {
        "HUMMOD_ENGINE_DIR": "C:\\HumMod",
        "HUMMOD_OUTDIR": "C:\\hummod-exports"
      }
    }
  }
}
```

### Codex CLI

Codex reads `config.toml` in its home directory (`~/.codex/config.toml` on
Windows, `%USERPROFILE%\.codex\config.toml`):

```toml
[mcp_servers.hummod]
command = "python"
args = ["-m", "oh_my_hummod.server"]

[mcp_servers.hummod.env]
HUMMOD_ENGINE_DIR = "C:\\HumMod"
HUMMOD_OUTDIR = "C:\\hummod-exports"
```

or from the CLI:

```bash
codex mcp add hummod --env HUMMOD_ENGINE_DIR=C:\HumMod -- python -m oh_my_hummod.server
```

### ZCode

ZCode keeps MCP servers in `~/.zcode/cli/config.json` under `mcp.servers`:

```json
{
  "mcp": {
    "servers": {
      "hummod": {
        "command": "python",
        "args": ["-m", "oh_my_hummod.server"],
        "env": {
          "HUMMOD_ENGINE_DIR": "C:\\HumMod",
          "HUMMOD_OUTDIR": "C:\\hummod-exports"
        }
      }
    }
  }
}
```

### Notes for all clients

- Use the **absolute path** of the Python that has `oh-my-hummod` installed
  (`where python` / `which python`) if the client's PATH differs from your
  shell's.
- `HUMMOD_PROFILE` may be omitted — the server auto-detects the engine by its
  EXE name.
- After editing the library's source, **restart the MCP server**: clients
  cache both the tool list and the loaded module for the life of a session.
- Some clients cap tool-call duration (commonly 30 s). Long runs
  (`hummod_go` on a week-scale step) can exceed that; `hummod_go` accepts
  `wait=False` to return immediately, then poll with `hummod_busy` and fetch
  results with `hummod_snapshot`.

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
| `menu_aliases` | canonical panel path → build-specific path |
| `page_ids` | panels that have no menu label at all (bitmap toolbars) |
| `quirks` | engine behaviours that change tool behaviour (slider commit, EPO, model noise) |

Adding a new engine version = run `tests/discover.py` against it, note the
differences, drop a JSON in `profiles/`. No code changes.

## Tools

| Area | Tools |
|---|---|
| Engine lifecycle | `hummod_status` `hummod_engines` `hummod_start` `hummod_restart` `hummod_restart_engine` (relaunch the process so model XML is re-read) |
| Discovery | `hummod_inspect` (`mode="menu"/"controls"/"both"`) `hummod_profile` `hummod_probe_radio` (auto-discover radio semantics) |
| Navigation | `hummod_navigate` (panel path) `hummod_menu_command` (menu path or command id) `hummod_view_group` (toggle a toolbar group) `hummod_open_panel` (via the engine's own "find panel" dialog) |
| Running | `hummod_go` (duration, `times=`, `verify=`, `wait=`) `hummod_busy` `hummod_stop_state` |
| Controls | `hummod_radio` `hummod_edit` `hummod_slider` `hummod_action` (`!` triggers) `hummod_button` (captioned buttons) `hummod_click` `hummod_drag` (coordinates) |
| Dialogs | `hummod_dialogs` `hummod_dialog_button` `hummod_modals` `hummod_dismiss_modal` `hummod_popup` `hummod_listbox` |
| Data | `hummod_snapshot` `hummod_get_vars` `hummod_history` (time series) `hummod_shot` (screenshot of the engine window) `hummod_save_ics` / `hummod_load_ics` (initial-condition files) |
| Parameters | `hummod_set_param` (set a model parameter by its physical value) |
| Reporting | `hummod_integrity_statement` (the academic-integrity statement a report must end with) `hummod_verify_integrity` (check a report still carries it) |

Every tool takes an optional `engine=` key, so one server can drive several
engine builds at once (see `engines.json` - copy `engines.example.json` to
create it; it is git-ignored because it holds your local paths);
`hummod_engines` lists them with running state and detected profile.

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
- Sliders can be addressed by ordinal, `ctrl_id` or `label`; pages often mix
  parameter sliders with plain scroll bars, so prefer `label`/`ctrl_id` when
  the page has more than a couple of them.

Errors return one-line JSON; unknown menu paths list the available siblings so
agents can self-correct.

## Manual for AI agents

The server ships its own manual, so an agent does not have to learn the tool
surface by trial and error:

| Channel | What it is | How it reaches the model |
|---|---|---|
| `instructions` | a compact workflow (discover → navigate → set → verify → run → collect) | returned in the MCP handshake; clients may fold it into the system prompt |
| `hummod://guide` | tool-by-tool usage | `resources/read` |
| `hummod://workflow` | a worked protocol (baseline → arm → verify → reset → repeat) | `resources/read` |
| `hummod://quirks` | engine differences and the traps that cost the most time | `resources/read` |
| `hummod://variables` | variable naming across builds | `resources/read` |
| `hummod://integrity` | reporting rules and the academic-integrity statement | `resources/read` |

Resources are the portable channel: every MCP client must support
`resources/read`, whereas `instructions` is optional for clients.

### Reports must end with an integrity statement

Any report or experiment write-up produced with this tool **must end with an
academic-integrity statement**. Call `hummod_integrity_statement` with what
the AI did and what the human did, then append the returned `statement`
verbatim as the last section, with every placeholder filled in:

```text
hummod_integrity_statement(
    ai_contributions=[...],      # what the AI actually did
    human_contributions=[...],   # what the human actually did
    author="...", date="...")
```

The statement separates *execution* from *authorship*: the tool automates
the mechanical parts (setting the same parameter on four arms, running the
same protocol five times, parsing thousands of variables, plotting them),
while experimental design, parameter choice, judging whether the numbers
make sense, and the interpretation stay with the human. It also states
plainly that using this tool to have AI do an entire assignment is **not
endorsed** - engine output contains model defects, not just physiology, and
telling those apart from real findings needs domain knowledge the tool does
not have.

### If the statement is removed, the agent must pause

A statement can disappear from a report after it was written - the user may
delete it, or a later rewrite may drop it. Whenever an agent is asked to
keep working on a report, it calls `hummod_verify_integrity(report_path=...)`
first. If the result is not `ok` (`missing`, `not_at_end`, or an unfilled
placeholder), the agent must **pause**: it does not continue the request,
does not run more experiments for that report, and does not silently
re-insert the text - it tells the user the statement is required, offers to
restore it, and waits. Silently re-adding it would hide the removal, which
is the opposite of what the statement is for.

`hummod://integrity` has the full wording, plus a note on what to do if
your course mandates its own AI disclosure form.

### Calling convention

Drive the engine **one tool call at a time and read each result before
deciding the next step**. That is what separates a working run from a
plausible-looking wrong one — a slider position that looks right on screen
may not have reached the model, and a radio whose state cannot be read back
may still be selected.

A script is fine for repeating a protocol you have already verified step by
step, but do not pre-write a batch of steps you have not probed, and do not
bypass this server to drive the engine directly.

### The traps worth knowing before your first run

- **Same EXE, different engine.** HumMod-BAT and Clemmer Salt 3.0.4 ship a
  byte-identical `HumMod.EXE`; all their differences are in the model XML.
  Menu-based detection cannot tell them apart — the profile has to be pinned
  per engine key (`engines.json` accepts `{"dir": ..., "profile": ...}`; use
  `engines.example.json` as the starting point).
- **"Finished" is engine-specific.** On HumMod the Stop menu is *enabled*
  while solving, so it is not a completion signal; the status bar is. On
  QCP it is the two-phase Stop behaviour. `hummod_go` already decides this
  correctly — do not second-guess it from the menu.
- **Verify every setting at model level.** Switch state often lives in the
  model rather than in the Win32 control, so the control cannot be read
  back. Pass `probe_vars=[...]` to `hummod_radio` / `hummod_slider` and read
  the model instead.
- **Sliders differ per build and per control.** Some commit linearly, some
  ignore position 0, some never commit at all. Set, then read back.
- **QCP must be started visible** (`hummod_start(key="qcp", hidden=False)`);
  a hidden start exits within seconds.
- **QCP exports state only** (`.ICS`, ~1367 variables): no time series, no
  derived values. Snapshot point by point.

`hummod://quirks` has the full list, measured rather than quoted.

## Validated profiles

| Engine build | Profile | Status |
|---|---|---|
| HumMod Clemmer Salt **3.0.4** | `hummod_3.0.4` | ✅ full protocol end-to-end (hemorrhage 4.3.1, five time points, SOL-verified) |
| **HumMod-BAT** (2018 custom build) | `hummod_bat` | ✅ engine_smoke passed - menu skeleton identical to 3.0.4, profile reuses it |
| **avphummod** (Modular AVP build) | `avphummod` | ✅ engine_smoke passed - same lineage; ships Model Solver.exe + ScriptedController.exe |
| HumMod standalone **1.6.1** | `hummod_1.6.1` | ✅ engine_smoke passed (Clinic/Hemorrhage, SOL-verified radio toggle, Go 1 Min) |
| **QCP 2005** | `qcp_2005` | ✅ core validated over MCP (canvas panels via command ids, View groups, ICS snapshots); no SOL export (QCP has none) and no time series - snapshot each point instead |

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
python tests\guide_test.py   # the manual is reachable: instructions + resources
python tests\integrity_test.py  # the integrity statement tool behaves as specified
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

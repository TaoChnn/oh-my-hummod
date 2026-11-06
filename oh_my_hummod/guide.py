"""Public manual for the oh-my-hummod MCP server.

Three layers, each with a different delivery mechanism:

  instructions   short, always-on text returned in the MCP handshake
                 (InitializeResult.instructions). Clients MAY fold it into
                 the system prompt; the wording therefore stays compact.
  resources      long-form guides the model pulls on demand via
                 resources/read (hummod://guide, hummod://quirks,
                 hummod://workflow). The protocol requires every client to
                 support them, so this is the portable channel.
  README.md      the human-readable manual on GitHub.

The content is deliberately public: it teaches how to drive the engines
reproducibly, not how to bypass the MCP layer.
"""
from __future__ import annotations

INSTRUCTIONS = """\
oh-my-hummod drives HumMod / QCP physiology simulation engines (Windows, GUI
only) through OS window messages, and parses the engines' own .SOL / .ICS
exports. No engine source, no reverse engineering.

WORKFLOW (follow it in this order):
1. hummod_engines / hummod_status  - which engines are registered and running.
2. hummod_start(key=...)            - launch one; QCP must start VISIBLE
                                    (hidden=False), it exits if hidden.
3. hummod_inspect(mode="menu")     - learn the live menu tree; panel paths
   hummod_inspect(mode="controls")  - and the widgets of the current page.
   Do NOT guess ids: they differ per engine build.
4. hummod_navigate(panel_path=...)  - switch page (label path, not ids).
5. Set values, then VERIFY by reading the model back:
   hummod_slider / hummod_radio / hummod_edit / hummod_set_param, each with
   probe_vars=[...] so the effect is confirmed at model level.
6. hummod_go(duration_label=...)    - run. Long runs: wait=False, then poll
   hummod_busy and read results with hummod_snapshot.
7. hummod_snapshot / hummod_history - the data (SOL has full time series;
   QCP .ICS has state only, no series, and no derived values).

ENGINE-SPECIFIC FACTS live in the profiles, not in this message. Two that
catch everyone: engine quirks differ per build (slider commit behaviour,
how "the run finished" is signalled, which radio ordinal means On), and
several builds are the SAME executable with different model XML, so the
profile must be pinned per engine key. Read hummod://quirks before your
first run on an unfamiliar build.

CALLING CONVENTION: drive the engine one tool call at a time and read each
result before deciding the next step - that is what makes the difference
between a working run and a plausible-looking wrong one. A script is fine
for repeating a protocol that you have already verified step by step, but
do not pre-write a batch of steps you have not probed, and do not bypass
this server to drive the engine directly.

Long-form guides are available as resources: hummod://guide (tool-by-tool
usage), hummod://workflow (a worked protocol), hummod://quirks (engine
differences and known traps), hummod://variables (variable naming across
builds). Read them when you need detail.
"""

WORKFLOW = """\
# A worked protocol: dose-response with three arms

This is the shape most experiments take. Adapt the paths and variables to
your engine build - discover them, do not copy them blindly.

## 0. One-off discovery (do this once per build)

    hummod_engines
      -> registry keys and their detected profiles
    hummod_start(key="3.0.4")
      -> {"ok": true, "pid": ..., "profile": "hummod_3.0.4"}
         (QCP: hummod_start(key="qcp", hidden=False))

    hummod_inspect(mode="menu")
      -> the whole live menu tree with command ids and full paths
         READ THIS: it tells you which panel paths exist in this build

## 1. Baseline

    hummod_navigate(panel_path="Trauma/Hemorrhage")
    hummod_snapshot(name="t0_baseline", vars=["BloodVol.Vol", "System.X"])

The snapshot always includes the model clock (System.X on HumMod, X on
QCP), so every snapshot tells you the model time it was taken at.

## 2. Set a parameter, then read the model back

    hummod_slider(panel_path="Trauma/Hemorrhage", ordinal=0, pos=3,
                  probe_vars=["Hemorrhage.Volume"])
    hummod_radio(panel_path="Trauma/Hemorrhage", value="On",
                 probe_vars=["Hemorrhage.Switch"])

probe_vars is the important part: several engines keep switch state in the
model, not in the Win32 control, so the control cannot be read back. The
probe reads the model instead. If the probed variable did not change, the
setting did not take - re-check the ordinal (hummod_inspect(mode="controls")
lists radios and sliders with their control ids) before retrying.

## 3. Run, and wait correctly

    hummod_go(duration_label="1 Min", verify=True)

verify=True reads the clock before and after, which proves the run really
advanced. For a run longer than the client's request timeout (~30 s):

    hummod_go(duration_label="1 Day", wait=False)
    hummod_busy          -> {"busy": true, ...} until it finishes
    hummod_snapshot(name="t1_day", vars=[...])

Do not treat a grayed Stop menu as "finished" on HumMod: during solving the
Stop item is ENABLED there. The server decides completion from the status
bar text ("Solving ... Done"); on QCP it is the two-phase Stop behaviour.
Trust hummod_go's own verdict rather than your own reading of the menu.

## 4. Repeat the arm, then repeat the protocol

For the next arm: reset the parameters you changed, then Restart the model
(hummod_restart), then re-apply the arm's settings. Verify the reset
actually happened with a probe before applying the next arm - a leftover
switch from the previous arm is the classic silent error.

## 5. Collect and check

    hummod_snapshot(name="arm2_day1", vars=[...])
    hummod_history(sol_path=".../arm2_day1.SOL", vars=["BloodVol.Vol"])

hummod_history returns a plot-ready time series from a HumMod .SOL file.
QCP has no time series: snapshot each point instead.

Also compare against the previous run: engines differ in how much
randomness they inject, so a 2-3 % drift between two identical runs is
normal for HumMod 3.x and means "no change" for most variables.
"""

QUIRKS = """\
# Engine differences and known traps

Everything here was measured, not read from a manual. The authoritative
copy lives in the profile JSONs (oh_my_hummod/profiles/*.json); this
resource is the human-readable digest.

## The same EXE can be different engines

HumMod-BAT and Clemmer Salt 3.0.4 ship the *byte-identical* HumMod.EXE
(same md5); all their differences are in the model XML under Structure/.
Menu-based detection therefore CANNOT tell them apart - the profile has to
be pinned per engine key. If hummod_status reports hummod_3.0.4 for a BAT
folder, the registry entry is missing its pinned profile.

## How a run is finished

- HumMod 3.x: the Stop menu item is ENABLED while solving, so it is not a
  completion signal. Use the status bar ("Solving ... Done"). The server
  does this for you; a manual "is Stop grey?" check gives wrong answers.
- QCP 2005: two-phase - Stop becomes enabled when the run starts, greys
  out when it finishes. There is no status-bar text.

## Sliders commit differently, per build AND per control

- Set a slider, then read the model value back. A thumb position that
  looks right on screen does not mean the model took it.
- QCP ignores SB_THUMBPOSITION with position 0; the server falls back to
  repeated line-scrolls for that case.
- HumMod 3.0.4 maplist sliders commit every index through SB_THUMBPOSITION
  but ignore line-scrolls entirely.
- HumMod 1.6.1 scrollbars only honour position/tracking messages.
- Some controls never commit at all (for example a treadmill grade slider
  on some builds). Those need the model XML, or another control.
- Profiles may carry a measured index->value table (slider_value_lists);
  hummod_set_param / hummod_slider(value=...) then set a parameter by its
  physical value instead of by thumb index.

## Switch state often lives in the model, not in the control

radio / checkbox check state is frequently not readable (check_readable
false or null). That does NOT mean "not selected". Use probe_vars to read
the model variable instead. hummod_probe_radio presses each radio in turn
and probes a variable - it discovers which ordinal means On.

## Event dialogs block everything

Some builds pop an application-level modal (for example "ECG shows S-T
segment shift") whenever a parameter changes. While it is open the main
window is disabled and every command fails. The server dismisses them
automatically before the next command; if something still fails, look for
a dialog with hummod_modals / hummod_dialogs and dismiss it explicitly.
Note that yes/no dialogs use button ids 6 (Yes) and 7 (No), not OK/Cancel.

## QCP specifics

- Must be started VISIBLE. A hidden start exits within seconds.
- Exports .ICS (state only, about 1367 variables) - no .SOL, no time
  series, no derived values (blood pressure, hormone concentrations and
  similar have to be read off the canvas).
- Canvas panels have no widget text at all: locate them by name or by
  command id, and read values from a screenshot (hummod_shot).
- Its ICS clock variable is "X", HumMod's is "System.X".
- It is deterministic - identical inputs give identical outputs, which
  makes it a clean control for cross-build comparisons.

## Model quirks that look like bugs in your experiment

- HumMod 3.0.4 does not compute EPO (the pool exists but is not coupled
  to red-cell production). Month-scale blood-loss experiments will show no
  red-cell recovery because of that, not because of your settings.
- HumMod 3.x injects up to ~2.75 % random noise; 1.6.1 and QCP are
  deterministic.
- 1.6.1 has no hypoxia->sympathetic pathway, so pneumothorax-like models
  show no tachycardia or pressor response there.
- 1.6.1's "To Next Week/Month" is relative (it advances to the next
  multiple of the target), so confirm where it landed via the clock.
- After cardiac arrest the arithmetic can break (pH above 10) and the
  heart rate can freeze. Treat post-arrest readings as void; use boolean
  state flags instead.
- Restart returns the model to its defaults, not to a saved initial
  condition. Use hummod_load_ics to restore a scenario.
"""

VARIABLES = """\
# Variable naming across builds

Names are NOT portable between builds. The two families you will meet:

- HumMod 3.x / 1.6.1 / AVP style: dotted paths, e.g.
  BloodVol.Vol, SystemicArtys.Pressure, SANode-Rate.Rate,
  PO2Artys.Pressure, LacPool.[Lac-(mEq/L)], Brain-Flow.BloodFlow,
  ReninPool.[PRA], MineralocorticoidReceptor.[Aldo(nG/dL)-Plasma]
- QCP 2005: mostly flat names with spaces, e.g.
  "Posture Control, Is Standing", and the model clock is simply "X".

Known renames that break copy-paste between builds:

  heart rate      3.x: SANode-Rate.Rate        1.6.1: Heart-Rate.Rate
  blood pH        3.x: BloodPhValues.ArtysPh  1.6.1: BloodPh.ArtysPh
  sympathetic     3.x: Ganglia-Sympathetic.level
                  1.6.1: GangliaGeneral.NA(Hz)
  alveolar PO2    3.x: LungO2.PAlveolar        1.6.1: Lung_O2.pO2

Watch out for case-only twins: some builds expose both
"Ganglia-Sympathetic.Level" and ".level"; a case-insensitive lookup can
pick the wrong one.

Sentinel values: variables in the BloodChemistry-Sample.* family are
reported as 1e+305 / 1e+306 / 1e+308 when the engine did not sample
them. They are not measurements - find the real value under a different
group name (A2Pool..., BloodPhValues..., ...).

How to find the right name for your build: export a full snapshot
(hummod_snapshot without vars) and search the file. hummod_get_vars
accepts a list and reports what it could not find under "missing", which
makes name discovery a quick loop:

    hummod_get_vars(sol_path=".../t0.SOL", names=["BloodVol.Vol", "X"])

The "missing" list is the fastest way to discover the real names.
"""

RESOURCES = {
    "hummod://guide": (
        "Tool-by-tool usage guide",
        """# Tool guide

Every tool takes an optional engine=<key> so one server can drive several
engine builds; the key comes from hummod_engines.

## Lifecycle
    hummod_engines                list registered engines, running state, profile
    hummod_status(engine=)         one engine: pid, profile, dir
    hummod_start(key=, hidden=)   launch an engine; QCP needs hidden=False
    hummod_restart(engine=)        reset the model to defaults (in memory)
    hummod_restart_engine(engine=) relaunch the PROCESS, so model XML is re-read
                                  (use after editing model files)

## Discovery - do this before guessing anything
    hummod_inspect(mode="menu"|"controls"|"both", panel_path=)
        mode="menu"     the live menu tree with command ids and paths
        mode="controls" the widgets of the current page (radios, sliders,
                        edits, buttons) with control ids
    hummod_profile(engine=)        the active profile: quirks, radio semantics,
                        page ids, slider maps
    hummod_probe_radio(panel_path=, probe_vars=)
        press each radio in turn and probe a model variable - discovers
        which ordinal means On

## Navigation
    hummod_navigate(panel_path= | menu_id=)
    hummod_menu_command(item_path= | menu_id=)   any menu entry
    hummod_view_group(group=, want=)             toggle a toolbar group
    hummod_open_panel(variable=)                  the engine's own "find panel"

## Running
    hummod_go(duration_label=, times=, verify=, wait=)
        times   repeat the step (no "30 Sec" entry exists: times=3 of "10 Sec")
        verify  read the model clock before/after to prove the run advanced
        wait=False returns immediately; poll with hummod_busy
    hummod_busy(engine=)          is a run in progress
    hummod_stop_state(engine=)    stop-menu state (an engine-specific signal)

## Setting values
    hummod_radio(panel_path=, value="On"|"Off" | ordinal=, probe_vars=[])
    hummod_slider(panel_path=, ordinal= | ctrl_id= | label= | value=, pos=,
                  probe_vars=[])
    hummod_set_param(panel_path=, name=, value=, probe_vars=[])
        set a model parameter by its physical value (needs a profile table)
    hummod_edit(panel_path=, ctrl_id= | label=, text=)
    hummod_action(panel_path=, action=)     press a named button ("Shock Now")
    hummod_button(panel_path=, caption=)    press a captioned button
    hummod_click(x=, y=) / hummod_drag(x1=,y1=,x2=,y2=)
        window-relative coordinates, for canvas-drawn widgets

## Data
    hummod_snapshot(name=, vars=[])   export state + parse the named variables
    hummod_get_vars(sol_path=, names=[])
    hummod_history(sol_path=, vars=[], max_points=)
        time series from a HumMod .SOL file (QCP has none)
    hummod_shot(name=)                PNG of the engine window
    hummod_save_ics(name=) / hummod_load_ics(path=)
        initial-condition files (a saved scenario)

## Dialogs
    hummod_modals / hummod_dialogs / hummod_dialog_button / hummod_dismiss_modal
    hummod_popup / hummod_listbox

Conventions worth remembering:
- Panel paths are resolved by label, with per-build aliases from the profile.
- The clock is always included in a snapshot, so you always know the time.
- Requested names that do not exist come back under "missing" - that list is
  your discovery feedback loop, not an error.
- Errors are one-line JSON and usually list the available alternatives.
""",
    ),
    "hummod://workflow": ("Worked protocol", WORKFLOW),
    "hummod://quirks": ("Engine differences and known traps", QUIRKS),
    "hummod://variables": ("Variable naming across builds", VARIABLES),
}

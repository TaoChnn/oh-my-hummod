# Tests

Three groups, three audiences.

```
tests/
  test_solver.py        unit tests for the SOL/ICS parsers (no engine needed)
  engine_smoke.py       the main check: drives a live engine through a profile
  discover.py           tool for an engine build you have not used before
  mcp_smoke.py          MCP-protocol smoke (stdio) for a HumMod build
  mcp_smoke_qcp.py      the same for QCP 2005
  multi_engine_test.py  one session across every registered engine
  mcp_oneshot_client.py helper: starts a fresh server per tool call
  fixtures/             sample exports for the parser tests
  regression/           one file per bug that was found and fixed
  probes/               development-time investigation scripts
```

## What to run

The deterministic suite is safe to collect with pytest:

```bat
python -m pytest -q
```

Field-trial scripts are protected by `if __name__ == "__main__"` and are not
executed during pytest collection. Run those scripts directly only with the
engine copy and MCP client environment they require.

If you just want to know whether the tool works on your machine:

```bat
set HUMMOD_ENGINE_DIR=C:\path\to\your\engine
python tests\engine_smoke.py --engine C:\path\to\your\engine --profile hummod_3.0.4
```

Expect `ENGINE_SMOKE_OK`. This one covers attach, model binding, the menu
tree, a radio (verified against the model), and a short run.

Without an engine you can still check the parser and the deterministic server
helpers:

```bat
python -m pytest -q               :: deterministic tests passed
```

`guide_test.py` and `integrity_test.py` exercise the MCP stdio subprocess and
must be run directly; their result depends on the local MCP client/runtime.

## regression/

Each file guards one defect that a field trial actually hit. They are kept
because the defect is easy to reintroduce - most of them were found by an
agent, fixed, and then had to be *proved* fixed.

| File | What it guards |
|---|---|
| `asphyxia_tools_test.py` | the tool fixes found during the asphyxia run (4.3.15) |
| `bat_profile_test.py` | per-engine profile pinning + string-typed parameters |
| `fixes_test.py` | slider addressing by ctrl_id/label, model clock in snapshots, run-completion fallback |
| `guide_test.py` | the manual is reachable: instructions in the handshake, resources readable |
| `improvements_test.py` | inspect modes, modal handling, panel aliases, radio probing |
| `integrity_test.py` | the integrity statement tool and the removal detection |
| `mcp_ics_load_test.py` | loading a saved scenario into a running engine |
| `mcp_ics_test.py` | the .ICS save/load chain (save -> restart -> load) |
| `mcp_smoke_action.py` | `hummod_action` actually fires (defibrillation) |
| `mcp_smoke_lax_args.py` | the tools tolerate stringly-typed and `{"item": [...]}` arguments |
| `mcp_smoke_qcp_canvas.py` | the canvas tools (shot / popup / click / drag) |
| `mcp_smoke_qcp_fixes.py` | the R3 QCP fixes (start alias, view-group reporting) |
| `modal_dismiss_test.py` | event dialogs are dismissed instead of blocking everything |
| `slider_pos0_304_test.py` | position 0 commits on HumMod 3.0.4 maplist sliders |
| `slider_regression_304_test.py` | the 3.0.4 path after `hummod_slider` gained `value=` |
| `slider_value_avp_test.py` | setting a model parameter by value on AVP |
| `test_ics_roundtrip.py` | the QCP file-dialog filename-edit id |
| `test_profile_detection.py` | profile detection (the 1.6.1 build was misdetected as 3.0.4) |

Most need a live engine. **Always point them at a copy**, never at the
engine another session is using:

```bat
cp -r C:\path\to\engine C:\path\to\engine_test_copies\mine
set HUMMOD_ENGINE_DIR=C:\path\to\engine_test_copies\mine
python tests\regression\slider_pos0_304_test.py
```

## probes/

Investigation scripts written while a behaviour was still unexplained. They
answer questions like "why did the Shock Now click not register?" and "what
is the exact scroll-position to value map of that stepper?". Several of
them produced the facts now stored in the profile JSONs.

**You normally do not need these.** They are kept as evidence for the
behaviour recorded in the profiles, and as a starting point when a new
engine build behaves unexpectedly. They expect an engine folder and print
whatever they find; there is no pass/fail contract.

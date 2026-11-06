# Probes

Development-time investigation scripts. They were written to answer a
specific question about an engine's behaviour - "does this stepper commit?",
"why did that click not register?", "what is the real slider scale?" - and
they print whatever they find rather than asserting a pass/fail contract.

**A normal user does not need these.** They are kept because several of
them produced the facts that are now encoded in `oh_my_hummod/profiles/*.json`
(slider scales, radio semantics, dialog control ids), and because they are
the fastest way to investigate a build you have not used before.

Most of them talk to the engine directly through the bridge rather than
through MCP - they were written to answer questions about the *engine*, not
to exercise the MCP layer.

| Script | Question it was written to answer |
|---|---|
| `probe_menu.py` | what does the menu tree of this build look like? |
| `probe_161.py` | what controls does HumMod 1.6.1 expose? |
| `probe_modal.py` | what exactly is the 1.6.1 event modal (class, buttons, text)? |
| `probe_cpr.py` | which radio ordinals and action buttons sit on the CPR / VF pages? |
| `probe_cpr2.py` | why did the Shock Now click not register? |
| `probe_cpr3.py` | what does the VF page look like (screenshot)? |
| `probe_qcp.py` | enumerate the windows of an unknown engine EXE |
| `probe_qcp2.py` | what does the QCP canvas look like from the bridge's point of view? |
| `probe_qcp3.py` | how do QCP's canvas sliders behave? |
| `probe_avp_diet_stepper.py` | does the AVP Lifestyle/Diet/Goal stepper commit a model value? |
| `probe_avp_diet_stepper2.py` | which message sequence makes it commit? |
| `probe_avp_value_maps.py` | what is the exact scroll-index to model-value map of the AVP steppers? |
| `smoke.py` | quick bridge-level sanity check of a profile against a live engine |

Typical use - give them an engine folder:

```bat
set HUMMOD_ENGINE_DIR=C:\path\to\engine
python tests\probes\probe_menu.py
```

Point them at a **copy** if the engine may be in use by another session.

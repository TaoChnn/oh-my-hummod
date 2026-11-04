# Regression test for the tool fixes found during the asphyxia experiment (4.3.15).
#
# Covered:
#   1. radio check-state readback  (BM_GETCHECK was 0x00F1 = BM_SETCHECK -> it wrote)
#   2. model-level radio verification via probe_vars
#   3. labelled panel buttons      (hummod_button - "Neurological Signs")
#   4. Go with times/verify        (30 s = 3 x "10 Sec"; sim clock must advance)
#   5. hummod_busy                 (is the engine still solving?)
#   6. hummod_restart_engine       (edited model XML only reloads on a new process)
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "oh_my_hummod", "server.py")
PANEL = "Respiration/Respiratory Center/Integration"


async def main():
    env = dict(os.environ)
    env.setdefault("HUMMOD_ENGINE_DIR", r"C:/path/to/engine")
    env.setdefault("HUMMOD_OUTDIR", r"C:/path/to/out\asphyxia_tools")
    os.makedirs(env["HUMMOD_OUTDIR"], exist_ok=True)
    async with stdio_client(StdioServerParameters(command=sys.executable, args=[SERVER], env=env)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                return " | ".join(c.text for c in res.content if getattr(c, "text", None))

            fails = []

            def check(label, cond, detail=""):
                print(("  OK   " if cond else "  FAIL ") + label + ("  " + detail if detail else ""))
                if not cond:
                    fails.append(label)

            print("[1] radio check state")
            print("     ", (await call("hummod_inspect", {"mode": "controls", "panel_path": PANEL}))[:600])
            out = await call("hummod_radio", {"panel_path": PANEL, "ordinal": 1, "expected": 2,
                                             "probe_vars": ["RespiratoryCenter-Integration.TotalDrive",
                                                            "RespiratoryCenter-Output.Rate"]})
            print("     ", out)
            check("radio press reports the model effect",
                  'TotalDrive": 0.0' in out and 'Rate": 0.0' in out, out[-200:])

            print("[2] labelled button")
            out = await call("hummod_button", {"panel_path": "Diagnosis/Evaluation",
                                               "caption": "Neurological Signs"})
            print("     ", out)
            check("button clicked", '"ok": true' in out.lower(), out[:160])

            print("[3] go times + verify")
            await call("hummod_restart")
            out = await call("hummod_go", {"duration_label": "10 Sec", "times": 3, "verify": True})
            print("     ", out)
            check("30 s of model time elapsed",
                  '"sim_minutes_advanced": 0.5' in out or '"sim_minutes_advanced":0.5' in out, out[-200:])

            print("[4] busy probe")
            print("     ", await call("hummod_busy"))

            print("[5] restart_engine (process relaunch -> model XML reload)")
            out = await call("hummod_restart_engine", {"engine": "t304"})
            print("     ", out)
            check("engine process relaunched", '"ok": true' in out.lower(), out[:200])
            out = await call("hummod_snapshot", {"name": "asphyxia_tools_after_restart",
                                                 "engine": "t304",
                                                 "vars": ["System.X", "RespiratoryCenter-Integration.TotalDrive"]})
            print("     ", out)
            check("fresh process has a bound model at t=0",
                  '"System.X": 0.0' in out, out[-200:])

            print("[6] restore: clamp off + restart")
            await call("hummod_radio", {"panel_path": PANEL, "ordinal": 0, "expected": 2})
            await call("hummod_restart")
            out = await call("hummod_snapshot", {"name": "asphyxia_tools_final",
                                                 "vars": ["System.X", "RespiratoryCenter-Integration.TotalDrive"]})
            print("     ", out)
            check("model back at t=0 with drive restored",
                  '"System.X": 0.0' in out and "0.96" in out, out[-200:])

            print("ASPHYXIA_TOOLS_OK" if not fails else f"ASPHYXIA_TOOLS_FAIL: {fails}")
            failed = bool(fails)

    sys.exit(1 if failed else 0)


asyncio.run(main())

# Regression test for the tool fixes found during the HumMod-BAT asphyxia run (4.3.15, R3).
#
# Covered:
#   1. per-engine profile pinning - HumMod-BAT and Clemmer Salt 3.0.4 ship the SAME
#      HumMod.EXE and neither has a VERSION file, so menu-based detection cannot tell
#      them apart and always answered "hummod_3.0.4" for the BAT engine. engines.json
#      now accepts {"dir": ..., "profile": ...}.
#   2. string-typed alternatives for parameters an MCP client may be unable to type
#      as JSON (arrays / numbers / booleans): vars_csv, names_csv, probe_vars_csv,
#      times_str, verify_str.
#
# Run against a COPY of the engine so no shared engine process is touched:
#   HUMMOD_ENGINE_DIR=C:/path/to\engine_test_copies\r3_bat python tests\bat_profile_test.py
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "oh_my_hummod", "server.py")
PANEL = "Respiration/Respiratory Center/Integration"


async def main() -> None:
    engine_dir = os.environ.get("HUMMOD_ENGINE_DIR", r"C:/path/to\engine_test_copies\r3_bat")
    env = dict(os.environ)
    env["HUMMOD_ENGINE_DIR"] = engine_dir
    env["HUMMOD_OUTDIR"] = os.environ.get("HUMMOD_OUTDIR", r"C:/path/to/out\bat_profile_test")
    # register the copy under a named key with the profile pinned
    env["HUMMOD_ENGINES"] = json.dumps({"bat": {"dir": engine_dir, "profile": "hummod_bat"}})
    os.makedirs(env["HUMMOD_OUTDIR"], exist_ok=True)

    fails = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        print(("  OK   " if cond else "  FAIL ") + label + ("  " + detail if detail else ""))
        if not cond:
            fails.append(label)

    async with stdio_client(StdioServerParameters(command=sys.executable, args=[SERVER], env=env)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                return " | ".join(c.text for c in res.content if getattr(c, "text", None))

            print("[1] pinned profile")
            out = await call("hummod_start", {"key": "bat"})
            print("     ", out)
            check("start reports the pinned profile", '"profile": "hummod_bat"' in out, out[:200])
            out = await call("hummod_status", {"engine": "bat"})
            print("     ", out)
            check("status reports the pinned profile", '"profile": "hummod_bat"' in out, out[:200])

            print("[2] string-typed list parameter (vars_csv)")
            out = await call("hummod_snapshot", {"name": "bat_profile_test", "engine": "bat",
                                                 "vars_csv": "System.X,RespiratoryCenter-Integration.TotalDrive,"
                                                             "SANode-Rate.Rate"})
            print("     ", out)
            check("vars_csv returns the named variables",
                  '"System.X"' in out and '"SANode-Rate.Rate"' in out, out[:220])

            print("[3] string-typed list parameter (probe_vars_csv)")
            out = await call("hummod_radio", {"panel_path": PANEL, "ordinal": 1, "expected": 2,
                                             "engine": "bat",
                                             "probe_vars_csv": "RespiratoryCenter-Integration.TotalDrive,"
                                                               "RespiratoryCenter-Output.Rate"})
            print("     ", out)
            check("probe_vars_csv reads the model back",
                  'TotalDrive": 0.0' in out and 'Rate": 0.0' in out, out[-220:])

            print("[4] string-typed scalar parameters (times_str / verify_str)")
            await call("hummod_restart", {"engine": "bat"})
            out = await call("hummod_go", {"duration_label": "10 Sec", "engine": "bat",
                                           "times_str": "3", "verify_str": "true"})
            print("     ", out)
            check("times_str repeats the Go step", '"times": 3' in out, out[:200])
            check("verify_str proves the clock moved",
                  '"sim_minutes_advanced": 0.5' in out, out[-200:])

            print("[5] restore")
            await call("hummod_radio", {"panel_path": PANEL, "ordinal": 0, "engine": "bat"})
            await call("hummod_restart", {"engine": "bat"})

    if fails:
        print("BAT_PROFILE_TEST_FAILED:", fails)
        raise SystemExit(1)
    print("BAT_PROFILE_TEST_OK")


asyncio.run(main())

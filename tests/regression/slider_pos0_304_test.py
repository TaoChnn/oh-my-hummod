# Regression test for B-fix: slider pos 0 must commit on HumMod 3.0.4 maplist sliders.
#
# Reproduces the 2026-11-05 R3 pericardial tamponade blocker: on
# Trauma/Pericardium/Pericardial Hemorrhage the Extreme (index 4) move commits
# via SB_THUMBPOSITION but returning to None (index 0) silently failed, because
# Bridge.set_slider replaced THUMBPOSITION(0) with an SB_LINELEFT burst - and
# 3.0.4 ignores SB_LINELEFT on maplist sliders. The fix sends THUMBPOSITION for
# every index and keeps the LINELEFT burst only as the QCP fallback.
#
# Runs against an ISOLATED engine copy (never the live session engine):
#   cp -r C:/path/to/engine C:/path/to\engine_test_copies\r3_304
#   HUMMOD_ENGINE_DIR=C:/path/to\engine_test_copies\r3_304 python tests\slider_pos0_304_test.py
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

PANEL = "Trauma/Pericardium/Pericardial Hemorrhage"
VARS = ["Pericardium-Hemorrhage.Conductance", "Pericardium-Hemorrhage.Switch"]


async def main() -> int:
    engine_dir = os.environ.get("HUMMOD_ENGINE_DIR", r"C:/path/to\engine_test_copies\r3_304")
    outdir = os.path.join(REPO, "_slider_pos0_out")
    env = {
        "HUMMOD_ENGINE_DIR": engine_dir,
        "HUMMOD_OUTDIR": outdir,
    }
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "oh_my_hummod.server"], cwd=REPO, env=env,
    )
    ok = True
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                texts = [c.text for c in res.content if getattr(c, "text", None)]
                return json.loads(texts[0]) if texts else None

            await call("hummod_start")
            await call("hummod_restart")
            await call("hummod_navigate", {"panel_path": PANEL})

            # 1. Extreme (index 4) -> 0.10 must commit (worked before the fix).
            await call("hummod_slider", {"panel_path": PANEL, "ordinal": 0, "pos": 4})
            v4 = (await call("hummod_snapshot", {"name": "s0_extreme", "vars": VARS}))["values"]
            c4 = v4["Pericardium-Hemorrhage.Conductance"]
            print(f"pos4 -> Conductance={c4}")
            ok &= abs(c4 - 0.10) < 1e-9

            # 2. Mild (index 1) -> 0.01 (intermediate step, committed pre-fix too).
            await call("hummod_slider", {"panel_path": PANEL, "ordinal": 0, "pos": 1})
            v1 = (await call("hummod_snapshot", {"name": "s0_mild", "vars": VARS}))["values"]
            c1 = v1["Pericardium-Hemorrhage.Conductance"]
            print(f"pos1 -> Conductance={c1}")
            ok &= abs(c1 - 0.01) < 1e-9

            # 3. THE FIX: None (index 0) -> 0.00. Pre-fix this silently failed
            #    (4 attempts: direct, retry, 1->0 path, canvas drag).
            await call("hummod_slider", {"panel_path": PANEL, "ordinal": 0, "pos": 0})
            v0 = (await call("hummod_snapshot", {"name": "s0_none", "vars": VARS}))["values"]
            c0 = v0["Pericardium-Hemorrhage.Conductance"]
            print(f"pos0 -> Conductance={c0}")
            ok &= abs(c0) < 1e-9

            # 4. Re-raise to Extreme so the fix is proven idempotent both ways.
            await call("hummod_slider", {"panel_path": PANEL, "ordinal": 0, "pos": 4})
            vr = (await call("hummod_snapshot", {"name": "s0_again", "vars": VARS}))["values"]
            print(f"pos4 again -> Conductance={vr['Pericardium-Hemorrhage.Conductance']}")
            ok &= abs(vr["Pericardium-Hemorrhage.Conductance"] - 0.10) < 1e-9

    print("SLIDER_POS0_TEST_" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

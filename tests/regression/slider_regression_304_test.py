# Regression guard for the 3.0.4 path after the hummod_slider signature change
# (new optional `value=` argument).  Runs against an ISOLATED copy so the live
# 3.0.4 engine other sessions may be using is never touched.
#
#   cp -r C:/path/to/engine C:/path/to\engine_test_copies\r3_304
#   HUMMOD_ENGINE_DIR=C:/path/to\engine_test_copies\r3_304 \
#       python tests\slider_regression_304_test.py
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


async def main() -> int:
    engine_dir = os.environ.get("HUMMOD_ENGINE_DIR", r"C:/path/to\engine_test_copies\r3_304")
    env = {
        "HUMMOD_ENGINE_DIR": engine_dir,
        "HUMMOD_OUTDIR": os.path.join(REPO, "_slider_regression_out"),
        "HUMMOD_PROFILE": "hummod_3.0.4",
        "PATH": os.environ.get("PATH", ""),
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
                return json.loads(texts[0]) if texts else {}

            await call("hummod_start")
            await call("hummod_restart")

            # radio + snapshot + slider by ordinal (classic 3.0.4 behaviour)
            out = await call("hummod_radio", {"panel_path": "Trauma/Hemorrhage",
                                              "value": "On", "expected": 8})
            print("radio On ->", out)
            ok &= out.get("ok") is True
            out = await call("hummod_snapshot", {"name": "reg_sw",
                                                 "vars": ["Hemorrhage.Switch"]})
            print("snapshot ->", out.get("values"))
            ok &= out.get("values", {}).get("Hemorrhage.Switch") == 1.0

            out = await call("hummod_slider", {"panel_path": "Trauma/Hemorrhage",
                                               "ordinal": "0", "pos": "3"})
            print("slider ordinal0 pos3 ->", out)
            ok &= out.get("ok") is True and out.get("pos") == 3

            # the new value= argument must not disturb the old route, and it must
            # fail cleanly on a panel that has no measured value table
            out = await call("hummod_slider", {"panel_path": "Trauma/Hemorrhage",
                                               "ordinal": "0", "pos": "3",
                                               "value": "7"})
            print("slider pos3 + value=7 ->", out)
            ok &= out.get("ok") is False and "no slider value table" in out.get("error", "")

            out = await call("hummod_set_param", {"panel_path": "Trauma/Hemorrhage",
                                                  "name": "Hemorrhage", "value": "1"})
            print("set_param on 3.0.4 ->", out)
            ok &= out.get("ok") is False

    print("SLIDER_REGRESSION_304_" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

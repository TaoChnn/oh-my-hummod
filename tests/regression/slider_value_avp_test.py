# Regression test for the R3 AVP fix: set a model parameter BY VALUE through the
# panel's own stepper, and prove that a client that marshals numbers as
# strings can still drive it.
#
# Background (2026-11-05, R3 4.3.6 sodium intake):
#   * R2 recorded that the AVP v3.1.0 Lifestyle/Diet/Goal steppers "do NOT
#     commit at any position".  That is wrong - they do commit (probes
#     tests/probe_avp_diet_stepper.py / _value_maps.py).
#   * The real blocker was that a stepper can only be addressed by a raw
#     scroll index, whose -> value scale is engine specific and irregular
#     (index 11 -> 20, 27 -> 180, 43 -> 500, 47 -> 1500), and that MCP
#     clients which marshal numbers as strings could not pass the index at
#     all.
#
# The fix: the profile now carries the measured index->value table
# (slider_value_lists) plus the label->control map (param_slots), and the
# server exposes hummod_set_param(name=..., value=...) and
# hummod_slider(value=...) so the caller asks for a VALUE.
#
# Runs against an ISOLATED engine copy (never the live session engine):
#   cp -r <avp engine> C:/path/to\engine_test_copies\r3_avp
#   HUMMOD_ENGINE_DIR=C:/path/to\engine_test_copies\r3_avp \
#       python tests\slider_value_avp_test.py
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SERVER = os.path.join(REPO, "oh_my_hummod", "server.py")

GOAL = "Lifestyle/Diet/Goal"
A2PAGE = "Hormones/Renin/A2"
VARS = ["DietGoalElectrolytes.Na+_mMol/Day", "DietGoalElectrolytes.Cl-_mMol/Day",
        "DietGoalElectrolytes.KCl_mMol/Day", "A2Pool.Block(%)"]


async def main() -> int:
    engine_dir = os.environ.get("HUMMOD_ENGINE_DIR", r"C:/path/to\engine_test_copies\r3_avp")
    outdir = os.path.join(REPO, "_slider_value_out")
    env = {
        "HUMMOD_ENGINE_DIR": engine_dir,
        "HUMMOD_OUTDIR": outdir,
        "HUMMOD_PROFILE": "avphummod",
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

            async def value_of(var):
                out = await call("hummod_snapshot", {"name": "sv_" + var.replace(".", "_"),
                                                     "vars": [var]})
                return out.get("values", {}).get(var)

            # 1. the manual's low-sodium diet: Na 20 / Cl 40  (Salt=20, KCl=20)
            #    NOTE: every numeric argument is passed as a STRING on purpose -
            #    that is the marshalling the fix has to survive.
            out = await call("hummod_set_param", {"panel_path": GOAL, "name": "Salt",
                                                  "value": "20"})
            print("set_param Salt=20 ->", out)
            ok &= out.get("ok") is True and out.get("value_at_pos") == 20.0
            await call("hummod_set_param", {"panel_path": GOAL, "name": "KCl",
                                            "value": "20"})
            na, cl = await value_of("DietGoalElectrolytes.Na+_mMol/Day"), \
                await value_of("DietGoalElectrolytes.Cl-_mMol/Day")
            print(f"  -> Na={na} Cl={cl}")
            ok &= na == 20.0 and cl == 40.0

            # 2. the manual's high-sodium diet: Na 500 / Cl 500 (Salt=500, KCl=0)
            await call("hummod_set_param", {"panel_path": GOAL, "name": "Salt",
                                            "value": "500"})
            await call("hummod_set_param", {"panel_path": GOAL, "name": "KCl",
                                            "value": "0"})
            na, cl = await value_of("DietGoalElectrolytes.Na+_mMol/Day"), \
                await value_of("DietGoalElectrolytes.Cl-_mMol/Day")
            print(f"  -> Na={na} Cl={cl}")
            ok &= na == 500.0 and cl == 500.0

            # 3. ACE inhibition: Block (%) = 100
            out = await call("hummod_set_param", {"panel_path": A2PAGE, "name": "Block (%)",
                                                  "value": "100"})
            print("set_param Block(%)=100 ->", out)
            ok &= out.get("ok") is True
            blk = await value_of("A2Pool.Block(%)")
            print(f"  -> Block(%)={blk}")
            ok &= blk == 100.0

            # 4. hummod_slider(value=...) resolves the same table
            out = await call("hummod_slider", {"panel_path": GOAL, "ctrl_id": 10033,
                                               "value": "180"})
            print("slider(value=180) ->", out)
            ok &= out.get("value_at_pos") == 180.0
            na = await value_of("DietGoalElectrolytes.Na+_mMol/Day")
            print(f"  -> Na={na}")
            ok &= na == 180.0

            # 5. an unknown parameter is refused with a helpful message
            out = await call("hummod_set_param", {"panel_path": GOAL, "name": "Nope",
                                                  "value": "1"})
            print("set_param bogus ->", out)
            ok &= out.get("ok") is False and "not known" in out.get("error", "")

            # 6. regression guard: the plain index route still works unchanged
            out = await call("hummod_slider", {"panel_path": GOAL, "ctrl_id": 10033,
                                               "pos": "27"})
            print("slider(pos=27) ->", out)
            na = await value_of("DietGoalElectrolytes.Na+_mMol/Day")
            print(f"  -> Na={na}")
            ok &= na == 180.0 and out.get("pos") == 27

    print("SLIDER_VALUE_AVP_TEST_" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

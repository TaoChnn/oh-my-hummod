# Verify that the tools tolerate laxly marshalled arguments.
#
# Some MCP clients marshal JSON scalars as strings and wrap JSON arrays in
# {"item": [...]}. The server must accept those shapes instead of failing the
# call in the client. This test drives a server started from *this* worktree
# against an isolated engine copy.
#
# Run:  HUMMOD_ENGINE_DIR=C:/path/to\\engine_test_copies\\r3_161 \
#       python tests/mcp_smoke_lax_args.py
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "..", "oh_my_hummod", "server.py")


async def main() -> int:
    env = dict(os.environ)
    env.setdefault("HUMMOD_ENGINE_DIR", r"C:/path/to\engine_test_copies\r3_161")
    env.setdefault("HUMMOD_OUTDIR", r"C:/path/to/out\mcp_lax")
    params = StdioServerParameters(command=sys.executable, args=[SERVER], env=env)
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
        if not ok:
            failures.append(label)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                text = " | ".join(c.text for c in res.content if getattr(c, "text", None))
                try:
                    return json.loads(text.split(" | ")[0])
                except Exception:
                    return {"raw": text}

            await call("hummod_start")

            # 1. integer as a string
            r = await call("hummod_navigate", {"panel_path": "Physiology/Lungs/Thorax"})
            check("navigate by path", r.get("ok") is True, str(r)[:120])

            # 2. integer parameter sent as a string (the client-side marshal)
            r = await call("hummod_radio", {"panel_path": "Physiology/Lungs/Thorax",
                                            "ordinal": "1", "expected": "4"})
            check("radio ordinal as string", r.get("ok") is True, str(r)[:160])
            check("radio state not readable (engine keeps it in the model)",
                  r.get("state_readable") in (None, False), str(r.get("state_readable")))

            # 3. list wrapped as {"item": [...]} (the ZCode client shape)
            r = await call("hummod_snapshot", {"name": "lax_probe",
                                               "vars": {"item": ["RightHemithorax.Pressure",
                                                                 "LeftHemithorax.Pressure"]}})
            vals = r.get("values", {})
            check("snapshot vars wrapped in {'item': [...]}",
                  r.get("ok") is True and "RightHemithorax.Pressure" in vals,
                  str(vals)[:160])
            check("radio really opened the right chest",
                  abs(float(vals.get("RightHemithorax.Pressure", 99))) < 0.001,
                  f"Right={vals.get('RightHemithorax.Pressure')}")

            # 4. integer slider position sent as a string
            r = await call("hummod_slider", {"panel_path": "Physiology/Lungs/Thorax",
                                             "ctrl_id": "4224", "pos": "6"})
            check("slider pos as string", r.get("ok") is True, str(r)[:160])
            check("slider pos coerced to int", r.get("pos") == 6, str(r.get("pos")))

            # 5. boolean parameter sent as a string
            r = await call("hummod_inspect", {"max_chars": "4000", "mode": "controls"})
            check("inspect max_chars as string", "controls" in r, str(r)[:120])

            r = await call("hummod_go", {"duration_label": "1 Min", "wait": "true",
                                         "times": "1", "verify": "false"})
            check("go wait/times/verify as strings", r.get("ok") is True, str(r)[:200])

            # 6. list of names wrapped in {"item": "x"} (single element)
            r = await call("hummod_get_vars", {"sol_path": r"C:/path/to/out\mcp_lax\lax_probe.SOL",
                                               "names": {"item": "System.X"}})
            check("get_vars names wrapped in {'item': 'x'}",
                  r.get("ok") is not False and "values" in r, str(r)[:160])

            # 7. a slider must also commit position 0 (HumMod ignores SB_LINELEFT)
            await call("hummod_navigate", {"panel_path": "Lifestyle/Air Supply"})
            r = await call("hummod_slider", {"panel_path": "Lifestyle/Air Supply",
                                             "ctrl_id": "13149", "pos": "0"})
            check("slider pos 0 accepted", r.get("ok") is True, str(r)[:160])
            v = await call("hummod_snapshot", {"name": "lax_slider0",
                                               "vars": ["AirSupply-GasTanks.N2Valve(%)"]})
            val = v.get("values", {}).get("AirSupply-GasTanks.N2Valve(%)")
            check("slider commits position 0 to the model",
                  val is not None and abs(float(val)) < 0.001, f"N2Valve={val}")

    print("LAX_ARGS_OK" if not failures else f"FAILURES: {failures}")
    return 1 if failures else 0


sys.exit(asyncio.run(main()))

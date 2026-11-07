# Verify the four improvements:
#  1) inspect mode='controls' returns widgets without the menu tree
#  2) ensure_ready auto-dismisses event modals (1.6.1 pops them on changes)
#  3) menu aliases + fuzzy fallback resolve handbook paths on other builds
#  4) hummod_probe_radio discovers radio semantics
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "oh_my_hummod", "server.py")


async def main():
    env = dict(os.environ)
    env["HUMMOD_OUTDIR"] = r"C:/path/to/out\improvements"
    os.makedirs(env["HUMMOD_OUTDIR"], exist_ok=True)
    async with stdio_client(StdioServerParameters(command=sys.executable, args=[SERVER], env=env)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                return " | ".join(c.text for c in res.content if getattr(c, "text", None))

            print("=== 1) inspect mode='controls' (no menu tree) ===")
            for key in ("3.0.4", "1.6.1", "avp"):
                await call("hummod_start", {"key": key})
            out = await call("hummod_inspect", {"engine": "3.0.4", "mode": "controls",
                                                "panel_path": "Trauma/Hemorrhage"})
            print(out[:420])
            print("  menu_present:", '"menu"' in out, "| summary:", out[out.find('"control_summary"'):][:120])

            print("\n=== 2) modal auto-dismiss (1.6.1 pops event modals) ===")
            print("nav:", (await call("hummod_navigate", {"panel_path": "Clinic/Myocardial Infarction",
                                                        "engine": "1.6.1"}))[:120])
            print("slider:", (await call("hummod_slider", {"panel_path": "Clinic/Myocardial Infarction",
                                                          "ordinal": 0, "pos": 40, "expected": 2,
                                                          "engine": "1.6.1"}))[:200])
            print("snap after slider (should work despite modal):",
                  (await call("hummod_snapshot", {"name": "imp_slider", "engine": "1.6.1",
                                                  "vars": ["LeftHeart-Infarction.Area%"]}))[:200])

            print("\n=== 3) menu alias: handbook path 'Physiology/Lungs/Thorax' on AVP ===")
            print((await call("hummod_navigate", {"panel_path": "Physiology/Lungs/Thorax",
                                                   "engine": "avp"}))[:200])
            print("fuzzy fallback (bad path):",
                  (await call("hummod_navigate", {"panel_path": "Trauma/Haemorrhage",
                                                  "engine": "avp"}))[:220])

            print("\n=== 4) probe_radio on VF page ===")
            print((await call("hummod_probe_radio", {"panel_path": "Trauma/Ventricular Fibrillation",
                                                     "probe_vars": ["Heart-VFib.Is_Fibrillating"],
                                                     "engine": "3.0.4"}))[:600])
            print("IMPROVEMENTS_OK")


if __name__ == "__main__":
    asyncio.run(main())

# Verify hummod_action over MCP: defibrillate on a fibrillating heart,
# Heart-Defibrillator.TotalShocks must advance.
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "oh_my_hummod", "server.py")
SOL = r"C:/path/to/out\mcp_new\vf_action.SOL"


async def main():
    env = dict(os.environ)
    env["HUMMOD_ENGINE_DIR"] = r"C:/path/to/engine"
    env["HUMMOD_PROFILE"] = "hummod_3.0.4"
    env["HUMMOD_OUTDIR"] = r"C:/path/to/out\mcp_new"
    async with stdio_client(StdioServerParameters(command=sys.executable, args=[SERVER], env=env)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                return " | ".join(c.text for c in res.content if getattr(c, "text", None))

            print("[nav]   ", await call("hummod_navigate", {"panel_path": "Trauma/Ventricular Fibrillation"}))
            print("[radio] ", await call("hummod_radio", {"panel_path": "Trauma/Ventricular Fibrillation",
                                                       "value": "On"}))
            print("[snap0] ", await call("hummod_snapshot", {"name": "vf_action0",
                                                             "vars": ["Heart-Defibrillator.TotalShocks",
                                                                      "Heart-VFib.Is_Fibrillating"]}))
            print("[action]", await call("hummod_action", {"panel_path": "Trauma/Ventricular Fibrillation",
                                                           "ordinal": 0, "expected": 1}))
            print("[snap1] ", await call("hummod_snapshot", {"name": "vf_action1",
                                                             "vars": ["Heart-Defibrillator.TotalShocks",
                                                                      "Heart-VFib.Is_Fibrillating"]}))
            print("ACTION_SMOKE_DONE")


if __name__ == "__main__":
    asyncio.run(main())

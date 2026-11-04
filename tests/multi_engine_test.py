# Multi-engine verification: one MCP session drives every registered engine.
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "oh_my_hummod", "server.py")


async def main():
    env = dict(os.environ)
    env.pop("HUMMOD_PROFILE", None)
    env["HUMMOD_ENGINE_DIR"] = r"C:/path/to/engine"
    env["HUMMOD_OUTDIR"] = r"C:/path/to/out\multi"
    os.makedirs(env["HUMMOD_OUTDIR"], exist_ok=True)
    async with stdio_client(StdioServerParameters(command=sys.executable, args=[SERVER], env=env)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                return " | ".join(c.text for c in res.content if getattr(c, "text", None))

            print("[engines]", (await call("hummod_engines"))[:600])

            plan = [
                ("3.0.4", "Trauma/Hemorrhage", "Go/1 Min", "BloodVol.Vol"),
                ("avp",   "Trauma/Ventricular Fibrillation", "Go/1 Min", "BloodVol.Vol"),
                ("bat",   "Trauma/Hemorrhage", "Go/1 Min", "BloodVol.Vol"),
                ("1.6.1", "Clinic/Hemorrhage", "Go/1 Min", "BloodVol.Vol"),
                ("qcp",   "View/Basic Physiology", "Go/1 Min", "X"),
            ]
            for key, panel, go, var in plan:
                st = await call("hummod_status", {"engine": key})
                if '"running": false' in st or '"running":false' in st:
                    print(f"[start {key}]", await call("hummod_start", {"key": key}))
                print(f"[nav {key}]   ", await call("hummod_navigate", {"panel_path": panel, "engine": key}))
                print(f"[go {key}]    ", await call("hummod_go", {"duration_label": go, "engine": key}))
                print(f"[snap {key}]  ", await call("hummod_snapshot",
                                                   {"name": f"multi_{key}", "vars": [var], "engine": key}))
            print("MULTI_ENGINE_OK")


asyncio.run(main())

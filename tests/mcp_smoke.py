# MCP-protocol smoke test for oh_my_hummod.server (stdio).
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "oh_my_hummod", "server.py")


async def main():
    env = dict(os.environ)
    env.setdefault("HUMMOD_ENGINE_DIR", r"C:/path/to/engine")
    env.setdefault("HUMMOD_OUTDIR", r"C:/path/to/out\mcp_new")
    params = StdioServerParameters(command=sys.executable, args=[SERVER], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("TOOLS:", [t.name for t in tools.tools])

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                return " | ".join(c.text for c in res.content if getattr(c, "text", None))

            print("[profile]", await call("hummod_profile"))
            print("[start]  ", await call("hummod_start"))
            print("[status] ", await call("hummod_status"))
            print("[nav]    ", await call("hummod_navigate", {"panel_path": "Trauma/Hemorrhage"}))
            print("[radio]  ", await call("hummod_radio", {"panel_path": "Trauma/Hemorrhage",
                                                           "value": "On", "expected": 8}))
            print("[snap]   ", await call("hummod_snapshot", {"name": "mcp_proto_smoke",
                                                              "vars": ["System.X", "Hemorrhage.Switch"]}))
            print("[radio0] ", await call("hummod_radio", {"panel_path": "Trauma/Hemorrhage",
                                                           "value": "Off"}))
            print("[bad]    ", await call("hummod_navigate", {"panel_path": "Trauma/Nope"}))
            print("[go]     ", await call("hummod_go", {"duration_label": "1 Min"}))
            print("[snap2]  ", await call("hummod_snapshot", {"name": "mcp_proto_after",
                                                              "vars": ["System.X", "BloodVol.Vol"]}))
            print("MCP_SMOKE_OK")


if __name__ == "__main__":
    asyncio.run(main())

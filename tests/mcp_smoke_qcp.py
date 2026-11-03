# MCP-protocol smoke for the QCP 2005 profile (stdio, same server, QCP engine).
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "oh_my_hummod", "server.py")


async def main():
    env = dict(os.environ)
    env["HUMMOD_ENGINE_DIR"] = r"C:/path/to/QCP-2005"
    env["HUMMOD_PROFILE"] = "qcp_2005"
    env["HUMMOD_OUTDIR"] = r"qcp-out"
    params = StdioServerParameters(command=sys.executable, args=[SERVER], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                return " | ".join(c.text for c in res.content if getattr(c, "text", None))

            print("[profile]", await call("hummod_profile"))
            print("[status] ", await call("hummod_status"))
            print("[nav]    ", await call("hummod_navigate", {"panel_path": "View/Basic Physiology"}))
            print("[go]     ", await call("hummod_go", {"duration_label": "1 Min"}))
            print("[snap]   ", await call("hummod_snapshot", {"name": "qcp_state", "vars": ["X"]}))
            print("MCP_QCP_OK")


asyncio.run(main())

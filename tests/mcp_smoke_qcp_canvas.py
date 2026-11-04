# MCP-protocol smoke for the QCP canvas tools (shot / popup / click / drag).
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "oh_my_hummod", "server.py")
OUT = r"qcp-canvas-out"
os.makedirs(OUT, exist_ok=True)


async def main():
    env = dict(os.environ)
    env["HUMMOD_ENGINE_DIR"] = r"C:/path/to/QCP-2005"
    env["HUMMOD_PROFILE"] = "qcp_2005"
    env["HUMMOD_OUTDIR"] = OUT
    params = StdioServerParameters(command=sys.executable, args=[SERVER], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                return " | ".join(c.text for c in res.content if getattr(c, "text", None))

            print("[shot]  ", (await call("hummod_shot", {"name": "canvas_00"}))[:400])
            print("[dlgs]  ", (await call("hummod_dialogs", {"engine": "qcp"}))[:400])
            print("[popup]", (await call("hummod_popup", {"engine": "qcp"}))[:400])
            # click the first toolbar button of the QCP toolbar (BLOOD group)
            print("[click]", (await call("hummod_click", {"x": 150, "y": 80, "engine": "qcp"}))[:300])
            print("[popup2]", (await call("hummod_popup", {"engine": "qcp"}))[:1200])
            print("[shot2] ", (await call("hummod_shot", {"name": "canvas_01"}))[:300])
            print("MCP_QCP_CANVAS_OK")


asyncio.run(main())

# MCP-protocol smoke for the QCP 2005 profile (stdio, same server, QCP engine).
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "oh_my_hummod", "server.py")


async def main():
    env = dict(os.environ)
    # Engine dir is overridable so regression runs can drive a private COPY of
    # the engine folder (HUMMOD_ENGINE_DIR=...) instead of a live shared engine.
    env.setdefault("HUMMOD_ENGINE_DIR", os.environ.get("HUMMOD_ENGINE_DIR", ""))
    env.setdefault("HUMMOD_PROFILE", "qcp_2005")
    env.setdefault("HUMMOD_OUTDIR", os.environ.get("HUMMOD_OUTDIR", "qcp-out"))
    params = StdioServerParameters(command=sys.executable, args=[SERVER], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                return " | ".join(c.text for c in res.content if getattr(c, "text", None))

            print("[profile]", await call("hummod_profile"))
            status = json.loads(await call("hummod_status"))
            print("[status] ", json.dumps(status))
            if not status.get("running"):
                # self-start: the smoke used to require a pre-running engine,
                # which made it fail in fresh CI-like environments; the engine
                # is a child of this session's server, so it dies with the
                # session - fine for a smoke, no cleanup needed.
                print("[start]  ", await call("hummod_start", {"key": "default", "hidden": False}))
            print("[nav]    ", await call("hummod_navigate", {"panel_path": "View/Basic Physiology"}))
            print("[go]     ", await call("hummod_go", {"duration_label": "1 Min"}))
            print("[snap]   ", await call("hummod_snapshot", {"name": "qcp_state", "vars": ["X"]}))
            print("MCP_QCP_OK")


if __name__ == "__main__":
    asyncio.run(main())

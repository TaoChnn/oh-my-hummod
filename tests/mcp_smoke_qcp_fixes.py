# MCP-protocol smoke for the R3 QCP baseline fixes (stdio, worktree server).
#
# Covers the three B-class fixes made for the QCP 4.1 baseline survey:
#   1. hummod_start accepts `engine` as an alias for `key` (before: passing
#      engine="qcp" silently started the DEFAULT engine - C:/path/to/engine).
#   2. hummod_view_group reports the state it actually reached and lists the
#      page commands the group added (before: the fallback branch reported the
#      inverted state and the ids had to be found by dumping the whole tree).
#   3. a failed hummod_open_panel returns a short sample of the category list
#      instead of all ~445 entries.
#
# The engine is driven from a private COPY of the engine folder: the 'qcp'
# entry of the registry is redirected for this process only via
# HUMMOD_ENGINES (engines.json on disk is never touched).
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "oh_my_hummod", "server.py")
COPY = os.environ.get("R3_QCP_COPY", r"C:/path/to\engine_test_copies\r3_qcp")


async def main():
    env = dict(os.environ)
    env["HUMMOD_ENGINE_DIR"] = COPY
    env["HUMMOD_PROFILE"] = "qcp_2005"
    env["HUMMOD_OUTDIR"] = os.path.join(COPY, "_mcp_out")
    env["HUMMOD_ENGINES"] = json.dumps({"qcp": COPY})
    params = StdioServerParameters(command=sys.executable, args=[SERVER], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                return " | ".join(c.text for c in res.content if getattr(c, "text", None))

            def j(text):
                return json.loads(text.split(" | ")[0])

            # 1. `engine` alias -> starts the QCP build, not the default one
            started = j(await call("hummod_start", {"engine": "qcp", "hidden": False}))
            print("[start(engine=)]", json.dumps(started))
            assert started.get("ok"), started
            assert started.get("profile") == "qcp_2005", started
            st = j(await call("hummod_status", {"engine": "qcp"}))
            assert st.get("running") and st.get("profile") == "qcp_2005", st
            print("[status]      ", json.dumps(st))

            # conflicting keys must fail loudly
            bad = await call("hummod_start", {"key": "3.0.4", "engine": "qcp"})
            print("[conflict]    ", bad)
            assert "conflicting" in bad.lower(), bad

            # 2. view group: state + the page ids the group adds
            on = j(await call("hummod_view_group",
                              {"group": "View/Nephron Details", "want": True, "engine": "qcp"}))
            print("[group on]    ", json.dumps(on))
            assert on.get("state") == "on", on
            assert on.get("pages_added"), on
            off = j(await call("hummod_view_group",
                               {"group": "View/Nephron Details", "want": False, "engine": "qcp"}))
            print("[group off]   ", json.dumps(off))
            assert off.get("state") == "off", off
            assert off.get("pages_removed"), off

            # 3. failed open_panel -> short payload
            miss = j(await call("hummod_open_panel",
                                {"variable": "zzz_no_such_variable", "engine": "qcp"}))
            print("[open_panel]  ", json.dumps(miss)[:400])
            assert miss.get("n_categories", 0) > 100, miss
            assert len(miss.get("categories_sample", [])) <= 25, miss
            assert "categories" not in miss, miss

            print("MCP_QCP_FIXES_OK")


asyncio.run(main())

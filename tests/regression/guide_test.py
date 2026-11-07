# Verify the public manual is actually reachable by a client:
#   - instructions shows up in the initialize handshake
#   - every resource in hummod://guide, ://workflow, ://quirks, ://variables
#     can be listed and read
# No engine needed.
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "..", "oh_my_hummod", "server.py")

EXPECTED = [
    "hummod://guide",
    "hummod://workflow",
    "hummod://quirks",
    "hummod://variables",
]


async def main():
    env = dict(os.environ)
    env.setdefault("HUMMOD_ENGINE_DIR", r"C:/path/to/engine")
    env.setdefault("HUMMOD_OUTDIR", r"C:/path/to/out\guide_test")
    params = StdioServerParameters(command=sys.executable, args=[SERVER], env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()

            # 1. instructions in the handshake
            instr = getattr(init, "instructions", None)
            assert instr, "server sent no instructions in the handshake"
            print("[instructions]", len(instr), "chars")
            for must in ("hummod_inspect", "hummod://guide", "probe_vars"):
                assert must in instr, f"instructions does not mention {must!r}"
            print("  OK  mentions tools, resources and probe_vars")

            # 2. resources are listed
            res = await s.list_resources()
            uris = {str(x.uri) for x in res.resources}
            print("[resources]", sorted(uris))
            for u in EXPECTED:
                assert u in uris, f"resource {u} not listed"
            print("  OK  all four resources listed")

            # 3. every resource reads back with content
            for u in EXPECTED:
                got = await s.read_resource(u)
                body = got.contents[0].text
                assert len(body) > 400, f"{u} looks empty ({len(body)} chars)"
                print(f"  OK  {u} -> {len(body)} chars")
                # the guide must actually mention the things agents get wrong
                if u == "hummod://quirks":
                    for must in ("EPO", "probe_vars", "SB_THUMBPOSITION",
                                 "VISIBLE", "byte-identical"):
                        assert must in body, f"quirks resource misses {must!r}"
                if u == "hummod://guide":
                    for must in ("hummod_snapshot", "hummod_history",
                                 "hummod_set_param"):
                        assert must in body, f"guide resource misses {must!r}"

            # 4. the tools still work / are still listed
            tools = await s.list_tools()
            names = [t.name for t in tools.tools]
            assert "hummod_inspect" in names and "hummod_go" in names
            print("[tools]", len(names), "tools still listed")

            print("GUIDE_OK")


if __name__ == "__main__":
    asyncio.run(main())

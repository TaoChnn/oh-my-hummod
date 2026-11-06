# Verify the academic-integrity statement tool:
#   - it returns a ready-to-paste statement
#   - the citation carries the real version and the access date
#   - placeholders exist when the contributions are not supplied
#   - the statement is registered as a tool AND as a resource
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
    env.setdefault("HUMMOD_OUTDIR", r"C:/path/to/out\integrity_test")
    params = StdioServerParameters(command=sys.executable, args=[SERVER], env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                return " | ".join(c.text for c in res.content
                                  if getattr(c, "text", None))

            # 1. the tool exists and is discoverable
            tools = await s.list_tools()
            names = [t.name for t in tools.tools]
            assert "hummod_integrity_statement" in names, \
                "integrity statement tool is not registered"
            print("[tool] hummod_integrity_statement registered")

            # 2. filled-in version
            out = await call("hummod_integrity_statement", {
                "ai_contributions": ["ran the simulation arms through the tools",
                                     "parsed the exported SOL files"],
                "human_contributions": ["designed the protocol", "wrote the report"],
                "author": "Test Student",
                "date": "2026-11-06",
            })
            import json as _json
            d = _json.loads(out)
            st = d["statement"]
            assert "学术诚信" in st, "statement is not labelled"
            assert "Test Student" in st, "author missing"
            assert "2026-11-06" in st, "access date missing"
            assert "ran the simulation arms" in st, "AI contributions missing"
            assert "designed the protocol" in st, "human contributions missing"
            assert "https://github.com/TaoChnn/oh-my-hummod" in st, \
                "citation missing"
            assert "bibtex" in st.lower(), "BibTeX block missing"
            assert "[请填写" not in st, \
                "placeholders still present although both lists were given"
            assert "不鼓励" in st, "the not-endorsed note is missing"
            print("[filled] statement carries date, author, both lists, citation")
            print(" ", st.splitlines()[0])

            # 3. unfilled version still carries placeholders (so the agent
            #    cannot ship a statement that says nothing)
            out2 = await call("hummod_integrity_statement", {})
            st2 = _json.loads(out2)["statement"]
            assert "[请填写" in st2, "missing placeholders when nothing was given"
            assert "https://github.com/TaoChnn/oh-my-hummod" in st2
            print("[unfilled] placeholders present, citation still there")

            # 4. the csv escape hatch works too
            out3 = await call("hummod_integrity_statement", {
                "ai_contributions_csv": "ran the engine / made the figures",
                "human_contributions_csv": "interpreted the results",
            })
            st3 = _json.loads(out3)["statement"]
            assert "ran the engine / made the figures" in st3
            assert "interpreted the results" in st3
            print("[csv] csv form accepted")

            # 4b. csv splits on commas (that is what csv means) - the parts
            #     must still land in the statement
            out4 = await call("hummod_integrity_statement", {
                "ai_contributions_csv": "ran the engine, made the figures",
            })
            st4 = _json.loads(out4)["statement"]
            assert "ran the engine; made the figures" in st4, \
                "comma-separated csv items should be joined with '; '"
            print("[csv] comma-separated items joined correctly")

            # 5. the policy is reachable as a resource
            res = await s.list_resources()
            uris = {str(x.uri) for x in res.resources}
            assert "hummod://integrity" in uris, "integrity resource not listed"
            got = await s.read_resource("hummod://integrity")
            body = got.contents[0].text
            for must in ("hummod_integrity_statement", "verbatim", "last section",
                         "not endorsed"):
                assert must in body, f"integrity resource misses {must!r}"
            print("[resource] hummod://integrity ->", len(body), "chars")

            # 6. the instructions demand it (this is the part an agent reads
            #    without opening any resource)
            init = await s.initialize()
            instr = getattr(init, "instructions", "") or ""
            assert "hummod_integrity_statement" in instr, \
                "instructions do not mention the integrity tool"
            assert "MANDATORY" in instr, "instructions do not mark it mandatory"
            assert "integrity" in instr, "instructions do not point at the resource"
            print("[instructions] demands the statement:", len(instr), "chars")

            print("INTEGRITY_OK")


asyncio.run(main())

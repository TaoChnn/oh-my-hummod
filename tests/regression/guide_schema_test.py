# The manual is a contract: every tool call documented in the resources and
# in the handshake instructions must use REAL parameter names, and every
# hummod_* name mentioned must be a registered tool. guide.py once drifted
# from server.py (hummod_edit documented as ctrl_id=/text= instead of
# ordinal=/value=, probe_vars promised on tools that do not have it) and no
# test noticed - agents then copied the wrong calls straight out of the
# manual and hit validation errors. This test pins the manual to the schema.
# No engine needed.
import asyncio
import os
import re
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "..", "oh_my_hummod", "server.py")


async def main():
    env = dict(os.environ)
    env.setdefault("HUMMOD_ENGINE_DIR", r"C:/path/to/engine")
    env.setdefault("HUMMOD_OUTDIR", r"C:/path/to/out\guide_schema_test")
    params = StdioServerParameters(command=sys.executable, args=[SERVER], env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()

            tools = {t.name: set((t.input_schema or {}).get("properties", {}))
                     for t in (await s.list_tools()).tools}
            assert tools, "no tools registered"

            texts = {"instructions": getattr(init, "instructions", "") or ""}
            for uri in ("hummod://guide", "hummod://workflow", "hummod://quirks",
                        "hummod://variables", "hummod://integrity"):
                texts[uri] = (await s.read_resource(uri)).contents[0].text

            # 1. every hummod_* name mentioned anywhere is a registered tool
            #    (a rename in server.py must not leave the manual behind)
            for where, text in texts.items():
                used = set(re.findall(r"hummod_[a-z_]+", text))
                unknown = sorted(used - set(tools))
                assert not unknown, f"{where}: unknown tools {unknown}"

            # 2. every keyword argument inside a documented call is a real
            #    parameter of that tool's schema
            call_re = re.compile(r"(hummod_[a-z_]+)\(([^)]*)\)")
            kw_re = re.compile(r"([a-z_]+)\s*=")
            checked = 0
            for where, text in texts.items():
                for m in call_re.finditer(text):
                    name, arglist = m.group(1), m.group(2)
                    if name not in tools:
                        continue  # already reported by check 1
                    kws = set(kw_re.findall(arglist))
                    bad = sorted(kws - tools[name])
                    assert not bad, (
                        f"{where}: {name} documented with parameters {bad} "
                        f"that its schema does not have "
                        f"(schema: {sorted(tools[name])})")
                    checked += 1

            # 3. the instructions must not tie probe_vars to the setters that
            #    do not have it, and must say which one does
            instr = texts["instructions"]
            for tool in ("hummod_slider", "hummod_edit", "hummod_set_param"):
                for line in instr.splitlines():
                    if tool in line and "probe_vars" in line:
                        raise AssertionError(
                            f"instructions tie {tool} to probe_vars, which its "
                            f"schema does not have: {line.strip()!r}")
            assert "hummod_radio accepts probe_vars" in instr, \
                "instructions no longer say which setter has probe_vars"

            print(f"GUIDE_SCHEMA_OK ({len(tools)} tools, "
                  f"{checked} documented calls checked against schemas)")


asyncio.run(main())

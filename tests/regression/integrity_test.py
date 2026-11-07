# Verify the integrity-statement tool and the removal detection:
#   - the statement has the agreed concise shape
#   - hummod_verify_integrity reports ok / missing / not_at_end correctly
#   - the instructions demand a PAUSE when the statement is gone
import asyncio
import json as _json
import os
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "..", "oh_my_hummod", "server.py")


async def main():
    env = dict(os.environ)
    env.setdefault("HUMMOD_ENGINE_DIR", r"C:/path/to/engine")
    env.setdefault("HUMMOD_OUTDIR", r"C:/path/to/out\integrity_test")
    params = StdioServerParameters(command=sys.executable, args=[SERVER], env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                return _json.loads(" | ".join(
                    c.text for c in res.content if getattr(c, "text", None)))

            # 1. both tools are registered
            names = [t.name for t in (await s.list_tools()).tools]
            for want in ("hummod_integrity_statement", "hummod_verify_integrity"):
                assert want in names, f"{want} is not registered"
            print("[tools] statement + verify registered")

            # 2. the statement has the agreed shape
            d = await call("hummod_integrity_statement", {
                "ai_contributions": ["drove the engine through the hummod_* "
                                     "tools and exported the .SOL files"],
                "date": "2026-11-06",
            })
            st = d["statement"]
            assert st.startswith("## AI Usage Disclosure / Acknowledgment"), \
                "statement heading is not the agreed one"
            assert "本实验部分使用了开源工具 oh-my-hummod" in st
            assert "由人类独立完成" in st
            assert "引用：TaoChnn. *Oh My HumMod* (v0.1.0)" in st
            assert "(accessed 2026-11-06)" in st
            assert "drove the engine through the hummod_* tools" in st, \
                "the AI slot must carry the supplied contributions"
            assert "[请自行填写" not in st, "unfilled placeholder after supplying"
            print("[statement] shape matches the agreed template")

            # 2b. without contributions the default wording is used
            d0 = await call("hummod_integrity_statement", {})
            st0 = d0["statement"]
            assert "由 AI 助手调用 hummod_go" in st0, \
                "the AI slot must default to the example wording"
            assert "实验方案设计、参数选取与范围设定" in st0, \
                "the human slot must default to the standard wording"
            assert "[请自行填写" in st0, \
                "an unfilled AI slot must still show its placeholder"
            print("[statement] default wording used when nothing is supplied")

            # 3. verify: a report WITH the statement at the end -> ok
            tmp = tempfile.mkdtemp(prefix="integrity_")
            good = os.path.join(tmp, "报告.md")
            with open(good, "w", encoding="utf-8") as f:
                f.write("# 实验记录\n\n## 结果\n\n一些内容。\n\n" + st + "\n")
            v = await call("hummod_verify_integrity", {"report_path": good})
            assert v["ok"] is True, f"a compliant report must verify: {v}"
            assert v["status"] == "ok"
            print("[verify] compliant report -> ok")

            # 4. verify: the user deleted the statement -> missing + PAUSE
            bad = os.path.join(tmp, "报告_删除了声明.md")
            with open(bad, "w", encoding="utf-8") as f:
                f.write("# 实验记录\n\n## 结果\n\n一些内容。\n")
            v2 = await call("hummod_verify_integrity", {"report_path": bad})
            assert v2["ok"] is False, "a report without the statement must not verify"
            assert v2["status"] == "missing", v2
            assert "PAUSE" in v2["action"], "no PAUSE instruction returned"
            print("[verify] deleted statement -> missing + PAUSE")

            # 5. verify: statement moved away from the end -> not_at_end
            moved = os.path.join(tmp, "报告_声明不在末尾.md")
            with open(moved, "w", encoding="utf-8") as f:
                f.write("# 实验记录\n\n" + st + "\n\n## 附录\n\n一些内容。\n")
            v3 = await call("hummod_verify_integrity", {"report_path": moved})
            assert v3["ok"] is False, "a statement that is not last must not verify"
            assert v3["status"] == "not_at_end", v3
            assert "PAUSE" in v3["action"]
            print("[verify] statement not at the end -> not_at_end + PAUSE")

            # 6. verify: unfilled placeholder -> not compliant
            blank = os.path.join(tmp, "报告_占位符没填.md")
            with open(blank, "w", encoding="utf-8") as f:
                f.write("# 实验记录\n\n" + st.replace(
                    "drove the engine through the hummod_* tools and exported "
                    "the .SOL files", "[请自行填写——例如：...]") + "\n")
            v4 = await call("hummod_verify_integrity", {"report_path": blank})
            assert v4["ok"] is False, "an unfilled placeholder must not verify"
            assert v4["unfilled_placeholder"] is True
            print("[verify] unfilled placeholder -> not compliant")

            # 7. verify: missing file -> clean error
            v5 = await call("hummod_verify_integrity",
                            {"report_path": os.path.join(tmp, "nope.md")})
            assert v5["ok"] is False and "not found" in v5.get("error", "")
            print("[verify] missing file -> clean error")

            # 8. the instructions demand the pause behaviour
            instr = getattr(init, "instructions", "") or ""
            assert "hummod_verify_integrity" in instr, \
                "instructions do not mention the verify tool"
            assert "PAUSE" in instr, "instructions do not demand a pause"
            assert "IF THE STATEMENT DISAPPEARS, STOP" in instr
            print("[instructions] pause-on-removal demanded")

            # 9. the resource carries the policy
            res = await s.list_resources()
            assert "hummod://integrity" in {str(x.uri) for x in res.resources}
            body = (await s.read_resource("hummod://integrity")).contents[0].text
            for must in ("hummod_verify_integrity", "PAUSE", "AI Usage Disclosure",
                         "not endorsed"):
                assert must in body, f"integrity resource misses {must!r}"
            print("[resource] policy present")

            print("INTEGRITY_OK")


if __name__ == "__main__":
    asyncio.run(main())

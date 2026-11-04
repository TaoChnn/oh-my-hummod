"""One-shot MCP client for driving a FRESH server process per tool call.

Why this exists: a long-lived server caches its engine registry (from
engines.json found at *import* time) and its per-engine bridges forever. In a
multi-agent workspace a stale/shadowed registry can silently bind a named
engine key to the WRONG engine process (observed: key "qcp" bound to a
HumMod 3.0.4 engine started for a parallel session). A one-shot client avoids
the whole class of poisoned-cache bugs: every call boots a clean server whose
registry is read from the worktree's engines.json and whose profile is
auto-detected from the live menus (no HUMMOD_PROFILE override).

Usage:
    python tests/mcp_oneshot_client.py <tool_name> ['{"json": "args"}']

Env (all optional):
    HUMMOD_ENGINE_DIR  engine dir for the "default" key (worktree engines.json
                       still supplies the named keys such as "qcp")
    HUMMOD_OUTDIR      where snapshot exports are written (default: own scratch)
    HUMMOD_ENGINES     JSON dict merged over the worktree engines.json

The server is spawned from THIS repo (parent of this file), so testing fixes
in a worktree never touches the installed/other checkouts.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "usage: mcp_oneshot_client.py <tool> [json_args]"}))
        return 2
    tool = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

    env = {
        "HUMMOD_ENGINE_DIR": os.environ.get("HUMMOD_ENGINE_DIR", ""),
        "HUMMOD_OUTDIR": os.environ.get(
            "HUMMOD_OUTDIR", os.path.join(REPO, "_oneshot_out")
        ),
    }
    if os.environ.get("HUMMOD_ENGINES"):
        env["HUMMOD_ENGINES"] = os.environ["HUMMOD_ENGINES"]
    env = {k: v for k, v in env.items() if v}
    # NOTE: deliberately NOT forwarding HUMMOD_PROFILE - profile detection must
    # run against the live menu so a named engine key cannot inherit the
    # default engine's profile override.

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "oh_my_hummod.server"],
        cwd=REPO,
        env=env,
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
    texts = [c.text for c in (result.content or []) if getattr(c, "type", "") == "text"]
    out = {"tool": tool, "args": args, "result": "\n".join(texts) if texts else None,
           "is_error": bool(getattr(result, "is_error", getattr(result, "isError", False)))}
    print(json.dumps(out, ensure_ascii=False))
    return 1 if out["is_error"] else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

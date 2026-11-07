# Regression for the QCP file-dialog filename-edit fix (bridge._pick_dialog_edit):
# Save ICs -> edit a value -> Load ICs must apply it (the Open dialog's
# filename Edit is id 1148 on QCP, while the profile listed 1001 = address bar).
# Runs against a private COPY of the engine dir (HUMMOD_ENGINE_DIR).
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "..", "oh_my_hummod", "server.py")
ENGINE = os.environ.get(
    "HUMMOD_ENGINE_DIR", r"C:/path/to\engine_test_copies\r2_qcp")
OUT = os.environ.get("HUMMOD_OUTDIR", r"qcp-out_ics_rt")


async def main():
    os.makedirs(OUT, exist_ok=True)
    env = dict(os.environ)
    env["HUMMOD_ENGINE_DIR"] = ENGINE
    env["HUMMOD_PROFILE"] = "qcp_2005"
    env["HUMMOD_OUTDIR"] = OUT
    params = StdioServerParameters(command=sys.executable, args=[SERVER], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                texts = [c.text for c in (res.content or []) if getattr(c, "type", "") == "text"]
                blob = "\n".join(texts)
                try:
                    return json.loads(blob)
                except json.JSONDecodeError:
                    return {"raw": blob}

            print("[start] ", (await call("hummod_start", {"key": "default", "hidden": False})))
            print("[rst]   ", (await call("hummod_restart")))
            save = await call("hummod_save_ics", {"name": "rt_base"})
            print("[save]  ", save)
            assert save.get("ok"), "save_ics failed"
            ics = save["path"]
            with open(ics, encoding="utf-8", errors="replace") as f:
                content = f.read()
            old = '{ VAR "Posture Control, Default Posture" 1. }'
            new = '{ VAR "Posture Control, Default Posture" 3. }'
            assert old in content, "posture var line not found in saved ICS"
            edited = os.path.join(OUT, "rt_standing.ICS")
            with open(edited, "w", encoding="utf-8") as f:
                f.write(content.replace(old, new, 1))
            load = await call("hummod_load_ics", {"path": edited})
            print("[load]  ", load)
            assert load.get("ok"), "load_ics failed"
            print("[go]    ", (await call("hummod_go", {"duration_label": "10 Sec", "verify": True})))
            snap = await call("hummod_snapshot", {
                "name": "rt_check",
                "vars": ["Posture Control, Default Posture",
                         "Posture Control, Result",
                         "Posture Control, Is Standing",
                         "Posture Control, Is Lying"]})
            print("[snap]  ", json.dumps(snap))
            vals = snap.get("values", {})
            ok = (vals.get("Posture Control, Default Posture") == 3.0
                  and vals.get("Posture Control, Is Lying") == 0.0)
            print("MCP_ICS_ROUNDTRIP_OK" if ok else "MCP_ICS_ROUNDTRIP_FAIL")
            return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

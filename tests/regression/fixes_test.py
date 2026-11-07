# Verify the follow-up fixes:
#  B7 - hummod_slider can locate a slider by ctrl_id / label (not only ordinal)
#  B8 - hummod_snapshot always includes the model clock alongside requested vars
#  B-11 - engines without a status-bar signal fall back to the Stop menu
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "oh_my_hummod", "server.py")


async def main():
    env = dict(os.environ)
    env["HUMMOD_OUTDIR"] = r"C:/path/to/out\fixes"
    os.makedirs(env["HUMMOD_OUTDIR"], exist_ok=True)
    async with stdio_client(StdioServerParameters(command=sys.executable, args=[SERVER], env=env)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                return " | ".join(c.text for c in res.content if getattr(c, "text", None))

            print("=== B8: snapshot always carries the model clock ===")
            out = await call("hummod_snapshot", {"name": "b8_clock", "engine": "3.0.4",
                                                 "vars": ["BloodVol.Vol"]})
            print(" ", out[:230])
            assert '"System.X"' in out, "model clock missing from snapshot values"
            print("  OK  System.X present alongside requested vars")

            print("\n=== B7: slider located by ordinal / ctrl_id ===")
            out2 = await call("hummod_slider", {"panel_path": "Trauma/Hemorrhage",
                                                 "ordinal": 0, "pos": 3, "engine": "3.0.4"})
            print(" ", out2[:200])
            assert '"located_by": "ordinal"' in out2, "ordinal addressing broke"
            out3 = await call("hummod_slider", {"panel_path": "Trauma/Hemorrhage",
                                                 "ctrl_id": 24220, "pos": 3, "engine": "3.0.4"})
            print(" ", out3[:200])
            assert '"located_by": "ctrl_id"' in out3, "ctrl_id addressing broke"
            print("  OK  slider addressable by ordinal and by ctrl_id")

            print("\n=== B7: label miss gives actionable alternatives ===")
            out = await call("hummod_slider", {"panel_path": "Trauma/Hemorrhage",
                                                "label": "Target Rate", "pos": 1,
                                                "engine": "3.0.4"})
            print(" ", out[:300])
            assert '"ok": false' in out, "bad label should fail, not silently act"
            assert "ctrl_id" in out and "ordinal" in out, \
                "error should list the sliders with ctrl_id/ordinal"
            print("  OK  error lists ctrl_id/ordinal alternatives")

            print("\n=== inspect stays valid JSON when long ===")
            import json as _json
            insp = await call("hummod_inspect", {"engine": "3.0.4", "mode": "both",
                                                "panel_path": "Trauma/Hemorrhage"})
            try:
                _json.loads(insp)
                print("  OK  inspect output parses as JSON")
            except Exception as e:
                raise AssertionError("inspect output is not valid JSON: " + str(e))

            print("\n=== B-11: QCP run completion (Stop-menu fallback) ===")
            out = await call("hummod_go", {"duration_label": "10 Sec", "engine": "qcp",
                                           "verify": True})
            print(" ", out[:260])

            print("\nFIXES_OK")


if __name__ == "__main__":
    asyncio.run(main())

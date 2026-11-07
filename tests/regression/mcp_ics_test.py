# Regression test for the .ICS save/load chain (batch-3 field trial).
# Drives a *running* engine through: save ICs -> Restart (state lost) ->
# load ICs (state restored). Verifies each step at model level.
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "..", "oh_my_hummod", "server.py")

BB_VARS = ["AmbientTemperature.Temp(F)", "Wind.MPH", "Status.Posture",
           "Exercise-Treadmill.Speed(MPH)", "DietIntakeH2O.Fixed?",
           "DietGoalH2O.Rate(L/Day)", "System.X"]


async def main():
    env = dict(os.environ)
    params = StdioServerParameters(command=sys.executable, args=[SERVER], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                return " | ".join(c.text for c in res.content if getattr(c, "text", None))

            print("[status]", await call("hummod_status"))

            # 1. save the current state as BILLYBOB.ICS
            out = await call("hummod_save_ics", {"name": "BILLYBOB"})
            print("[save]  ", out)
            path = json.loads(out)["path"]

            # 2. Restart: in-memory reset must NOT return to Billy Bob
            print("[restart]", await call("hummod_restart"))
            res = await call("hummod_snapshot", {"name": "ics_after_restart", "vars": BB_VARS})
            vals = json.loads(res)["values"]
            print("[after restart]", {k: vals[k] for k in BB_VARS})

            # 3. Load Initial Conditions: state must come back
            print("[load]  ", await call("hummod_load_ics", {"path": path}))
            res = await call("hummod_snapshot", {"name": "ics_after_load", "vars": BB_VARS})
            vals = json.loads(res)["values"]
            print("[after load]  ", {k: vals[k] for k in BB_VARS})

            ok = (abs(vals["AmbientTemperature.Temp(F)"] - 100.0) < 0.01
                  and abs(vals["Wind.MPH"] - 2.0) < 0.01
                  and abs(vals["Status.Posture"] - 3.0) < 0.01
                  and abs(vals["DietIntakeH2O.Fixed?"] - 1.0) < 0.01
                  and abs(vals["DietGoalH2O.Rate(L/Day)"] - 0.0) < 0.01
                  and abs(vals["Exercise-Treadmill.Speed(MPH)"] - 2.0) < 0.01)
            print("ICS_TEST_" + ("OK" if ok else "FAILED"))


if __name__ == "__main__":
    asyncio.run(main())

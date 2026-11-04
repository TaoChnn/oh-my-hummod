# Focused Load-ICs probe: attach to a *running* engine, load BILLYBOB.ICS,
# then verify state at model level. Reports engine liveness after each step.
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "oh_my_hummod", "server.py")

BB_VARS = ["AmbientTemperature.Temp(F)", "Wind.MPH", "Status.Posture",
           "Exercise-Control.Request", "Exercise-Treadmill.Speed(MPH)",
           "DietIntakeH2O.Fixed?", "DietGoalH2O.Rate(L/Day)", "System.X"]


async def main():
    env = dict(os.environ)
    params = StdioServerParameters(command=sys.executable, args=[SERVER], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                return " | ".join(c.text for c in res.content if getattr(c, "text", None))

            ics = os.environ.get("HUMMOD_OUTDIR", ".") + os.sep + "BILLYBOB.ICS"

            print("[status]", await call("hummod_status"))
            print("[load]  ", await call("hummod_load_ics", {"path": ics}))
            print("[dialogs]", await call("hummod_dialogs"))
            print("[busy]  ", await call("hummod_busy"))
            print("[snap]  ", await call("hummod_snapshot",
                                         {"name": "ics_load_check", "vars": BB_VARS}))


asyncio.run(main())

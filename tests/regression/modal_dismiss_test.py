"""Regression test for the modal-dialog dismissal defect (B1) and the
modal reporting tools (B4).

HumMod 1.6.1 raises MessageBox-style popups from its model files
(<page> elements). The ECG events and the symptom messages use MB_YESNO, so
the dialog only offers IDYES(6)/IDNO(7) - there is no IDOK/IDCANCEL to click.
The old dismiss_modals() posted IDOK/IDCANCEL and clicked children with
cid in (1, 2), so those dialogs could never be closed and every engine
command failed with "engine still blocked by a modal dialog".

Run:  python tests/modal_dismiss_test.py
"""
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "..", "oh_my_hummod", "server.py")
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from oh_my_hummod.bridge import Bridge  # noqa: E402


class FakeButton:
    """Minimal stand-in for Bridge.Control."""

    def __init__(self, ctrl_id, text="", style=0x50030001, visible=True, enabled=True):
        self.ctrl_id = ctrl_id
        self.text = text
        self.style = style
        self.visible = visible
        self.enabled = enabled


def test_button_picking():
    pick = Bridge.pick_dialog_button
    # MB_YESNO dialog (HumMod 1.6.1 ECG / symptom popups): only 6 and 7.
    yesno = [FakeButton(6, "是(&Y)"), FakeButton(7, "否(&N)")]
    assert pick(yesno).ctrl_id == 6, "IDYES must be picked on a MB_YESNO dialog"
    assert pick(yesno, prefer=7).ctrl_id == 7
    # MB_OK dialog: IDOK(1) is the only button.
    ok = [FakeButton(1, "确定(&O)")]
    assert pick(ok).ctrl_id == 1
    # A dialog that offers both: the preferred one wins.
    mixed = [FakeButton(1, "OK"), FakeButton(6, "Yes"), FakeButton(7, "No")]
    assert pick(mixed).ctrl_id == 6
    assert pick(mixed, prefer=1).ctrl_id == 1
    # Disabled / hidden buttons are not clickable.
    hidden = [FakeButton(6, visible=False), FakeButton(7, enabled=False)]
    assert pick(hidden) is None
    # A radio/check button is not a push button and must be skipped.
    nonpush = [FakeButton(6, style=0x50030009), FakeButton(1)]
    assert pick(nonpush).ctrl_id == 1
    print("BUTTON_PICK_OK")


async def main():
    test_button_picking()

    env = dict(os.environ)
    env.pop("HUMMOD_PROFILE", None)
    env["HUMMOD_ENGINE_DIR"] = r"C:/path/to/engine"
    env["HUMMOD_OUTDIR"] = r"C:/path/to/out\modal_test"
    os.makedirs(env["HUMMOD_OUTDIR"], exist_ok=True)
    async with stdio_client(StdioServerParameters(command=sys.executable, args=[SERVER], env=env)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = {t.name for t in (await s.list_tools()).tools}
            for needed in ("hummod_modals", "hummod_dismiss_modal"):
                assert needed in tools, f"missing tool {needed}"

            async def call(name, args=None):
                res = await s.call_tool(name, args or {})
                return " | ".join(c.text for c in res.content if getattr(c, "text", None))

            out = await call("hummod_modals", {"engine": "1.6.1"})
            assert '"count"' in out, out
            out = await call("hummod_dismiss_modal", {"engine": "1.6.1"})
            # must not raise and must report what it closed / what is still open
            assert '"dismissed"' in out and '"still_open"' in out, out
            print("MODAL_TOOLS_OK")


asyncio.run(main())
print("MODAL_DISMISS_OK")

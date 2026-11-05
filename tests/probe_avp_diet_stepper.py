# Probe: does the AVP (v3.1.0) Lifestyle/Diet/Goal stepper commit a model value?
#
# R2 found that the electrolyte steppers on that page (Salt / KCl / ...) do not
# commit at any scroll position, which blocks 4.3.6 (sodium intake) from being
# set through the GUI.  This probe tries the plausible Win32 routes against an
# ISOLATED engine copy and reports which one actually moves the model value.
#
#   cp -r <avp engine> C:/path/to\engine_test_copies\r3_avp
#   python tests\probe_avp_diet_stepper.py
#
# Read-only probe: it changes the value only inside the throw-away copy.
import ctypes
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from oh_my_hummod.bridge import Bridge            # noqa: E402
from oh_my_hummod.profile import Profile          # noqa: E402
from oh_my_hummod.solver import parse_export      # noqa: E402

ENGINE = os.environ.get("HUMMOD_ENGINE_DIR", r"C:/path/to\engine_test_copies\r3_avp")
OUT = r"C:/path/to/out\probe_avp_diet"
PANEL = "Lifestyle/Diet/Goal"
VAR = "DietGoalElectrolytes.Na+_mMol/Day"

user32 = ctypes.windll.user32
WM_HSCROLL, WM_COMMAND, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0114, 0x0111, 0x0201, 0x0202
SB_LINERIGHT, SB_LINELEFT, SB_THUMBPOSITION, SB_ENDSCROLL = 1, 0, 4, 8


def lparam(x: int, y: int) -> int:
    return (y << 16) | (x & 0xFFFF)


def read_value(b, profile) -> float:
    os.makedirs(OUT, exist_ok=True)
    sol = os.path.join(OUT, "probe.SOL")
    if os.path.exists(sol):
        os.remove(sol)
    b.save_file_dialog(profile.file["save_sol"], sol, tuple(profile.dialog_edit_ids))
    vals = parse_export(sol, {VAR.lower()})
    for k, v in vals.items():
        if k.lower() == VAR.lower():
            return v
    return float("nan")


def main() -> int:
    profile = Profile.load("avphummod")
    b = Bridge(ENGINE)
    b.start(hidden=True)
    b.wait_ready()
    time.sleep(1.0)
    node = b.menu_tree().walk(PANEL)
    b.navigate(node.cmd_id)
    time.sleep(0.8)

    sliders = sorted([c for c in b.controls() if c.cls == "ScrollBar"],
                      key=lambda c: c.ctrl_id)
    print(f"panel={PANEL} cmd_id={node.cmd_id} sliders={len(sliders)}")
    for i, c in enumerate(sliders):
        print(f"  [{i}] ctrl_id={c.ctrl_id} rect=({c.left},{c.top},{c.right},{c.bottom}) "
              f"pos={c.scroll_pos} range=({c.scroll_min},{c.scroll_max})")

    # The Salt stepper: right-hand column, first row (known from the panel shot).
    salt = next((c for c in sliders if c.left > 300 and c.top < 260), sliders[0])
    parent = user32.GetParent(salt.hwnd)
    print(f"\nusing slider ctrl_id={salt.ctrl_id} hwnd={salt.hwnd} parent={parent}")
    base = read_value(b, profile)
    print(f"baseline {VAR} = {base}")

    def try_route(name, fn):
        before = read_value(b, profile)
        fn()
        time.sleep(0.6)
        after = read_value(b, profile)
        print(f"  {name:42s} {before:>8.4g} -> {after:>8.4g} "
              f"{'COMMIT' if after != before else '(no change)'}")
        return after

    print("\nroutes:")
    try_route("SB_THUMBPOSITION(1) -> parent",
              lambda: user32.PostMessageW(parent, WM_HSCROLL,
                                          (1 << 16) | SB_THUMBPOSITION, salt.hwnd))
    try_route("SB_THUMBPOSITION(1) -> scrollbar",
              lambda: user32.PostMessageW(salt.hwnd, WM_HSCROLL,
                                          (1 << 16) | SB_THUMBPOSITION, 0))

    def line_right(n=5, target=None):
        for _ in range(n):
            user32.PostMessageW(target or parent, WM_HSCROLL, SB_LINERIGHT, salt.hwnd)
            time.sleep(0.05)

    try_route("SB_LINERIGHT x5 -> parent", lambda: line_right())
    try_route("SB_LINERIGHT x5 -> scrollbar", lambda: line_right(target=salt.hwnd))

    def click_arrow(side="right"):
        w = salt.right - salt.left
        cx = w - 6 if side == "right" else 6
        cy = (salt.bottom - salt.top) // 2
        user32.PostMessageW(salt.hwnd, WM_LBUTTONDOWN, 1, lparam(cx, cy))
        user32.PostMessageW(salt.hwnd, WM_LBUTTONUP, 0, lparam(cx, cy))

    try_route("WM_LBUTTONDOWN/UP on right arrow", click_arrow)

    def cmd_thumbpos():
        user32.PostMessageW(parent, WM_COMMAND, (SB_THUMBPOSITION << 16) | salt.ctrl_id,
                            salt.hwnd)

    try_route("WM_COMMAND(SB_THUMBPOSITION) -> parent", cmd_thumbpos)

    def drag_thumb():
        # drag the thumb to the far right end of the trough
        user32.SendMessageW(salt.hwnd, WM_LBUTTONDOWN, 1,
                            lparam((salt.right - salt.left) // 2, (salt.bottom - salt.top) // 2))
        user32.PostMessageW(salt.hwnd, WM_MOUSEMOVE if False else 0x0200, 0,
                            lparam(salt.right - salt.left - 3, (salt.bottom - salt.top) // 2))
        user32.PostMessageW(salt.hwnd, WM_LBUTTONUP, 0,
                            lparam(salt.right - salt.left - 3, (salt.bottom - salt.top) // 2))

    try_route("drag thumb to right end", drag_thumb)

    final = read_value(b, profile)
    print(f"\nfinal {VAR} = {final}  (baseline {base})")
    b.terminate()
    print("PROBE_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

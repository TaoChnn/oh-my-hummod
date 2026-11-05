# Probe #2 for the AVP v3.1.0 Lifestyle/Diet/Goal stepper:
#   (a) does the CURRENT Bridge.set_slider sequence (THUMBPOSITION + ENDSCROLL)
#       commit the model value, or does the ENDSCROLL notification undo it?
#   (b) map scroll position -> model value for the Salt stepper.
#
#   cp -r <avp engine> C:/path/to\engine_test_copies\r3_avp
#   python tests\probe_avp_diet_stepper2.py
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
OUT = r"C:/path/to/out\probe_avp_diet2"
PANEL = "Lifestyle/Diet/Goal"
VAR = "DietGoalElectrolytes.Na+_mMol/Day"
SALT_CTRL_ID = 10033

user32 = ctypes.windll.user32
WM_HSCROLL, WM_COMMAND = 0x0114, 0x0111
SB_LINERIGHT, SB_LINELEFT, SB_THUMBPOSITION, SB_ENDSCROLL = 1, 0, 4, 8


def read_value(b, profile) -> float:
    os.makedirs(OUT, exist_ok=True)
    sol = os.path.join(OUT, "probe2.SOL")
    if os.path.exists(sol):
        os.remove(sol)
    b.save_file_dialog(profile.file["save_sol"], sol, tuple(profile.dialog_edit_ids))
    for k, v in parse_export(sol, {VAR.lower()}).items():
        if k.lower() == VAR.lower():
            return v
    return float("nan")


def main() -> int:
    profile = Profile.load("avphummod")
    b = Bridge(ENGINE)
    b.start(hidden=True)
    b.wait_ready()
    time.sleep(1.0)
    b.navigate(b.menu_tree().walk(PANEL).cmd_id)
    time.sleep(0.8)

    sliders = sorted([c for c in b.controls() if c.cls == "ScrollBar"],
                      key=lambda c: c.ctrl_id)
    salt = next(c for c in sliders if c.ctrl_id == SALT_CTRL_ID)
    parent = user32.GetParent(salt.hwnd)
    print(f"salt ctrl_id={salt.ctrl_id} hwnd={salt.hwnd} parent={parent}")
    print(f"baseline {VAR} = {read_value(b, profile)}\n")

    print("=== (a) current Bridge.set_slider sequence (THUMBPOSITION + ENDSCROLL) ===")
    for pos in (3, 6):
        user32.PostMessageW(parent, WM_HSCROLL, (pos << 16) | SB_THUMBPOSITION, salt.hwnd)
        time.sleep(0.06)
        user32.PostMessageW(parent, WM_HSCROLL, SB_ENDSCROLL, 0)
        user32.PostMessageW(salt.hwnd, WM_HSCROLL, SB_ENDSCROLL, 0)
        time.sleep(0.4)
        print(f"  THUMBPOSITION({pos}) + ENDSCROLL x2 -> {read_value(b, profile)}")

    print("\n=== (a2) THUMBPOSITION only (no ENDSCROLL) ===")
    for pos in (3, 6, 9):
        user32.PostMessageW(parent, WM_HSCROLL, (pos << 16) | SB_THUMBPOSITION, salt.hwnd)
        time.sleep(0.4)
        print(f"  THUMBPOSITION({pos}) only -> {read_value(b, profile)}")

    print("\n=== (b) position -> value map (THUMBPOSITION only) ===")
    mapping = {}
    for pos in list(range(0, 13)) + [14, 15, 16, 18, 20, 25, 30, 40, 60, 100]:
        user32.PostMessageW(parent, WM_HSCROLL, (pos << 16) | SB_THUMBPOSITION, salt.hwnd)
        time.sleep(0.25)
        v = read_value(b, profile)
        mapping[pos] = v
        print(f"  pos {pos:>4} -> {v}")

    print("\nmap:", {k: v for k, v in mapping.items()})
    b.terminate()
    print("PROBE2_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

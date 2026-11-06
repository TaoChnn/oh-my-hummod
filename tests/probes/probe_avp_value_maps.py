# Probe #3 for AVP v3.1.0: exact scroll-position -> model-value maps for the
# steppers this experiment needs, so the GUI route becomes reproducible and the
# profile can carry real facts instead of "does not commit".
#
#   Salt    (Lifestyle/Diet/Goal, ctrl_id 10033)  -> DietGoalElectrolytes.Na+_mMol/Day
#   KCl     (Lifestyle/Diet/Goal, ctrl_id 10036)  -> DietGoalElectrolytes.KCl_mMol/Day
#   Block   (Hormones/Renin/A2,     ctrl_id 6792) -> A2Pool.Block(%)
#
#   cp -r <avp engine> C:/path/to\engine_test_copies\r3_avp
#   python tests\probe_avp_value_maps.py
import ctypes
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from oh_my_hummod.bridge import Bridge            # noqa: E402
from oh_my_hummod.profile import Profile          # noqa: E402
from oh_my_hummod.solver import parse_export      # noqa: E402

ENGINE = os.environ.get("HUMMOD_ENGINE_DIR", r"C:/path/to\engine_test_copies\r3_avp")
OUT = r"C:/path/to/out\probe_avp_maps"

user32 = ctypes.windll.user32
WM_HSCROLL = 0x0114
SB_THUMBPOSITION = 4

TARGETS = [
    ("Salt", "Lifestyle/Diet/Goal", 10033, "DietGoalElectrolytes.Na+_mMol/Day", 0, 60),
    ("KCl", "Lifestyle/Diet/Goal", 10036, "DietGoalElectrolytes.KCl_mMol/Day", 0, 30),
    ("Block", "Hormones/Renin/A2", 6792, "A2Pool.Block(%)", 0, 40),
]


def read_value(b, profile, var) -> float:
    os.makedirs(OUT, exist_ok=True)
    sol = os.path.join(OUT, "maps.SOL")
    if os.path.exists(sol):
        os.remove(sol)
    b.save_file_dialog(profile.file["save_sol"], sol, tuple(profile.dialog_edit_ids))
    for k, v in parse_export(sol, {var.lower()}).items():
        if k.lower() == var.lower():
            return v
    return float("nan")


def main() -> int:
    profile = Profile.load("avphummod")
    b = Bridge(ENGINE)
    b.start(hidden=True)
    b.wait_ready()
    time.sleep(1.0)
    maps = {}
    for label, panel, ctrl_id, var, lo, hi in TARGETS:
        b.navigate(b.menu_tree().walk(panel).cmd_id)
        time.sleep(0.8)
        sliders = sorted([c for c in b.controls() if c.cls == "ScrollBar"],
                          key=lambda c: c.ctrl_id)
        c = next((s for s in sliders if s.ctrl_id == ctrl_id), None)
        if c is None:
            print(f"!! {label}: ctrl_id {ctrl_id} not found on {panel}")
            continue
        parent = user32.GetParent(c.hwnd)
        seq = []
        for pos in range(lo, hi + 1):
            user32.PostMessageW(parent, WM_HSCROLL, (pos << 16) | SB_THUMBPOSITION, c.hwnd)
            time.sleep(0.2)
            seq.append(read_value(b, profile, var))
        maps[label] = {"panel": panel, "ctrl_id": ctrl_id, "var": var, "values": seq}
        print(f"\n=== {label} ({panel} ctrl_id={ctrl_id}) -> {var} ===")
        print("  " + ", ".join(f"{i}:{v:g}" for i, v in enumerate(seq)))
    with open(os.path.join(OUT, "value_maps.json"), "w", encoding="utf-8") as fh:
        json.dump(maps, fh, indent=1)
    print("\nwrote", os.path.join(OUT, "value_maps.json"))
    b.terminate()
    print("PROBE3_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

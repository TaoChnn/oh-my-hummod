# Probe 2: why did the Shock Now click not register? Dump button states,
# try clicking while the simulation is running, and compare message variants.
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from oh_my_hummod.bridge import Bridge, user32
from oh_my_hummod.profile import Profile
from oh_my_hummod.solver import parse_export

OUT = r"C:/path/to/out\mcp_new"
p = Profile.load("hummod_3.0.4")
b = Bridge(r"C:/path/to/engine")
print("attach:", b.attach(), "pid:", b.pid)
tree = b.menu_tree()

vf = tree.walk("Trauma/Ventricular Fibrillation")
b.navigate(vf.cmd_id)
time.sleep(0.4)
radios = sorted([c for c in b.controls() if c.is_radio], key=lambda c: c.ctrl_id)
actions = sorted([c for c in b.controls()
                  if c.cls == "Button" and c.text.strip() == "!"], key=lambda c: c.ctrl_id)
for c in actions:
    print(f"action ctrl_id={c.ctrl_id} vis={c.visible} en={c.enabled}")
print("radios:", [(r.ctrl_id, r.enabled) for r in radios])

# make sure fibrillation is on
if not any(r.checked for r in radios):
    b.press(radios[1].hwnd)
    time.sleep(0.5)


def shocks(tag):
    sol = os.path.join(OUT, f"probe_{tag}.SOL")
    if os.path.exists(sol):
        os.remove(sol)
    b.save_file_dialog(p.file["save_sol"], sol, tuple(p.dialog_edit_ids))
    v = parse_export(sol, {"heart-defibrillator.totalshocks", "heart-vfib.is_fibrillating", "system.x"})
    print(f"  [{tag}] {v}")
    return v


print("\n-- click while idle --")
s = shocks("idle_before")
b.press(actions[0].hwnd)
time.sleep(0.8)
s = shocks("idle_after")

print("\n-- click while running (Go 10 Sec then click) --")
b.command(tree.walk("Go/10 Sec").cmd_id)
time.sleep(0.5)  # simulation now running (Stop enabled)
b.press(actions[0].hwnd)
time.sleep(0.5)
b.press(actions[0].hwnd)  # second shock at a different sim step
# wait for finish
deadline = time.time() + 30
while time.time() < deadline:
    if not b.menu_item_enabled(p.stop_cmd_id):
        break
    time.sleep(0.2)
s = shocks("running_after")
print("PROBE_DONE")

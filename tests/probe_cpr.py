# Probe: CPR / VF page radios + action buttons (profile semantics extraction).
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from oh_my_hummod.bridge import Bridge

b = Bridge(r"C:/path/to/engine")
print("attach:", b.attach(), "pid:", b.pid)
tree = b.menu_tree()

for panel_path in ("Intervention/CPR", "Trauma/Ventricular Fibrillation"):
    node = tree.walk(panel_path)
    b.navigate(node.cmd_id)
    time.sleep(0.5)
    controls = sorted([c for c in b.controls()
                       if c.is_radio or (c.cls == "Button" and c.text.strip() == "!")],
                      key=lambda c: c.ctrl_id)
    print(f"\n== {panel_path} (id={node.cmd_id}) ==")
    for i, c in enumerate(controls):
        kind = "radio" if c.is_radio else "ACTION"
        print(f"  [{i}] {kind:6} ctrl_id={c.ctrl_id} checked={c.checked}")

# VF radio semantics live check: press ordinal 1 (On), SOL-verify Vfib switch
vf = tree.walk("Trauma/Ventricular Fibrillation")
b.navigate(vf.cmd_id)
radios = sorted([c for c in b.controls() if c.is_radio], key=lambda c: c.ctrl_id)
b.press(radios[1].hwnd)
time.sleep(0.6)
from oh_my_hummod.profile import Profile
p = Profile.load("hummod_3.0.4")
from oh_my_hummod.solver import parse_export
out = r"C:/path/to/out\mcp_new"
sol = os.path.join(out, "vf_on.SOL")
if os.path.exists(sol):
    os.remove(sol)
b.save_file_dialog(p.file["save_sol"], sol, tuple(p.dialog_edit_ids))
sw = [k for k in parse_export(sol) if "ib" in k.lower() or "fibr" in k.lower()]
vals = parse_export(sol, {k.lower() for k in sw})
print("\nVF On -> switched vars:", vals)

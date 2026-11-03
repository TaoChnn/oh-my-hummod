# Probe 3: show the engine window, navigate to VF, screenshot the page.
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from oh_my_hummod.bridge import Bridge, user32

b = Bridge(r"C:/path/to/engine")
print("attach:", b.attach())
user32.ShowWindow(b.main, 9)  # SW_RESTORE
time.sleep(0.5)
tree = b.menu_tree()
vf = tree.walk("Trauma/Ventricular Fibrillation")
b.navigate(vf.cmd_id)
time.sleep(0.6)
radios = sorted([c for c in b.controls() if c.is_radio], key=lambda c: c.ctrl_id)
actions = sorted([c for c in b.controls()
                  if c.cls == "Button" and c.text.strip() == "!"], key=lambda c: c.ctrl_id)
for c in actions:
    print(f"action ctrl_id={c.ctrl_id} vis={c.visible} en={c.enabled} bounds=({c.left},{c.top},{c.right},{c.bottom})")
for c in radios:
    print(f"radio  ctrl_id={c.ctrl_id} vis={c.visible} en={c.enabled} checked={c.checked}")

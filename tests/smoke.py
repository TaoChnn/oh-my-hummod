# Smoke test for the pure-Python bridge against a live 3.0.4 engine.
import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from oh_my_hummod.bridge import Bridge          # noqa: E402
from oh_my_hummod.profile import Profile        # noqa: E402
from oh_my_hummod.solver import parse_sol       # noqa: E402

ENGINE_DIR = os.environ.get("HUMMOD_ENGINE_DIR", r"C:/path/to/engine")
OUT = os.environ.get("HUMMOD_OUT", r"C:/path/to/out\mcp_new")

p = Profile.load("hummod_3.0.4")
b = Bridge(ENGINE_DIR, exe_name=p.exe_names[0])
if not b.attach():
    print("engine not running; starting...")
    print("pid:", b.start())
b.wait_ready()
print("attached pid:", b.pid)

tree = b.menu_tree()
print("\n-- top-level menu --")
for item in tree.children:
    print(f"  {item.label!r:28} id={item.cmd_id} pos={item.position} enabled={item.enabled}")

go = tree.find("Go")
print("\n-- Go children (first 8) --")
for c in go.children[:8]:
    print(f"  {c.label!r:12} id={c.cmd_id}")

# page ids: discovery-based lookup for Trauma/Hemorrhage
node = tree.walk("Trauma/Hemorrhage")
print("\nTrauma/Hemorrhage cmd_id =", node.cmd_id, "(profile says", p.page_ids.get("Trauma/Hemorrhage"), ")")

b.navigate(node.cmd_id)
time.sleep(0.5)
radios = sorted([c for c in b.controls() if c.is_radio], key=lambda c: c.ctrl_id)
print("radios on page:", [(r.ctrl_id, r.text.strip()[:12]) for r in radios])

# toggle Switch On (ordinal 1), verify via SOL
b.press(radios[1].hwnd)
time.sleep(0.6)
os.makedirs(OUT, exist_ok=True)
sol1 = os.path.join(OUT, "smoke_on.SOL")
b.save_file_dialog(p.file["save_sol"], sol1, tuple(p.dialog_edit_ids))
v1 = parse_sol(sol1, {"hemorrhage.switch", "hemorrhage.targetrate", "system.x"})
print("after ON :", v1)

b.press(radios[0].hwnd)
time.sleep(0.6)
sol0 = os.path.join(OUT, "smoke_off.SOL")
b.save_file_dialog(p.file["save_sol"], sol0, tuple(p.dialog_edit_ids))
v0 = parse_sol(sol0, {"hemorrhage.switch"})
print("after OFF:", v0)

# restart settles
cmd_restart = tree.walk("Restart").cmd_id
b.command(cmd_restart)
print("restart idle after", round(b.wait_idle(p.stop_cmd_id, 60), 1), "s")

assert v1["Hemorrhage.Switch"] == 1.0, "Switch On failed"
assert v0["Hemorrhage.Switch"] == 0.0, "Switch Off failed"
print("\nSMOKE_OK")

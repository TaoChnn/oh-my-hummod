# Probe 3: QCP two-phase wait_idle + Save ICs dialog control discovery.
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "..")))
from oh_my_hummod.bridge import Bridge

ENGINE = os.environ.get("HUMMOD_ENGINE_DIR") or sys.argv[1]
OUT = os.environ.get("HUMMOD_OUTDIR", "qcp-out")
os.makedirs(OUT, exist_ok=True)

b = Bridge(ENGINE, exe_name="QCP 2005.EXE")
print("attach:", b.attach(), "pid:", b.pid)
tree = b.menu_tree()

print("[go] 1 Min with two-phase wait...")
b.command(tree.walk("Go/1 Min").cmd_id)
print("idle after", round(b.wait_idle(tree.walk("Stop").cmd_id, 120), 1), "s")

print("[save ics] posting File/Save Initial Conditions (id 27)...")
user32 = __import__("oh_my_hummod.bridge", fromlist=["user32"]).user32
user32.PostMessageW(b.main, 0x0111, 27, 0)
time.sleep(1.5)
dlgs = b._visible_dialogs()
print("visible dialogs:", [hex(d) for d in dlgs])
if dlgs:
    kids = b._dialog_children(dlgs[0])
    for k in kids:
        print(f"  cls={k.cls!r:20} id={k.ctrl_id} text={k.text[:40]!r} vis={k.visible} en={k.enabled}")
    # try filling the first Edit and clicking IDOK
    edits = [k for k in kids if k.cls == "Edit" and k.visible]
    if edits:
        target = os.path.join(OUT, "qcp_state.ICs")
        if os.path.exists(target):
            os.remove(target)
        b.set_text(edits[0].hwnd, target)
        ok = [k for k in kids if k.cls == "Button" and k.ctrl_id == 1 and k.visible and k.enabled]
        if ok:
            b.press(ok[0].hwnd)
            time.sleep(2)
            print("saved:", os.path.exists(target), os.path.getsize(target) if os.path.exists(target) else 0)
            if os.path.exists(target):
                print("--- ICS head ---")
                print(open(target, "r", errors="replace").read(300))
                print("QCP_PROBE3_OK")
        else:
            print("no enabled IDOK button")
    else:
        print("no Edit control found in dialog")
else:
    print("no dialog appeared - maybe it saved directly or opened something else")

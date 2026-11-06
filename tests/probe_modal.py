# Inspect what the 1.6.1 event modal actually is (class, buttons, text).
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import ctypes
from ctypes import wintypes

from oh_my_hummod.bridge import Bridge, user32
from oh_my_hummod.profile import Profile

ENGINE = os.environ.get("HUMMOD_ENGINE_DIR") or sys.argv[1]
p = Profile.load("hummod_1.6.1")
b = Bridge(ENGINE)
if not b.attach():
    b.start()
    b.wait_ready(p.bind_marker)
print("pid:", b.pid)

tree = b.menu_tree()
b.navigate(tree.walk("Clinic/Myocardial Infarction").cmd_id)
time.sleep(0.5)
sliders = sorted([c for c in b.controls() if c.cls == "ScrollBar"], key=lambda c: c.ctrl_id)
print("sliders:", [(s.ctrl_id, s.scroll_min, s.scroll_max) for s in sliders])
b.set_slider(sliders[0].hwnd, user32.GetParent(sliders[0].hwnd), 40, commit_endscroll=True)
time.sleep(1.0)

print("busy:", b.busy())
dlgs = b._visible_dialogs()
print("visible dialogs:", [hex(d) for d in dlgs])
for d in dlgs:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(d, buf, 256)
    tb = ctypes.create_unicode_buffer(512)
    res = ctypes.c_size_t()
    user32.SendMessageTimeoutW(d, 0x000D, 512, tb, 0x0002, 1000, ctypes.byref(res))
    print(f"  dialog class={buf.value!r} title={tb.value[:80]!r} enabled={bool(user32.IsWindowEnabled(d))}")
    for c in b._dialog_children(d):
        print(f"    child cls={c.cls!r} id={c.ctrl_id} text={c.text[:60]!r} vis={c.visible} en={c.enabled}")

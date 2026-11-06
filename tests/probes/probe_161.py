import os, sys, time, ctypes
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "..")))
from oh_my_hummod.bridge import Bridge, user32
from ctypes import wintypes

ENGINE = os.environ.get("HUMMOD_ENGINE_DIR") or sys.argv[1]
b = Bridge(ENGINE)
print("attach:", b.attach(), "pid:", b.pid)
if not b.pid:
    sys.exit("start engine first")

b.wait_ready("Startup")
print("enabled:", bool(user32.IsWindowEnabled(b.main)))

def statusbar_text(hwnd):
    # MSCTLS_STATUSBAR32 of main window
    for c in b.controls():
        if "statusbar" in c.cls.lower():
            return c.text
    return "(no statusbar)"

print("statusbar:", statusbar_text(b.main)[:120])

for attempt in (1, 2):
    print(f"--- navigate attempt {attempt} ---")
    res = ctypes.c_size_t()
    ok = user32.SendMessageTimeoutW(b.main, 0x0111, 532, 0, 0x0002, 120000, ctypes.byref(res))
    print("SendMessageTimeout returned:", bool(ok))
    time.sleep(1)
    print("statusbar:", statusbar_text(b.main)[:120])
    print("enabled:", bool(user32.IsWindowEnabled(b.main)))

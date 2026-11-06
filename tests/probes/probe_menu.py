import ctypes, sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "..")))
from ctypes import wintypes
from oh_my_hummod.bridge import Bridge, user32

b = Bridge(r"C:/path/to/engine")
ok = b.attach()
print("attach:", ok, "pid:", b.pid, "main:", hex(b.main) if b.main else None)

menu = user32.GetMenu(b.main)
print("GetMenu:", hex(menu) if menu else None, "count:", user32.GetMenuItemCount(menu))

# enumerate ALL top-level windows of the pid, note which have menus
@ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
def on_w(hwnd, _l):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == b.pid and user32.IsWindowVisible(hwnd):
        m = user32.GetMenu(hwnd)
        t = ctypes.create_unicode_buffer(128)
        user32.GetWindowTextW(hwnd, t, 128)
        print(f"  vis window hwnd={hex(hwnd)} class_unknown title={t.value!r} menu={hex(m) if m else None} count={user32.GetMenuItemCount(m) if m else '-'}")
    return True

user32.EnumWindows(on_w, 0)

# also enumerate with GetMenuItemID on first 30 positions to see what count really holds
if menu:
    names = []
    for i in range(30):
        buf = ctypes.create_unicode_buffer(64)
        n = user32.GetMenuStringW(menu, i, buf, 64, 0x400)
        if not n:
            break
        names.append(buf.value.replace("&", ""))
    print("items by position:", names)

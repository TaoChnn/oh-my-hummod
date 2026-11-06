# Generic probe for an unknown engine EXE: enumerate windows, menus, controls.
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import ctypes
from ctypes import wintypes

from oh_my_hummod.bridge import user32, kernel32

ENGINE_DIR = sys.argv[1] if len(sys.argv) > 1 else \
    (os.environ.get("HUMMOD_ENGINE_DIR") or sys.argv[1])
EXE = sys.argv[2] if len(sys.argv) > 2 else "QCP 2005.EXE"

target = os.path.join(ENGINE_DIR, EXE)
p = os.popen(f'start "" "{target}"', "w") if False else None
import subprocess
subprocess.Popen([target], cwd=ENGINE_DIR)
print("launched", EXE)

deadline = time.time() + 25
pid_found = None
while time.time() < deadline and not pid_found:
    time.sleep(0.5)
    # find pid by exe path
    import psutil
    for proc in psutil.process_iter(["pid", "exe"]):
        try:
            if proc.info["exe"] and proc.info["exe"].lower() == target.lower():
                pid_found = proc.info["pid"]
                break
        except Exception:
            pass
if not pid_found:
    print("process not found"); sys.exit(1)
print("pid:", pid_found)
time.sleep(3)


def exe_path(pid):
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    buf = ctypes.create_unicode_buffer(1024)
    size = wintypes.DWORD(1024)
    ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
    kernel32.CloseHandle(h)
    return buf.value if ok else None


windows = []

@ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
def on_window(hwnd, _l):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value != pid_found:
        return True
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    title = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title, 256)
    menu = user32.GetMenu(hwnd)
    count = user32.GetMenuItemCount(menu) if menu else 0
    windows.append({
        "hwnd": hwnd, "cls": cls.value, "title": title.value,
        "visible": bool(user32.IsWindowVisible(hwnd)),
        "enabled": bool(user32.IsWindowEnabled(hwnd)),
        "menu": bool(menu), "menu_count": count,
    })
    return True

user32.EnumWindows(on_window, 0)
print(f"\n== top-level windows ({len(windows)}) ==")
for w in windows:
    if w["visible"] or w["menu"]:
        print(f"  hwnd=0x{w['hwnd']:X} cls={w['cls']!r} title={w['title'][:50]!r} "
              f"vis={w['visible']} en={w['enabled']} menu={w['menu']}({w['menu_count']})")

menud = next((w for w in windows if w["menu"]), None)
if menud:
    hmenu = user32.GetMenu(menud["hwnd"])

    def dump(hm, indent=2):
        n = user32.GetMenuItemCount(hm)
        for i in range(n):
            buf = ctypes.create_unicode_buffer(128)
            user32.GetMenuStringW(hm, i, buf, 128, 0x400)
            sub = user32.GetSubMenu(hm, i)
            cid = user32.GetMenuItemID(hm, i)
            print(" " * indent + f"{buf.value!r} id={'popup' if sub else cid}")
            if sub:
                dump(sub, indent + 2)

    print(f"\n== menu tree of hwnd=0x{menud['hwnd']:X} ==")
    dump(hmenu)
else:
    print("\nNO Win32 menu bar found - different UI framework; need UIA/other route")

# child control classes of the main visible window
mainw = next((w for w in windows if w["visible"] and (w["menu"] or w["title"])), None)
if mainw:
    classes = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def on_child(h, _l):
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, cls, 256)
        classes[cls.value] = classes.get(cls.value, 0) + 1
        return True

    user32.EnumChildWindows(mainw["hwnd"], on_child, 0)
    print(f"\n== child control classes of 0x{mainw['hwnd']:X} ==")
    for k, v in sorted(classes.items(), key=lambda kv: -kv[1]):
        print(f"  {k!r} x{v}")

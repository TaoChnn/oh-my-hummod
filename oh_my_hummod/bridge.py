"""Win32 message-level automation core for HumMod-family engines.

Drives a running engine EXE purely through public window messages
(WM_COMMAND / BM_CLICK / WM_SETTEXT / WM_HSCROLL): enumerate menus and
child controls, switch model pages, press buttons, run simulations and
automate the native file dialogs for SOL/ICS export. No engine source,
no memory access, no reverse engineering - the engine cannot tell these
messages from a user's mouse.

Everything here is engine-agnostic; version differences live in profiles
(see profile.py). All handle/ID discoveries happen at attach time.
"""
from __future__ import annotations

import ctypes
import re
import subprocess
import time
from ctypes import wintypes
from dataclasses import dataclass, field

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_CLOSE = 0x0010
WM_SETTEXT = 0x000C
WM_COMMAND = 0x0111
WM_HSCROLL = 0x0114
BM_CLICK = 0x00F5

MF_BYCOMMAND = 0x0000
MF_BYPOSITION = 0x0400
MFS_MASK = 0x0003  # MFS_GRAYED | MFS_DISABLED

SB_THUMBPOSITION = 4
SB_ENDSCROLL = 8
WM_GETTEXT = 0x000D


@dataclass
class Control:
    hwnd: int
    ctrl_id: int
    cls: str
    text: str
    visible: bool
    enabled: bool
    style: int
    scroll_pos: int = 0
    scroll_min: int = 0
    scroll_max: int = 0
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0
    checked: bool = False

    @property
    def y_center(self) -> int:
        return (self.top + self.bottom) // 2

    @property
    def is_radio(self) -> bool:
        # BS_RADIOBUTTON / BS_AUTORADIOBUTTON low style bits
        return (self.style & 0x0F) in (0x04, 0x09)

    @property
    def is_checkbox(self) -> bool:
        return (self.style & 0x0F) in (0x02, 0x03, 0x05, 0x06)

    @property
    def is_push(self) -> bool:
        return (self.style & 0x0F) in (0x00, 0x01, 0x03)


@dataclass
class MenuItem:
    label: str
    cmd_id: int | None  # None = submenu (popup)
    position: int
    enabled: bool
    children: list["MenuItem"] = field(default_factory=list)

    def find(self, label: str) -> "MenuItem | None":
        want = label.strip().lower()
        for item in self.children:
            if item.label.strip().lower() == want:
                return item
        return None

    def walk(self, path: str) -> "MenuItem":
        """Resolve 'Go/10 Min' against this node's subtree."""
        node = self
        for seg in [s.strip() for s in path.split("/") if s.strip()]:
            nxt = node.find(seg)
            if nxt is None:
                raise KeyError(f"menu path not found: {seg!r} in {path!r}")
            node = nxt
        return node


class Bridge:
    """Attach to a running engine and drive it with window messages."""

    def __init__(self, engine_dir: str, exe_name: str = "HumMod.EXE"):
        self.engine_dir = engine_dir
        self.exe_name = exe_name
        self.pid: int | None = None
        self.main: int | None = None  # hwnd of the window that owns the menu bar

    # ---------- process attach ----------

    def attach(self) -> bool:
        """Find the engine process by exe path and locate its menu window."""
        target = self._engine_exe_path().lower()
        found: list[tuple[int, int]] = []  # (pid, hwnd-with-menu)

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def on_window(hwnd, _l):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value:
                path = self._process_exe_path(pid.value)
                if path and path.lower() == target:
                    if user32.GetMenu(hwnd):
                        found.append((pid.value, hwnd))
            return True

        user32.EnumWindows(on_window, 0)
        if not found:
            return False
        pids = {pid for pid, _ in found}
        if len(pids) != 1:
            raise RuntimeError(f"expected one engine process, found {sorted(pids)}")
        self.pid, self.main = found[0]
        return True

    def start(self, hidden: bool = True) -> int:
        """Launch the engine EXE; return the new process pid."""
        import os
        flags = 0x00000008  # DETACHED_PROCESS
        si = subprocess.STARTUPINFO()
        if hidden:
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE
        p = subprocess.Popen([self._engine_exe_path()], cwd=self.engine_dir,
                             creationflags=flags, startupinfo=si)
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.attach():
                return self.pid
            time.sleep(0.3)
        raise RuntimeError("engine started but its window never appeared")

    def _engine_exe_path(self) -> str:
        import os
        return os.path.join(self.engine_dir, self.exe_name)

    @staticmethod
    def _process_exe_path(pid: int) -> str | None:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            # QueryFullProcessImageNameW avoids needing PROCESS_QUERY_INFORMATION
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value
            return None
        finally:
            kernel32.CloseHandle(h)

    # ---------- menus ----------

    def menu_tree(self) -> MenuItem:
        """Enumerate the full menu bar as a tree of MenuItems."""
        menu = user32.GetMenu(self.main)
        if not menu:
            raise RuntimeError("engine window has no menu bar")
        root = MenuItem(label="/", cmd_id=None, position=-1, enabled=True)
        self._menu_children(menu, root)
        return root

    def wait_ready(self, bound_marker: str = "Sizing", timeout: float = 60.0) -> None:
        """Wait until the model finishes binding.

        Freshly started engines show only the File..Help row; the model-page row
        (Circulation ... Sizing) is populated when 'Starting Model ... Binding ...
        Done' completes. Poll for the last row's marker label.
        """
        deadline = time.time() + timeout
        last_count = -1
        while time.time() < deadline:
            tree = self.menu_tree()
            if tree.find(bound_marker) is not None:
                return
            if len(tree.children) == last_count and len(tree.children) > 7:
                return  # count stable above the File..Help row: accept as bound
            last_count = len(tree.children)
            time.sleep(0.4)
        raise TimeoutError(f"engine model binding not observed within {timeout}s")

    def _menu_children(self, hmenu: int, node: MenuItem) -> None:
        count = user32.GetMenuItemCount(hmenu)
        for i in range(count):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetMenuStringW(hmenu, i, buf, 256, MF_BYPOSITION)
            label = buf.value.replace("&", "")
            sub = user32.GetSubMenu(hmenu, i)
            cmd = user32.GetMenuItemID(hmenu, i)
            state = user32.GetMenuState(hmenu, i, MF_BYPOSITION)
            item = MenuItem(label=label,
                            cmd_id=None if cmd in (0xFFFFFFFF, -1) else int(cmd) & 0xFFFF,
                            position=i,
                            enabled=(state & MFS_MASK) == 0)
            if sub:
                self._menu_children(sub, item)
            node.children.append(item)

    def find_cmd_id(self, menu: MenuItem, label: str) -> int:
        """Locate a top-level item by label and return its command id."""
        item = menu.find(label)
        if item is None or item.cmd_id is None:
            raise KeyError(f"menu item {label!r} not found or has no command id")
        return item.cmd_id

    def menu_item_enabled(self, cmd_id: int) -> bool:
        state = user32.GetMenuState(user32.GetMenu(self.main), cmd_id, MF_BYCOMMAND)
        if state == -1:
            raise KeyError(f"menu command id {cmd_id} not found")
        return (state & MFS_MASK) == 0

    # ---------- controls ----------

    def controls(self) -> list[Control]:
        out: list[Control] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def on_child(hwnd, _l):
            out.append(self._control_info(hwnd))
            return True

        user32.EnumChildWindows(self.main, on_child, 0)
        return out

    def _control_info(self, hwnd: int) -> Control:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        cls = buf.value
        tb = ctypes.create_unicode_buffer(65536)
        res = ctypes.c_size_t()
        user32.SendMessageTimeoutW(hwnd, WM_GETTEXT, 65536, tb,
                                   0x0002, 1000, ctypes.byref(res))
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        pos = mn = mx = 0
        check = 0
        if cls == "ScrollBar":
            pos = user32.GetScrollPos(hwnd, 0)
            rng = (wintypes.INT(), wintypes.INT())
            user32.GetScrollRange(hwnd, 0, ctypes.byref(rng[0]), ctypes.byref(rng[1]))
            mn, mx = rng[0].value, rng[1].value
        if cls == "Button":
            check = user32.SendMessageW(hwnd, 0x00F1, 0, 0)  # BM_GETCHECK
        return Control(hwnd=hwnd, ctrl_id=user32.GetDlgCtrlID(hwnd), cls=cls,
                       text=tb.value, visible=bool(user32.IsWindowVisible(hwnd)),
                       enabled=bool(user32.IsWindowEnabled(hwnd)),
                       style=user32.GetWindowLongW(hwnd, -16),
                       scroll_pos=pos, scroll_min=mn, scroll_max=mx,
                       left=rect.left, top=rect.top, right=rect.right, bottom=rect.bottom,
                       checked=bool(check))

    # ---------- actions ----------

    def command(self, cmd_id: int) -> None:
        """Post a top-level menu command (Restart=7, Go durations, ...)."""
        if not user32.IsWindowEnabled(self.main):
            raise RuntimeError("engine has an open modal dialog")
        if not user32.PostMessageW(self.main, WM_COMMAND, cmd_id, 0):
            raise RuntimeError("command delivery failed")

    def navigate(self, page_cmd_id: int, timeout: float = 30.0) -> None:
        """Switch model page (menu command) and wait for the page to load.

        Older engines may accept the command only after their page handlers
        finish binding, so a timeout here is retried rather than fatal.
        """
        if not user32.IsWindowEnabled(self.main):
            raise RuntimeError("engine has an open modal dialog")
        res = ctypes.c_size_t()
        for attempt in range(3):
            if user32.SendMessageTimeoutW(self.main, WM_COMMAND, page_cmd_id, 0,
                                          0x0002, int(timeout * 1000),
                                          ctypes.byref(res)) != 0:
                return
            time.sleep(2.0)
        raise RuntimeError("page did not finish loading")

    def press(self, hwnd: int) -> None:
        user32.PostMessageW(hwnd, BM_CLICK, 0, 0)

    def set_text(self, hwnd: int, value: str) -> None:
        res = ctypes.c_size_t()
        if user32.SendMessageTimeoutW(hwnd, WM_SETTEXT, 0,
                                      ctypes.create_unicode_buffer(value),
                                      0x0002, 2000, ctypes.byref(res)) == 0:
            raise RuntimeError("text update timed out")

    def set_slider(self, ctrl_hwnd: int, parent_hwnd: int, pos: int, commit_endscroll: bool = True) -> None:
        """Move a ScrollBar thumb; commit behaviour is engine-dependent (see profile)."""
        user32.PostMessageW(parent_hwnd, WM_HSCROLL,
                            (pos << 16) | SB_THUMBPOSITION, ctrl_hwnd)
        time.sleep(0.06)
        if commit_endscroll:
            user32.PostMessageW(parent_hwnd, WM_HSCROLL, SB_ENDSCROLL, 0)
            user32.PostMessageW(ctrl_hwnd, WM_HSCROLL, SB_ENDSCROLL, 0)
        time.sleep(0.1)

    # ---------- run / completion ----------

    def wait_idle(self, stop_cmd_id: int, timeout: float = 600.0) -> float:
        """Poll until the Stop menu item grays out (simulation finished)."""
        t0 = time.time()
        time.sleep(0.4)
        while time.time() - t0 < timeout:
            if not self.menu_item_enabled(stop_cmd_id):
                return time.time() - t0
            time.sleep(0.3)
        raise TimeoutError(f"simulation did not finish within {timeout}s")

    def busy(self) -> bool:
        return not bool(user32.IsWindowEnabled(self.main))

    # ---------- dialogs ----------

    def dismiss_modals(self) -> list[int]:
        found: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def on_window(hwnd, _l):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == self.pid and user32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, buf, 256)
                if buf.value == "#32770":
                    found.append(hwnd)
            return True

        user32.EnumWindows(on_window, 0)
        for d in found:
            user32.PostMessageW(d, WM_CLOSE, 0, 0)
            user32.PostMessageW(d, WM_COMMAND, 2, 0)  # IDCANCEL

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def on_child(h, _l, _d=d):
                cid = user32.GetDlgCtrlID(h)
                if cid in (1, 2):  # IDOK / IDCANCEL
                    user32.PostMessageW(h, BM_CLICK, 0, 0)
                    return False
                return True

            user32.EnumChildWindows(d, on_child, 0)
        time.sleep(0.3)
        return found

    def save_file_dialog(self, command_id: int, target_path: str,
                         edit_ids: tuple[int, ...] = (1001, 1148),
                         timeout: float = 60.0) -> None:
        """Trigger File > Save Solution/ICs and drive the native Save dialog."""
        import os
        target_path = os.path.abspath(target_path)
        if os.path.exists(target_path):
            os.remove(target_path)
        if self.busy():
            raise RuntimeError("engine busy or modal is open")
        user32.PostMessageW(self.main, WM_COMMAND, command_id, 0)
        dlg = self._wait_dialog(timeout)
        edit = button = None
        deadline = time.time() + timeout
        while time.time() < deadline:
            dialogs = self._visible_dialogs()
            if len(dialogs) == 1:
                dlg = dialogs[0]
                kids = self._dialog_children(dlg)
                edits = [k for k in kids if k.cls == "Edit" and k.ctrl_id in edit_ids and k.visible]
                buttons = [k for k in kids if k.cls == "Button" and k.ctrl_id == 1 and k.visible and k.enabled]
                if len(edits) == 1 and len(buttons) == 1:
                    edit, button = edits[0], buttons[0]
                    break
            time.sleep(0.05)
        if edit is None or button is None:
            raise RuntimeError("unrecognized file dialog; inspect the engine")
        self.set_text(edit.hwnd, target_path)
        user32.PostMessageW(button.hwnd, BM_CLICK, 0, 0)
        # The engine keeps writing after the dialog closes; SOL vars are written
        # alphabetically, so wait for the closing tag and a stable size.
        deadline = time.time() + timeout
        last_size = -1
        while time.time() < deadline:
            if os.path.exists(target_path) and not self.busy():
                try:
                    size = os.path.getsize(target_path)
                    if size == last_size and size > 0:
                        with open(target_path, "rb") as f:
                            f.seek(max(0, size - 64))
                            tail = f.read().decode("utf-8", "replace")
                        if "</solution>" in tail or "</ics>" in tail.lower():
                            return
                    last_size = size if size != last_size else last_size
                except OSError:
                    pass
            time.sleep(0.1)
        raise RuntimeError("export did not complete; inspect the engine")

    def _visible_dialogs(self) -> list[int]:
        out: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def on_window(hwnd, _l):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == self.pid and user32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, buf, 256)
                if buf.value == "#32770":
                    out.append(hwnd)
            return True

        user32.EnumWindows(on_window, 0)
        return out

    def _dialog_children(self, dlg: int) -> list[Control]:
        out: list[Control] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def on_child(hwnd, _l):
            out.append(self._control_info(hwnd))
            return True

        user32.EnumChildWindows(dlg, on_child, 0)
        return out

    def _wait_dialog(self, timeout: float) -> int:
        deadline = time.time() + timeout
        while time.time() < deadline:
            dlgs = self._visible_dialogs()
            if len(dlgs) == 1:
                return dlgs[0]
            if len(dlgs) > 1:
                raise RuntimeError("unexpected multiple dialogs")
            time.sleep(0.05)
        raise RuntimeError("file dialog did not open")

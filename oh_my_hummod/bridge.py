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
import os
import re
import subprocess
import time
from ctypes import wintypes
from dataclasses import dataclass, field

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# SendMessageW takes a pointer lParam (e.g. LB_GETTEXT's buffer); without
# explicit argtypes ctypes truncates it to a 32-bit int on 64-bit Python.
user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                               ctypes.c_size_t, ctypes.c_size_t]
user32.SendMessageW.restype = ctypes.c_ssize_t

# 64-bit safe handle handling: without explicit restypes ctypes truncates
# kernel handles to 32 bits, which breaks OpenProcess/CloseHandle.
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.TerminateProcess.restype = wintypes.BOOL
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.GetExitCodeProcess.restype = wintypes.BOOL
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]

WM_CLOSE = 0x0010
WM_SETTEXT = 0x000C
WM_COMMAND = 0x0111
WM_HSCROLL = 0x0114
WM_NULL = 0x0000
BM_CLICK = 0x00F5
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDBLCLK = 0x0203

MF_BYCOMMAND = 0x0000
MF_BYPOSITION = 0x0400
MFS_MASK = 0x0003  # MFS_GRAYED | MFS_DISABLED

SB_THUMBPOSITION = 4
SB_ENDSCROLL = 8
SB_LINELEFT = 0
WM_GETTEXT = 0x000D
BM_GETCHECK = 0x00F0   # read the check state (BM_SETCHECK is 0x00F1)
BM_SETCHECK = 0x00F1


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
    own_visible: bool = False   # WS_VISIBLE of the control itself

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

    # BS_* type bits (style & 0x0F)
    BTN_TYPES = {0x00: "push", 0x01: "push-default", 0x02: "checkbox",
                 0x03: "auto-checkbox", 0x04: "radio", 0x05: "3state",
                 0x06: "auto-3state", 0x07: "groupbox", 0x08: "groupbox",
                 0x09: "auto-radio", 0x0A: "multi-choice", 0x0B: "ownerdraw",
                 0x0C: "groupbox", 0x0D: "groupbox", 0x0E: "groupbox",
                 0x0F: "ownerdraw-radio"}

    @property
    def button_type(self) -> str:
        """Human name of the BS_* style bits (style & 0x0F)."""
        return self.BTN_TYPES.get(self.style & 0x0F, f"type-0x{self.style & 0x0F:02X}")

    @property
    def check_state_readable(self) -> bool:
        """Whether BM_GETCHECK returns the real selection for this control.

        Windows only keeps a check state for the standard box/radio styles.
        Owner-drawn buttons (BS_OWNERDRAW / BS_OWNERDWRADIOBUTTON) keep the
        state in the application, so BM_GETCHECK always answers 0 and a
        post-click readback is meaningless.
        """
        return (self.style & 0x0F) in (0x02, 0x03, 0x04, 0x05, 0x06, 0x09)


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

    def __init__(self, engine_dir: str, exe_name: str | None = None):
        self.engine_dir = engine_dir
        self.exe_name = exe_name  # optional filter; discovered from the process if None
        self.pid: int | None = None
        self.main: int | None = None  # hwnd of the window that owns the menu bar

    # ---------- process attach ----------

    def attach(self) -> bool:
        """Find the engine process by its folder and locate its menu window.

        When exe_name is set, only processes running that exact EXE match;
        otherwise any EXE inside engine_dir matches (so builds like QCP's
        'QCP 2005.EXE' are found without knowing the name up front).
        """
        target = os.path.abspath(self.engine_dir).lower()
        found: list[tuple[int, int, str]] = []  # (pid, hwnd-with-menu, exe path)

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def on_window(hwnd, _l):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value:
                path = self._process_exe_path(pid.value)
                if path:
                    d = os.path.dirname(path).lower()
                    name = os.path.basename(path)
                    if d == target and (not self.exe_name or name.lower() == self.exe_name.lower()):
                        if user32.GetMenu(hwnd):
                            found.append((pid.value, hwnd, path))
            return True

        user32.EnumWindows(on_window, 0)
        if not found:
            return False
        pids = {pid for pid, _, _ in found}
        if len(pids) != 1:
            raise RuntimeError(f"expected one engine process, found {sorted(pids)}")
        self.pid, self.main, exe = found[0]
        self.exe_name = os.path.basename(exe)
        return True

    def start(self, hidden: bool = True) -> int:
        """Launch the engine EXE; return the new process pid.

        If exe_name was not given, the folder must contain exactly one .exe
        (other builds like Modular AVP ship several and need an explicit name).
        """
        exe = self.exe_name
        if not exe:
            exes = [f for f in os.listdir(self.engine_dir) if f.lower().endswith(".exe")]
            if len(exes) != 1:
                pref = [f for f in exes if f.lower() == "hummod.exe"]
                if len(pref) == 1:
                    exes = pref  # main binary beats helper EXEs (e.g. Model Navigator.EXE)
            if len(exes) != 1:
                raise RuntimeError(f"cannot pick an EXE in {self.engine_dir}: {exes}")
            exe = exes[0]
            self.exe_name = exe
        flags = 0x00000008  # DETACHED_PROCESS
        si = subprocess.STARTUPINFO()
        if hidden:
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE
        p = subprocess.Popen([os.path.join(self.engine_dir, exe)], cwd=self.engine_dir,
                             creationflags=flags, startupinfo=si)
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.attach():
                return self.pid
            time.sleep(0.3)
        raise RuntimeError("engine started but its window never appeared")

    def _engine_exe_path(self) -> str:
        return os.path.join(self.engine_dir, self.exe_name or "")

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

        The marker can appear a moment before the page handlers accept commands,
        so also require the main window to be enabled and settle briefly.
        """
        deadline = time.time() + timeout
        last_count = -1
        while time.time() < deadline:
            tree = self.menu_tree()
            if tree.find(bound_marker) is not None:
                break
            if len(tree.children) == last_count and len(tree.children) > 7:
                break  # count stable above the File..Help row: accept as bound
            last_count = len(tree.children)
            time.sleep(0.4)
        else:
            raise TimeoutError(f"engine model binding not observed within {timeout}s")

        # wait until the engine actually accepts commands (no modal, window enabled)
        while time.time() < deadline:
            if not self.busy():
                break
            self.dismiss_modals()
            time.sleep(0.2)
        time.sleep(0.5)  # settle: page handlers bind just after the menu appears

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
            # BM_GETCHECK is 0x00F0; 0x00F1 is BM_SETCHECK - reading with it
            # would *write* (un-check) the control and report 0 every time.
            check = user32.SendMessageW(hwnd, BM_GETCHECK, 0, 0)
        style = user32.GetWindowLongW(hwnd, -16)
        return Control(hwnd=hwnd, ctrl_id=user32.GetDlgCtrlID(hwnd), cls=cls,
                       text=tb.value, visible=bool(user32.IsWindowVisible(hwnd)),
                       enabled=bool(user32.IsWindowEnabled(hwnd)),
                       style=style,
                       scroll_pos=pos, scroll_min=mn, scroll_max=mx,
                       left=rect.left, top=rect.top, right=rect.right, bottom=rect.bottom,
                       checked=bool(check),
                       own_visible=bool(style & 0x10000000))  # WS_VISIBLE

    # ---------- actions ----------

    def command(self, cmd_id: int) -> None:
        """Post a top-level menu command (Restart=7, Go durations, ...)."""
        self.ensure_ready()
        if not user32.PostMessageW(self.main, WM_COMMAND, cmd_id, 0):
            raise RuntimeError("command delivery failed")

    def navigate(self, page_cmd_id: int, timeout: float = 30.0) -> None:
        """Switch model page (menu command) and wait for the page to load.

        Older engines may accept the command only after their page handlers
        finish binding, so a timeout here is retried rather than fatal.
        """
        self.ensure_ready()
        res = ctypes.c_size_t()
        # short per-attempt timeout + more attempts: a cold engine may need a
        # moment before it accepts page commands, and one long wait would
        # stall the caller for the full timeout.
        attempts = max(3, int(timeout // 5) + 1)
        for attempt in range(attempts):
            if user32.SendMessageTimeoutW(self.main, WM_COMMAND, page_cmd_id, 0,
                                          0x0002, 5000,
                                          ctypes.byref(res)) != 0:
                return
            time.sleep(1.5)
        raise RuntimeError("page did not finish loading")

    def press(self, hwnd: int) -> None:
        self.ensure_ready()
        user32.PostMessageW(hwnd, BM_CLICK, 0, 0)

    def set_text(self, hwnd: int, value: str) -> None:
        res = ctypes.c_size_t()
        if user32.SendMessageTimeoutW(hwnd, WM_SETTEXT, 0,
                                      ctypes.create_unicode_buffer(value),
                                      0x0002, 2000, ctypes.byref(res)) == 0:
            raise RuntimeError("text update timed out")

    @staticmethod
    def _scroll_pos(ctrl_hwnd: int) -> int | None:
        return user32.GetScrollPos(ctrl_hwnd, 0)

    def set_slider(self, ctrl_hwnd: int, parent_hwnd: int, pos: int, commit_endscroll: bool = True) -> None:
        """Move a ScrollBar thumb; commit behaviour is engine-dependent (see profile).

        QCP 2005 ignores SB_THUMBPOSITION with position 0 (the value never
        commits to the minimum), so pos 0 is set by repeated SB_LINELEFT
        line-scrolls instead - each of those commits immediately, and
        SB_LINELEFT at 0 is a no-op. The control's reported thumb position can
        be unsynced (0) before QCP has painted the page, so never trust it to
        mean "already at 0": always overshoot with a fixed message budget.
        """
        if pos == 0:
            for _ in range(60):
                user32.PostMessageW(parent_hwnd, WM_HSCROLL, SB_LINELEFT, ctrl_hwnd)
                time.sleep(0.04)
            return
        user32.PostMessageW(parent_hwnd, WM_HSCROLL,
                            (pos << 16) | SB_THUMBPOSITION, ctrl_hwnd)
        time.sleep(0.06)
        if commit_endscroll:
            user32.PostMessageW(parent_hwnd, WM_HSCROLL, SB_ENDSCROLL, 0)
            user32.PostMessageW(ctrl_hwnd, WM_HSCROLL, SB_ENDSCROLL, 0)
        time.sleep(0.1)

    # ---------- run / completion ----------

    def ensure_ready(self, dismiss: bool = True) -> list[int]:
        """Make sure the engine can accept commands.

        Some engines pop event modals on parameter changes (1.6.1 shows e.g.
        'ECG shows S-T segment shift.'); while such a dialog is open the main
        window is disabled and every command fails. Close those dialogs first.
        Returns the list of dismissed dialog handles.
        """
        if not self.busy():
            return []
        dismissed = self.dismiss_modals() if dismiss else []
        time.sleep(0.2)
        if self.busy():
            raise RuntimeError("engine still blocked by a modal dialog")
        return dismissed

    _BUSY_WORDS = ("solv", "running", "calculat", "integrat", "simulat", "step")

    def has_status_signal(self) -> bool:
        """True when the engine's status bar carries run-state text.

        HumMod writes "Solving ... / Done"; QCP 2005 keeps a static
        "Starting Model ... Binding ... Done" line, so it carries no usable
        signal and completion has to be judged by the Stop menu instead.
        """
        t = self.status_text().strip().lower()
        if not t:
            return False
        return any(w in t for w in self._BUSY_WORDS) or t.endswith("done")

    def solving(self) -> bool:
        """True while the engine reports an unfinished run in its status bar.

        HumMod writes "Solving ..." while the model integrates and appends
        "Done" when it finishes.  This is the only reliable signal on 3.0.4:
        the Stop menu item can stay gray while the model runs, and the UI
        thread keeps answering messages.
        """
        t = self.status_text().strip().lower()
        if not t:
            return False
        if t.endswith("done"):
            return False
        return any(w in t for w in self._BUSY_WORDS)

    def wait_idle(self, stop_cmd_id: int, timeout: float = 600.0,
                  start_grace: float = 8.0,
                  before_status: str | None = None,
                  dismiss: bool = True) -> dict:
        """Wait until the simulation has really finished.

        HumMod 3.0.4 keeps the Stop menu item gray while the model is solving
        and keeps answering window messages, so neither can detect "running".
        The status bar is the reliable signal ("Solving ..." -> "Solving ... Done").

        `dismiss` closes event popups that the model raises mid-run (1.6.1
        pops "The ECG shows V-Fib! Continue?" and the symptom messages). Such a
        popup is modal: while it is up the engine does not solve, so a run
        would never finish and the caller would wait for the whole timeout.

        Returns {"started": bool, "elapsed": float, "signal": str,
                 "modals_dismissed": int}.
        """
        t0 = time.time()
        deadline = t0 + timeout
        before = self.status_text() if before_status is None else before_status
        started = False
        signal = "none"
        dismissed = 0
        # Engines without a status-bar run signal (QCP 2005) have to be judged
        # by their Stop menu item, which is enabled while the model runs.
        stop_fallback = not self.has_status_signal()
        # phase 1 - catch the run starting
        while time.time() - t0 < start_grace:
            if dismiss and self.busy():
                dismissed += len(self.dismiss_modals())
            if self.solving():
                started, signal = True, "status-text"
                break
            if self.menu_item_enabled(stop_cmd_id):
                started, signal = True, "stop-enabled"
                break
            time.sleep(0.05)
        if not started:
            # the run may have been too short to observe; the status bar still
            # shows that something ran and finished
            now = self.status_text()
            if now and now != before and now.strip().lower().endswith("done"):
                started, signal = True, "status-text-fast"
        # phase 2 - wait for it to finish
        while time.time() < deadline:
            if dismiss and self.busy():
                dismissed += len(self.dismiss_modals())
            if not self.solving():
                if stop_fallback and self.menu_item_enabled(stop_cmd_id):
                    # no status signal: the Stop menu is still lit, so the run
                    # is not over (a modal popup can freeze the model while
                    # the engine keeps the "running" state)
                    time.sleep(0.2)
                    continue
                time.sleep(0.2)          # confirm: a solver pause is not the end
                if not self.solving():
                    return {"started": started, "elapsed": time.time() - t0,
                            "signal": signal, "modals_dismissed": dismissed}
            time.sleep(0.05)
        raise TimeoutError(f"simulation did not finish within {timeout}s")

    def terminate(self, grace: float = 6.0) -> bool:
        """Close the engine process so a fresh one can reload the model XML.

        Sends WM_CLOSE first (lets the engine shut down cleanly); if the window
        is still up after `grace` seconds the process is terminated.
        """
        if not self.main:
            return False
        user32.PostMessageW(self.main, WM_CLOSE, 0, 0)
        deadline = time.time() + grace
        while time.time() < deadline:
            if not user32.IsWindow(self.main):
                return True
            time.sleep(0.2)
        handle = kernel32.OpenProcess(0x0001 | 0x0400, False, self.pid)  # TERMINATE|SYNCHRONIZE
        if handle:
            kernel32.TerminateProcess(handle, 0)
            kernel32.CloseHandle(handle)
        # wait for the process itself to exit - the window handle can outlive
        # it briefly, and a second engine in the same folder breaks attach()
        deadline = time.time() + 8
        while time.time() < deadline:
            h = kernel32.OpenProcess(0x1000, False, self.pid)  # SYNCHRONIZE
            if not h:
                return True
            code = wintypes.DWORD()
            kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            kernel32.CloseHandle(h)
            if code.value != 259:  # STILL_ACTIVE
                return True
            time.sleep(0.2)
        return False

    def busy(self) -> bool:
        return not bool(user32.IsWindowEnabled(self.main))

    def ui_responsive(self, timeout_ms: int = 400) -> bool:
        """True when the engine's UI thread still answers messages.

        HumMod solves the model on the UI thread, so while a run is in progress
        the window stops pumping messages.  A WM_NULL probe with a timeout is
        the only reliable "is the engine still working?" signal - the Stop menu
        item stays gray on 3.0.4 even while the model is solving.
        """
        res = ctypes.c_size_t()
        return user32.SendMessageTimeoutW(self.main, WM_NULL, 0, 0,
                                           0x0002, timeout_ms, ctypes.byref(res)) != 0

    def status_text(self) -> str:
        """Text of the engine's status bar (progress messages live there)."""
        out = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def on_child(hwnd, _l):
            buf = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, buf, 64)
            if buf.value.startswith("msctls_statusbar"):
                tb = ctypes.create_unicode_buffer(1024)
                res = ctypes.c_size_t()
                if user32.SendMessageTimeoutW(hwnd, WM_GETTEXT, 1024, tb,
                                              0x0002, 1500, ctypes.byref(res)):
                    out.append(tb.value.strip())
                return False
            return True

        user32.EnumChildWindows(self.main, on_child, 0)
        return out[0] if out else ""

    # ---------- window state ----------

    SW_RESTORE = 9
    SW_SHOW = 5
    SW_HIDE = 0

    def window_rect(self) -> tuple[int, int, int, int]:
        r = wintypes.RECT()
        user32.GetWindowRect(self.main, ctypes.byref(r))
        return (r.left, r.top, r.right, r.bottom)

    def is_minimized(self) -> bool:
        return bool(user32.IsIconic(self.main))

    def restore_window(self) -> None:
        """Bring the engine window back to a usable size.

        Engines launched hidden (or minimised by the WM) still paint their
        panels, but mouse/keyboard input and window-relative screenshots need
        a real, restored window.
        """
        was_hidden = not user32.IsWindowVisible(self.main)
        if self.is_minimized():
            user32.ShowWindow(self.main, self.SW_RESTORE)
        elif was_hidden:
            user32.ShowWindow(self.main, self.SW_SHOW)
        if was_hidden or self.is_minimized():
            # only steal focus when we really had to bring the window back;
            # foregrounding an already visible window hides modeless dialogs
            user32.SetForegroundWindow(self.main)
            time.sleep(0.3)

    def client_origin(self) -> tuple[int, int]:
        """Client-area origin expressed in window coordinates."""
        pt = wintypes.POINT(0, 0)
        user32.ClientToScreen(self.main, ctypes.byref(pt))
        l, t, _, _ = self.window_rect()
        return (pt.x - l, pt.y - t)

    # ---------- capture ----------

    def capture_png(self, path: str) -> tuple[int, int]:
        """Save a PNG of the engine window (PrintWindow, falls back to BitBlt).

        Canvas-drawn engines have no widget tree, so a picture is the only way
        an agent can see what is on screen.
        """
        import struct
        import zlib

        l, t, r, b = self.window_rect()
        w, h = r - l, b - t
        if w <= 0 or h <= 0:
            raise RuntimeError("engine window has no size")
        gdi = ctypes.windll.gdi32
        hdc = user32.GetWindowDC(self.main)
        mdc = gdi.CreateCompatibleDC(hdc)
        bmp = gdi.CreateCompatibleBitmap(hdc, w, h)
        gdi.SelectObject(mdc, bmp)
        try:
            ok = user32.PrintWindow(self.main, mdc, 2)  # PW_RENDERFULLCONTENT
            if not ok:
                gdi.BitBlt(mdc, 0, 0, w, h, hdc, 0, 0, 0x00CC0020)
            class BIH(ctypes.Structure):
                _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                            ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                            ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                            ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                            ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                            ("biClrImportant", wintypes.DWORD)]
            bi = BIH()
            bi.biSize = ctypes.sizeof(BIH)
            bi.biWidth = w
            bi.biHeight = -h
            bi.biPlanes = 1
            bi.biBitCount = 32
            bi.biCompression = 0
            buf = ctypes.create_string_buffer(w * h * 4)
            if not gdi.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0):
                raise RuntimeError("GetDIBits failed")
            raw = buf.raw
            # BGRX -> RGB
            rgb = bytearray(w * h * 3)
            for i in range(w * h):
                rgb[3 * i] = raw[4 * i + 2]
                rgb[3 * i + 1] = raw[4 * i + 1]
                rgb[3 * i + 2] = raw[4 * i]
            png = self._png_bytes(w, h, bytes(rgb))
            with open(path, "wb") as f:
                f.write(png)
            return (w, h)
        finally:
            gdi.DeleteObject(bmp)
            gdi.DeleteDC(mdc)
            user32.ReleaseDC(self.main, hdc)

    @staticmethod
    def _png_bytes(width: int, height: int, rgb: bytes) -> bytes:
        """Minimal PNG writer (stdlib only - no Pillow dependency)."""
        import struct
        import zlib
        stride = width * 3
        raw = bytearray()
        for y in range(height):
            raw.append(0)
            raw += rgb[y * stride:(y + 1) * stride]

        def chunk(typ: bytes, data: bytes) -> bytes:
            return (struct.pack(">I", len(data)) + typ + data
                    + struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff))

        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
                + chunk(b"IEND", b""))

    # ---------- pointer ----------

    def click(self, x: int, y: int, button: str = "left", double: bool = False,
              method: str = "message") -> dict:
        """Click at window-relative (x, y).

        method='message' posts WM_LBUTTON*/WM_RBUTTON* to the window, which
        works for owner-drawn canvases without moving the physical mouse.
        method='mouse' moves the real cursor (needs a foreground window).
        """
        ox, oy = self.client_origin()
        cx, cy = x - ox, y - oy
        down, up = (WM_LBUTTONDOWN, WM_LBUTTONUP) if button == "left" else (WM_RBUTTONDOWN, WM_RBUTTONUP)
        lparam = (cy << 16) | (cx & 0xFFFF)
        wparam = 1 if button == "left" else 2
        if method == "mouse":
            l, t, _, _ = self.window_rect()
            user32.SetCursorPos(l + x, t + y)
            time.sleep(0.05)
            user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
            time.sleep(0.05)
            user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
        else:
            self.ensure_ready()
            user32.SendMessageW(self.main, WM_MOUSEMOVE, 0, lparam)
            user32.SendMessageW(self.main, down, wparam, lparam)
            time.sleep(0.03)
            user32.SendMessageW(self.main, up, 0, lparam)
            if double:
                user32.SendMessageW(self.main, WM_LBUTTONDBLCLK, wparam, lparam)
        time.sleep(0.15)
        return {"window_xy": [x, y], "client_xy": [cx, cy], "method": method}

    def drag(self, x1: int, y1: int, x2: int, y2: int, steps: int = 20) -> dict:
        """Press at (x1,y1), move to (x2,y2), release - for canvas slidebars."""
        ox, oy = self.client_origin()
        cx1, cy1 = x1 - ox, y1 - oy
        cx2, cy2 = x2 - ox, y2 - oy
        lp1 = (cy1 << 16) | (cx1 & 0xFFFF)
        lp2 = (cy2 << 16) | (cx2 & 0xFFFF)
        self.ensure_ready()
        user32.SendMessageW(self.main, WM_MOUSEMOVE, 0, lp1)
        user32.SendMessageW(self.main, WM_LBUTTONDOWN, 1, lp1)
        for i in range(1, steps + 1):
            x = cx1 + (cx2 - cx1) * i // steps
            y = cy1 + (cy2 - cy1) * i // steps
            user32.SendMessageW(self.main, WM_MOUSEMOVE, 1, (y << 16) | (x & 0xFFFF))
            time.sleep(0.02)
        user32.SendMessageW(self.main, WM_LBUTTONUP, 0, lp2)
        time.sleep(0.15)
        return {"from": [x1, y1], "to": [x2, y2], "client_from": [cx1, cy1]}

    # ---------- popup menus ----------

    def popup_menus(self) -> list[dict]:
        """Enumerate visible popup menus (#32768) and their items.

        TrackPopupMenu creates a class '#32768' window that owns the menu, so
        the items can be read (and their command ids reused) while it is open.
        """
        out: list[dict] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def on_window(hwnd, _l):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == self.pid and user32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(hwnd, buf, 64)
                if buf.value == "#32768":
                    hmenu = user32.GetMenu(hwnd)
                    items = []
                    if hmenu:
                        n = user32.GetMenuItemCount(hmenu)
                        for i in range(n):
                            ib = ctypes.create_unicode_buffer(256)
                            user32.GetMenuStringW(hmenu, i, ib, 256, MF_BYPOSITION)
                            state = user32.GetMenuState(hmenu, i, MF_BYPOSITION)
                            cid = user32.GetMenuItemID(hmenu, i)
                            items.append({"label": ib.value.replace("&", ""),
                                          "id": int(cid) & 0xFFFF if cid not in (0xFFFFFFFF, -1) else None,
                                          "enabled": (state & MFS_MASK) == 0})
                    out.append({"hwnd": hex(hwnd), "menu": hex(hmenu) if hmenu else None,
                                "items": items})
            return True

        user32.EnumWindows(on_window, 0)
        return out

    # ---------- list boxes / dialog widgets ----------

    LB_GETCOUNT = 0x018B
    LB_GETTEXT = 0x0189
    LB_GETCURSEL = 0x0188
    LB_SETCURSEL = 0x0186
    LBN_SELCHANGE = 1

    def listbox_items(self, hwnd: int) -> list[str]:
        """Read every item of a list box (standard control, text marshalled)."""
        cnt = user32.SendMessageW(hwnd, self.LB_GETCOUNT, 0, 0)
        out: list[str] = []
        for i in range(cnt):
            buf = ctypes.create_unicode_buffer(2048)
            user32.SendMessageW(hwnd, self.LB_GETTEXT, i,
                                ctypes.addressof(buf))
            out.append(buf.value)
        return out

    def listbox_selected(self, hwnd: int) -> int:
        return user32.SendMessageW(hwnd, self.LB_GETCURSEL, 0, 0)

    def listbox_select(self, hwnd: int, index: int) -> dict:
        """Select an item and notify the parent (LBN_SELCHANGE), so the app
        refreshes whatever depends on that list."""
        ok = user32.SendMessageW(hwnd, self.LB_SETCURSEL, index, 0)
        parent = user32.GetParent(hwnd)
        cid = user32.GetDlgCtrlID(hwnd)
        wparam = (self.LBN_SELCHANGE << 16) | (cid & 0xFFFF)
        user32.SendMessageW(parent, WM_COMMAND, wparam, hwnd)
        time.sleep(0.15)
        return {"selected": index, "set": bool(ok),
                "current": self.listbox_selected(hwnd)}

    def dialog_by_title(self, needle: str) -> int | None:
        """Find a visible #32770 dialog whose title contains `needle`."""
        needle = needle.lower()
        for d in self._visible_dialogs():
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(d, buf, 256)
            if needle in buf.value.lower():
                return d
        return None

    def dialog_with_text(self, needle: str) -> int | None:
        """Find a visible #32770 dialog that *contains* a control with this text.

        Some engines reuse the app title for their dialogs and mark them only
        with a static caption, so the title alone is not a reliable key.
        """
        needle = needle.lower()
        for d in self._visible_dialogs():
            for k in self._dialog_children(d):
                if needle in k.text.strip().lower():
                    return d
        return None

    def press_dialog_button(self, dlg: int, caption: str) -> bool:
        """Press a dialog button by its caption."""
        for k in self._dialog_children(dlg):
            if k.cls == "Button" and k.text.strip().lower() == caption.strip().lower():
                self.press(k.hwnd)
                time.sleep(0.2)
                return True
        return False

    # ---------- dialogs ----------

    # Standard MessageBox button ids. HumMod 1.6.1 raises MessageBox-style
    # popups from its model files: the ECG events and the symptom messages use
    # MB_YESNO (IDYES/IDNO), the rest MB_OK (IDOK). Posting IDOK/IDCANCEL to a
    # YES/NO box does nothing at all - the box has no such button - so those
    # dialogs could never be closed and every engine command then failed with
    # "engine still blocked by a modal dialog".
    DIALOG_BUTTON_IDS = (1, 2, 6, 7)  # IDOK, IDCANCEL, IDYES, IDNO

    @staticmethod
    def pick_dialog_button(buttons, prefer: int = 6):
        """Choose which button of a modal dialog to click.

        `buttons` is a list of Control-like objects with .ctrl_id, .visible,
        .enabled and .style. Returns the preferred button when the dialog
        offers it (IDYES by default, i.e. answer "yes / continue"), otherwise
        the first push button, otherwise None.

        Kept separate from the Win32 plumbing so it can be unit-tested: the
        old implementation only ever looked for IDOK/IDCANCEL, which a
        MB_YESNO dialog does not have.
        """
        usable = [b for b in buttons
                  if getattr(b, "visible", True) and getattr(b, "enabled", True)
                  and (getattr(b, "style", 0) & 0x0F) in (0x00, 0x01, 0x03)]
        for b in usable:
            if b.ctrl_id == prefer:
                return b
        return usable[0] if usable else None

    def dialog_info(self) -> list[dict]:
        """Describe every modal dialog the engine currently has open.

        Returns hwnd / title / message / the buttons offered - enough for a
        caller to report *why* the engine is blocked instead of just
        "engine still blocked by a modal dialog".
        """
        out: list[dict] = []
        for d in self._visible_dialogs():
            kids = self._dialog_children(d)
            msg = next((c.text for c in kids
                        if c.cls == "Static" and c.ctrl_id == 65535), "")
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(d, buf, 256)
            out.append({
                "hwnd": hex(d),
                "title": buf.value,
                "message": msg,
                "buttons": [{"id": c.ctrl_id, "text": c.text}
                            for c in kids if c.cls == "Button"],
            })
        return out

    def dismiss_modals(self, prefer: int = 6, max_passes: int = 40) -> list[int]:
        """Close every modal dialog the engine has open.

        `prefer` is the button id to click when the dialog offers it
        (default IDYES = 6, i.e. answer "yes / continue"); dialogs without it
        fall back to their first push button (IDOK for MB_OK boxes).
        Returns the handles that were found (whether or not they closed).
        """
        found: list[int] = []
        # QCP raises event dialogs in cascades: answering one immediately
        # raises the next ("V-Fib" -> "not conscious" -> "not breathing" -> ...).
        # Keep answering until the engine is free again.
        for _ in range(max_passes):
            if not self._visible_dialogs():
                break
            for d in self._visible_dialogs():
                found.append(d)
                buttons = [c for c in self._dialog_children(d) if c.cls == "Button"]
                target = self.pick_dialog_button(buttons, prefer)
                if target is not None:
                    user32.PostMessageW(target.hwnd, BM_CLICK, 0, 0)
                    time.sleep(0.2)
                if d in self._visible_dialogs():
                    # BM_CLICK did not take - drive the dialog with WM_COMMAND.
                    user32.PostMessageW(d, WM_COMMAND,
                                        target.ctrl_id if target else 1, 0)
                    time.sleep(0.15)
                if d in self._visible_dialogs():
                    user32.PostMessageW(d, WM_CLOSE, 0, 0)
                    time.sleep(0.15)
        # final hard pass: anything still open gets a synchronous WM_CLOSE
        still = [h for h in self._visible_dialogs() if h in found]
        for d in still:
            user32.SendMessageTimeoutW(d, WM_CLOSE, 0, 0, 0x0002, 2000,
                                       ctypes.byref(ctypes.c_size_t()))
        if still:
            time.sleep(0.2)
        return found

    def save_file_dialog(self, command_id: int, target_path: str,
                         edit_ids: tuple[int, ...] = (1001, 1148),
                         timeout: float = 60.0,
                         tail_markers: tuple[str, ...] = ("</solution>", "</ics>")) -> None:
        """Trigger File > Save Solution/ICs and drive the native Save dialog."""
        import os
        target_path = os.path.abspath(target_path)
        if os.path.exists(target_path):
            os.remove(target_path)
        # event modals (1.6.1 pops them on parameter changes) would block the
        # export - clear them first instead of failing
        self.ensure_ready()
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
        # The engine keeps writing after the dialog closes (SOL vars are written
        # alphabetically). If the format has a closing tag, wait for it; otherwise
        # (e.g. QCP ICS) a stable file size means the writer is done.
        deadline = time.time() + timeout
        last_size = -1
        stable_seen = False
        while time.time() < deadline:
            if os.path.exists(target_path) and not self.busy():
                try:
                    size = os.path.getsize(target_path)
                    if size == last_size and size > 0:
                        with open(target_path, "rb") as f:
                            f.seek(max(0, size - 256))
                            tail = f.read().decode("utf-8", "replace").lower()
                        if any(m in tail for m in tail_markers):
                            return
                        if stable_seen:  # no marker expected for this format
                            return
                        stable_seen = True
                    else:
                        stable_seen = False
                    last_size = size
                except OSError:
                    pass
            time.sleep(0.1)
        raise RuntimeError("export did not complete; inspect the engine")

    def load_file_dialog(self, command_id: int, target_path: str,
                         edit_ids: tuple[int, ...] = (1001, 1148),
                         timeout: float = 60.0) -> None:
        """Trigger File > Load Solution/ICs and drive the native Open dialog.

        Same mechanics as save_file_dialog, but the target file must already
        exist (it is only typed into the dialog, never written), and completion
        is "the dialog closed and the engine is idle again" - the engine does
        not write a file when loading."""
        import os
        target_path = os.path.abspath(target_path)
        if not os.path.exists(target_path):
            raise FileNotFoundError(f"no such file to load: {target_path}")
        self.ensure_ready()
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
        # the Open dialog closes as soon as the engine accepts the file; wait
        # for it to disappear and the engine UI to settle
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self._visible_dialogs() and not self.busy():
                return
            time.sleep(0.1)
        raise RuntimeError("load did not complete; inspect the engine")

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

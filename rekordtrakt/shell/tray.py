"""The notification-area (tray) icon and its menu, with plain Win32 calls through ctypes (no extra packages).

Runs a message loop on the thread that calls run(). Other threads talk to it through call_soon(), which posts a
message to the hidden window. A timer refreshes the icon and tooltip from `status()` twice a second.
"""
import ctypes
import queue
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WM_DESTROY, WM_CLOSE, WM_TIMER, WM_QUIT, WM_NULL = 0x0002, 0x0010, 0x0113, 0x0012, 0x0000
WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0205, 0x007B
WM_APP = 0x8000
WM_TRAY, WM_CALL = WM_APP + 1, WM_APP + 2
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO, NIIF_WARNING, NIIF_ERROR = 1, 2, 3
MF_STRING, MF_GRAYED, MF_CHECKED, MF_SEPARATOR = 0x0, 0x1, 0x8, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
SM_CXSMICON, SM_CYSMICON = 49, 50
PM_REMOVE, QS_ALLINPUT = 0x1, 0x04FF
TIMER_ID = 1


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON)]


def _sig(dll, name, restype, *argtypes):
    f = getattr(dll, name)
    f.restype, f.argtypes = restype, argtypes
    return f


DefWindowProcW = _sig(_user32, "DefWindowProcW", LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
RegisterClassExW = _sig(_user32, "RegisterClassExW", wintypes.ATOM, ctypes.POINTER(WNDCLASSEXW))
UnregisterClassW = _sig(_user32, "UnregisterClassW", wintypes.BOOL, wintypes.LPCWSTR, wintypes.HINSTANCE)
CreateWindowExW = _sig(_user32, "CreateWindowExW", wintypes.HWND, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                       wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                       wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID)
DestroyWindow = _sig(_user32, "DestroyWindow", wintypes.BOOL, wintypes.HWND)
PostMessageW = _sig(_user32, "PostMessageW", wintypes.BOOL, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
PostQuitMessage = _sig(_user32, "PostQuitMessage", None, ctypes.c_int)
PeekMessageW = _sig(_user32, "PeekMessageW", wintypes.BOOL, ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT,
                    wintypes.UINT, wintypes.UINT)
TranslateMessage = _sig(_user32, "TranslateMessage", wintypes.BOOL, ctypes.POINTER(wintypes.MSG))
DispatchMessageW = _sig(_user32, "DispatchMessageW", LRESULT, ctypes.POINTER(wintypes.MSG))
MsgWaitForMultipleObjects = _sig(_user32, "MsgWaitForMultipleObjects", wintypes.DWORD, wintypes.DWORD,
                                 ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD, wintypes.DWORD)
CreatePopupMenu = _sig(_user32, "CreatePopupMenu", wintypes.HMENU)
AppendMenuW = _sig(_user32, "AppendMenuW", wintypes.BOOL, wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR)
DestroyMenu = _sig(_user32, "DestroyMenu", wintypes.BOOL, wintypes.HMENU)
TrackPopupMenu = _sig(_user32, "TrackPopupMenu", ctypes.c_int, wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                      ctypes.c_int, wintypes.HWND, wintypes.LPVOID)
GetCursorPos = _sig(_user32, "GetCursorPos", wintypes.BOOL, ctypes.POINTER(wintypes.POINT))
SetForegroundWindow = _sig(_user32, "SetForegroundWindow", wintypes.BOOL, wintypes.HWND)
SetTimer = _sig(_user32, "SetTimer", ctypes.c_size_t, wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID)
KillTimer = _sig(_user32, "KillTimer", wintypes.BOOL, wintypes.HWND, ctypes.c_size_t)
RegisterWindowMessageW = _sig(_user32, "RegisterWindowMessageW", wintypes.UINT, wintypes.LPCWSTR)
LoadImageW = _sig(_user32, "LoadImageW", wintypes.HANDLE, wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                  ctypes.c_int, ctypes.c_int, wintypes.UINT)
DestroyIcon = _sig(_user32, "DestroyIcon", wintypes.BOOL, wintypes.HICON)
GetSystemMetrics = _sig(_user32, "GetSystemMetrics", ctypes.c_int, ctypes.c_int)
Shell_NotifyIconW = _sig(_shell32, "Shell_NotifyIconW", wintypes.BOOL, wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW))
GetModuleHandleW = _sig(_kernel32, "GetModuleHandleW", wintypes.HMODULE, wintypes.LPCWSTR)


def set_dpi_aware():
    """Sharp icons and menus on scaled displays."""
    try:
        _user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))     # per-monitor v2
    except (AttributeError, OSError):
        pass


class MenuItem:
    def __init__(self, text, action=None, checked=False, enabled=True):
        self.text, self.action, self.checked, self.enabled = text, action, checked, enabled


SEPARATOR = None


class Tray:
    """status(): returns (icon key, tooltip). menu(): returns a list of MenuItem / SEPARATOR, built when opened.
    on_click(): left click."""

    CLASS_NAME = "RekordTraktTray"

    def __init__(self, icon_paths, status, menu, on_click=None):
        self.icon_paths = icon_paths
        self.status = status
        self.menu = menu
        self.on_click = on_click
        self._icons = {}
        self._shown = None                  # (icon key, tooltip) last given to Windows
        self._added = False
        self._calls = queue.Queue()
        self._taskbar_created = RegisterWindowMessageW("TaskbarCreated")   # before the window: _proc reads it
        self._wndproc = WNDPROC(self._proc)  # must stay referenced while the window exists
        self._hinst = GetModuleHandleW(None)
        wc = WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW), lpfnWndProc=self._wndproc, hInstance=self._hinst,
                         lpszClassName=self.CLASS_NAME)
        if not RegisterClassExW(ctypes.byref(wc)):
            raise OSError(f"RegisterClassExW failed ({ctypes.get_last_error()})")
        # A hidden top-level window rather than a message-only one: those don't get "TaskbarCreated".
        self.hwnd = CreateWindowExW(0, self.CLASS_NAME, "RekordTrakt", 0, 0, 0, 0, 0, None, None, self._hinst, None)
        if not self.hwnd:
            raise OSError(f"CreateWindowExW failed ({ctypes.get_last_error()})")
        SetTimer(self.hwnd, TIMER_ID, 500, None)
        self._refresh()

    # --- any thread -----------------------------------------------------------------------------------
    def call_soon(self, fn):
        self._calls.put(fn)
        PostMessageW(self.hwnd, WM_CALL, 0, 0)

    def notify(self, title, text, level="info"):
        self.call_soon(lambda: self._balloon(title, text, level))

    def quit(self):
        self.call_soon(lambda: PostQuitMessage(0))

    # --- tray thread ----------------------------------------------------------------------------------
    def run(self):
        msg = wintypes.MSG()
        while True:
            while PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == WM_QUIT:
                    return
                TranslateMessage(ctypes.byref(msg))
                DispatchMessageW(ctypes.byref(msg))
            MsgWaitForMultipleObjects(0, None, False, 200, QS_ALLINPUT)   # returns to Python often, so Ctrl+C works

    def close(self):
        if self._added:
            Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._data(0)))
            self._added = False
        KillTimer(self.hwnd, TIMER_ID)
        DestroyWindow(self.hwnd)
        UnregisterClassW(self.CLASS_NAME, self._hinst)
        for icon in self._icons.values():
            DestroyIcon(icon)
        self._icons.clear()

    def _icon(self, key):
        if key not in self._icons:
            cx, cy = GetSystemMetrics(SM_CXSMICON), GetSystemMetrics(SM_CYSMICON)
            self._icons[key] = LoadImageW(None, str(self.icon_paths[key]), IMAGE_ICON, cx, cy, LR_LOADFROMFILE)
        return self._icons[key]

    def _data(self, flags):
        d = NOTIFYICONDATAW(cbSize=ctypes.sizeof(NOTIFYICONDATAW), hWnd=self.hwnd, uID=1, uFlags=flags,
                            uCallbackMessage=WM_TRAY)
        return d

    def _refresh(self, force=False):
        key, tip = self.status()
        if not force and self._added and (key, tip) == self._shown:
            return
        d = self._data(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        d.hIcon = self._icon(key)
        d.szTip = tip[:127]
        if Shell_NotifyIconW(NIM_MODIFY if self._added else NIM_ADD, ctypes.byref(d)):
            self._added = True
            self._shown = (key, tip)
        else:
            self._added = False            # e.g. Explorer not ready yet at login: the timer tries again

    def _balloon(self, title, text, level):
        if not self._added:
            return
        d = self._data(NIF_INFO)
        d.szInfoTitle = title[:63]
        d.szInfo = text[:255]
        d.dwInfoFlags = {"info": NIIF_INFO, "warning": NIIF_WARNING, "error": NIIF_ERROR}[level]
        Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(d))

    def _show_menu(self):
        items = self.menu()
        hmenu = CreatePopupMenu()
        actions = {}
        for i, item in enumerate(items, start=1):
            if item is SEPARATOR:
                AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
                continue
            flags = MF_STRING | (MF_CHECKED if item.checked else 0) | (0 if item.enabled and item.action else MF_GRAYED)
            AppendMenuW(hmenu, flags, i, item.text)
            actions[i] = item.action
        pt = wintypes.POINT()
        GetCursorPos(ctypes.byref(pt))
        SetForegroundWindow(self.hwnd)            # otherwise the menu doesn't close when clicking elsewhere
        chosen = TrackPopupMenu(hmenu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, pt.x, pt.y, 0, self.hwnd, None)
        PostMessageW(self.hwnd, WM_NULL, 0, 0)
        DestroyMenu(hmenu)
        if chosen and actions.get(chosen):
            actions[chosen]()

    def _proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                event = lparam & 0xFFFF
                if event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._show_menu()
                elif event == WM_LBUTTONUP:
                    (self.on_click or self._show_menu)()
                return 0
            if msg == WM_CALL:
                while True:
                    try:
                        self._calls.get_nowait()()
                    except queue.Empty:
                        break
                return 0
            if msg == WM_TIMER:
                self._refresh()
                return 0
            if msg == self._taskbar_created:        # Explorer restarted: add the icon again
                self._added = False
                self._refresh(force=True)
                return 0
            if msg == WM_CLOSE:
                PostQuitMessage(0)
                return 0
        except Exception as e:                      # never let an exception escape into Windows
            print(f"tray: {type(e).__name__}: {e}")
        return DefWindowProcW(hwnd, msg, wparam, lparam)

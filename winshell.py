"""
WinShell v2: Windows 10-style taskbar + Start menu + desktop + settings
for Wine/Winlator. Pure Python + ctypes (no pip packages).

Run:  pythonw.exe winshell.py          (log: %TEMP%\\winshell.log)

Everything is configured from the built-in Settings window (Start > gear,
or right-click the taskbar > Settings). Settings are stored in
C:\\ProgramData\\WinShell\\config.json and also reload live if you edit
that file by hand.
"""
import atexit
import ctypes
import json
import logging
import logging.handlers
import math
import os
import random
import shutil
import struct
import subprocess
import sys
import time
from ctypes import (POINTER, Structure, WINFUNCTYPE, byref, c_int, c_short, c_uint,
                    c_size_t, c_ssize_t, c_ubyte, c_void_p, c_wchar_p,
                    create_unicode_buffer, sizeof)
from ctypes import wintypes as wt

if sys.platform != "win32":
    sys.exit("This program must run inside Wine/Windows (Winlator).")

_handler = logging.handlers.RotatingFileHandler(
    os.path.join(os.environ.get("TEMP", "C:\\"), "winshell.log"), maxBytes=400000,
    backupCount=2, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
logging.getLogger().addHandler(_handler)
logging.getLogger().setLevel(logging.INFO)
log = logging.getLogger("winshell")
sys.excepthook = lambda et, ev, tb: log.error("unhandled error", exc_info=(et, ev, tb))

# ==========================================================================
# Config
# ==========================================================================
DEFAULTS = {
    # personalization
    "theme": "dark",               # dark | light
    "glass": True,                 # translucent bars + gloss highlight
    "glass_opacity": 88,           # 30..100 (percent)
    "glass_blur": False,           # fake blur: blurred wallpaper behind the bars
    "start_icon": "",              # .ico / .png for the Start button
    # window look (title bars, buttons, scroll bars of Wine apps)
    "window_look": "default",      # default | windows10_light | windows10_dark
    "look_title_accent": False,
    "look_caption_height": 22,
    "look_scrollbar_width": 17,
    "theme_file": "",              # optional Windows-style .msstyles you own
    "look_backup": {},
    "clock_offset": 0,
    "use_winshell_explorer": True,
    "explorer_show_hidden": False,
    # startup apps
    "autostart": [],
    "autostart_delay": 3,
    # full-screen / maximized behaviour
    "fs_mode": "keep_visible",     # keep_visible | bar_over_app | floating_icon | hide_bar
    "fs_trigger": "fullscreen",    # fullscreen | maximized | both
    "float_corner": "bottom-right",
    # custom title bars drawn by WinShell on top of app windows
    "look_title_color": "#FFFFFF",
    "custom_titlebar": False,
    "tb_button_style": "windows10",   # windows10 | circles | boxed
    "tb_align": "theme",
    "tb_show_icon": True,
    "tb_height_adjust": 0,
    "tb_offset_y": 0,
    "tb_theme": "windows10",
    "tb_use_theme_colors": True,
    "tb_text": "app_and_title",    # title | app | app_and_title
    "tb_show_snap": True,
    "tb_show_shade": True,
    "tb_icon_min": "", "tb_icon_max": "", "tb_icon_restore": "",
    "tb_icon_close": "", "tb_icon_snap": "", "tb_icon_shade": "",
    "tb_new_theme_name": "my_theme",
    # blur per surface
    "glass_blur_bar": False,
    "glass_blur_start": False,
    "glass_blur_title": False,
    "glass_blur_window": False,
    # start menu tiles
    "start_collapsed": False,
    "tile_random_colors": False,
    "tile_shuffle": False,
    "tile_shuffle_seconds": 8,
    "tile_colors": {},
    # previews
    "preview_on_hover": True,
    "preview_live": True,
    "preview_width": 240,
    "preview_refresh_ms": 500,
    "preview_hover_delay": 400,
    # file explorer
    "bookmarks": [],
    "assoc": {},
    "open_with_apps": [],
    "explorer_view": "details",
    "explorer_grid_size": 96,
    "accent": "#0078D7",
    "bar_color": "",               # "#RRGGBB" or empty for theme default
    "font": "Segoe UI",
    "font_size": 14,
    "scale": 1.0,
    # taskbar
    "position": "bottom",          # bottom | top
    "alignment": "left",           # left | center | right
    "height": 40,
    "icon_size": 24,
    "button_width": 170,
    "show_titles": False,
    "icon_accent": True,
    "lock_taskbar": True,          # True: full-screen apps are kept above the bar
    "clock_format": "%H:%M\n%d/%m/%Y",
    "reserve_work_area": True,
    "hide_wine_taskbar": False,
    "pinned": ["explorer.exe"],
    # start menu / user
    "start_pins": ["explorer.exe", "control.exe", "cmd.exe", "taskmgr.exe",
                   "regedit.exe", "notepad.exe"],
    "user_name": "User",
    "user_photo": "",
    "start_extra": [],
    "start_hidden": [],
    "start_starred": [],
    "start_usage": {},
    "start_tile_sizes": {},
    # desktop
    "full_desktop": False,
    "grid_size": 96,
    "grid_snap": True,
    "show_desktop_icons": True,
    "wallpaper": "",
    "wallpaper_mode": "fill",      # fill | fit | stretch | center | tile
    "desktop_color": "#1E3A5F",
    "desktop_extra": [],
    "desktop_hidden": [],
    "desktop_layout": {},
}
CONFIG_DIR = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "WinShell")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "dark_mode" in data and "theme" not in data:   # v1 migration
                data["theme"] = "dark" if data["dark_mode"] else "light"
            if "fs_mode" not in data and "lock_taskbar" in data:
                data["fs_mode"] = "keep_visible" if data["lock_taskbar"] else "hide_bar"
            if data.get("glass_blur") and "glass_blur_bar" not in data:
                for k in ("glass_blur_bar", "glass_blur_start", "glass_blur_title",
                          "glass_blur_window"):
                    data[k] = True
            cfg.update(data)
        else:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
    except Exception as exc:
        log.warning("config error: %s", exc)
    return cfg


def config_mtime():
    try:
        return os.path.getmtime(CONFIG_PATH)
    except OSError:
        return 0


def rgb(r, g, b):
    return r | (g << 8) | (b << 16)


def split_rgb(c):
    return c & 255, (c >> 8) & 255, (c >> 16) & 255


def shade(c, f):
    r, g, b = split_rgb(c)
    return rgb(min(255, int(r * f)), min(255, int(g * f)), min(255, int(b * f)))


def mix(c1, c2, t):
    a, b = split_rgb(c1), split_rgb(c2)
    return rgb(*[int(a[i] * (1 - t) + b[i] * t) for i in range(3)])


def hex_color(text, default):
    try:
        t = str(text).lstrip("#")
        return rgb(int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16))
    except Exception:
        return default


def s32(v):
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


# ==========================================================================
# Win32 bindings
# ==========================================================================
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
comdlg32 = ctypes.WinDLL("comdlg32", use_last_error=True)
try:
    msimg32 = ctypes.WinDLL("msimg32", use_last_error=True)
except OSError:
    msimg32 = None

LRESULT = c_ssize_t
WNDPROC = WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
WNDENUMPROC = WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
WINEVENTPROC = WINFUNCTYPE(None, wt.HANDLE, wt.DWORD, wt.HWND, wt.LONG, wt.LONG,
                           wt.DWORD, wt.DWORD)
RECT = wt.RECT


class WNDCLASSW(Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", c_int), ("cbWndExtra", c_int),
                ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]


class PAINTSTRUCT(Structure):
    _fields_ = [("hdc", wt.HDC), ("fErase", wt.BOOL), ("rcPaint", RECT),
                ("fRestore", wt.BOOL), ("fIncUpdate", wt.BOOL),
                ("rgbReserved", c_ubyte * 32)]


class ICONINFO(Structure):
    _fields_ = [("fIcon", wt.BOOL), ("xHotspot", wt.DWORD), ("yHotspot", wt.DWORD),
                ("hbmMask", wt.HBITMAP), ("hbmColor", wt.HBITMAP)]


class BITMAP(Structure):
    _fields_ = [("bmType", wt.LONG), ("bmWidth", wt.LONG), ("bmHeight", wt.LONG),
                ("bmWidthBytes", wt.LONG), ("bmPlanes", wt.WORD),
                ("bmBitsPixel", wt.WORD), ("bmBits", c_void_p)]


class BITMAPINFOHEADER(Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


class TRACKMOUSEEVENT(Structure):
    _fields_ = [("cbSize", wt.DWORD), ("dwFlags", wt.DWORD),
                ("hwndTrack", wt.HWND), ("dwHoverTime", wt.DWORD)]


class WINDOWPOS(Structure):
    _fields_ = [("hwnd", wt.HWND), ("hwndInsertAfter", wt.HWND), ("x", c_int),
                ("y", c_int), ("cx", c_int), ("cy", c_int), ("flags", wt.UINT)]


class SHFILEINFOW(Structure):
    _fields_ = [("hIcon", wt.HICON), ("iIcon", c_int), ("dwAttributes", wt.DWORD),
                ("szDisplayName", wt.WCHAR * 260), ("szTypeName", wt.WCHAR * 80)]


class OPENFILENAMEW(Structure):
    _fields_ = [("lStructSize", wt.DWORD), ("hwndOwner", wt.HWND),
                ("hInstance", wt.HINSTANCE), ("lpstrFilter", wt.LPCWSTR),
                ("lpstrCustomFilter", wt.LPWSTR), ("nMaxCustFilter", wt.DWORD),
                ("nFilterIndex", wt.DWORD), ("lpstrFile", wt.LPWSTR),
                ("nMaxFile", wt.DWORD), ("lpstrFileTitle", wt.LPWSTR),
                ("nMaxFileTitle", wt.DWORD), ("lpstrInitialDir", wt.LPCWSTR),
                ("lpstrTitle", wt.LPCWSTR), ("Flags", wt.DWORD),
                ("nFileOffset", wt.WORD), ("nFileExtension", wt.WORD),
                ("lpstrDefExt", wt.LPCWSTR), ("lCustData", wt.LPARAM),
                ("lpfnHook", c_void_p), ("lpTemplateName", wt.LPCWSTR),
                ("pvReserved", c_void_p), ("dwReserved", wt.DWORD),
                ("FlagsEx", wt.DWORD)]


class GdiplusStartupInput(Structure):
    _fields_ = [("GdiplusVersion", wt.UINT), ("DebugEventCallback", c_void_p),
                ("SuppressBackgroundThread", wt.BOOL),
                ("SuppressExternalCodecs", wt.BOOL)]


class MEASUREITEMSTRUCT(Structure):
    _fields_ = [("CtlType", wt.UINT), ("CtlID", wt.UINT), ("itemID", wt.UINT),
                ("itemWidth", wt.UINT), ("itemHeight", wt.UINT), ("itemData", c_size_t)]


class MENUINFO(Structure):
    _fields_ = [("cbSize", wt.DWORD), ("fMask", wt.DWORD), ("dwStyle", wt.DWORD),
                ("cyMax", wt.UINT), ("hbrBack", wt.HBRUSH), ("dwContextHelpID", wt.DWORD),
                ("dwMenuData", c_size_t)]


class COPYDATASTRUCT(Structure):
    _fields_ = [("dwData", c_size_t), ("cbData", wt.DWORD), ("lpData", c_void_p)]


class BROWSEINFOW(Structure):
    _fields_ = [("hwndOwner", wt.HWND), ("pidlRoot", c_void_p), ("pszDisplayName", wt.LPWSTR),
                ("lpszTitle", wt.LPCWSTR), ("ulFlags", wt.UINT), ("lpfn", c_void_p),
                ("lParam", wt.LPARAM), ("iImage", c_int)]


class DRAWITEMSTRUCT(Structure):
    _fields_ = [("CtlType", wt.UINT), ("CtlID", wt.UINT), ("itemID", wt.UINT),
                ("itemAction", wt.UINT), ("itemState", wt.UINT), ("hwndItem", wt.HWND),
                ("hDC", wt.HDC), ("rcItem", RECT), ("itemData", c_size_t)]


class CHOOSECOLORW(Structure):
    _fields_ = [("lStructSize", wt.DWORD), ("hwndOwner", wt.HWND), ("hInstance", wt.HWND),
                ("rgbResult", wt.DWORD), ("lpCustColors", POINTER(wt.DWORD)),
                ("Flags", wt.DWORD), ("lCustData", wt.LPARAM), ("lpfnHook", c_void_p),
                ("lpTemplateName", wt.LPCWSTR)]


class SYSTEMTIME(Structure):
    _fields_ = [(n, wt.WORD) for n in ("wYear", "wMonth", "wDayOfWeek", "wDay", "wHour",
                                       "wMinute", "wSecond", "wMilliseconds")]


class LOGFONTW(Structure):
    _fields_ = [("lfHeight", wt.LONG), ("lfWidth", wt.LONG), ("lfEscapement", wt.LONG),
                ("lfOrientation", wt.LONG), ("lfWeight", wt.LONG),
                ("lfItalic", wt.BYTE), ("lfUnderline", wt.BYTE), ("lfStrikeOut", wt.BYTE),
                ("lfCharSet", wt.BYTE), ("lfOutPrecision", wt.BYTE),
                ("lfClipPrecision", wt.BYTE), ("lfQuality", wt.BYTE),
                ("lfPitchAndFamily", wt.BYTE), ("lfFaceName", wt.WCHAR * 32)]


class NONCLIENTMETRICSW(Structure):
    _fields_ = [("cbSize", wt.UINT), ("iBorderWidth", c_int), ("iScrollWidth", c_int),
                ("iScrollHeight", c_int), ("iCaptionWidth", c_int),
                ("iCaptionHeight", c_int), ("lfCaptionFont", LOGFONTW),
                ("iSmCaptionWidth", c_int), ("iSmCaptionHeight", c_int),
                ("lfSmCaptionFont", LOGFONTW), ("iMenuWidth", c_int),
                ("iMenuHeight", c_int), ("lfMenuFont", LOGFONTW),
                ("lfStatusFont", LOGFONTW), ("lfMessageFont", LOGFONTW),
                ("iPaddedBorderWidth", c_int)]


def api(dll, name, restype, *argtypes):
    fn = dll[name]            # indexing gives a fresh function object each time
    fn.restype = restype
    fn.argtypes = list(argtypes)
    return fn


H, U, I, D = wt.HWND, wt.UINT, c_int, wt.DWORD
RegisterClassW = api(user32, "RegisterClassW", wt.ATOM, POINTER(WNDCLASSW))
CreateWindowExW = api(user32, "CreateWindowExW", wt.HWND, D, wt.LPCWSTR, wt.LPCWSTR,
                      D, I, I, I, I, H, wt.HMENU, wt.HINSTANCE, c_void_p)
DestroyWindow = api(user32, "DestroyWindow", wt.BOOL, H)
IsWindow = api(user32, "IsWindow", wt.BOOL, H)
DefWindowProcW = api(user32, "DefWindowProcW", LRESULT, H, U, wt.WPARAM, wt.LPARAM)
GetMessageW = api(user32, "GetMessageW", c_int, POINTER(wt.MSG), H, U, U)
TranslateMessage = api(user32, "TranslateMessage", wt.BOOL, POINTER(wt.MSG))
DispatchMessageW = api(user32, "DispatchMessageW", LRESULT, POINTER(wt.MSG))
PostQuitMessage = api(user32, "PostQuitMessage", None, I)
PostMessageW = api(user32, "PostMessageW", wt.BOOL, H, U, wt.WPARAM, wt.LPARAM)
SendMessageW = api(user32, "SendMessageW", LRESULT, H, U, c_size_t, c_ssize_t)
SendMessageS = api(user32, "SendMessageW", LRESULT, H, U, c_size_t, c_wchar_p)
SetTimer = api(user32, "SetTimer", c_size_t, H, c_size_t, U, c_void_p)
KillTimer = api(user32, "KillTimer", wt.BOOL, H, c_size_t)
InvalidateRect = api(user32, "InvalidateRect", wt.BOOL, H, POINTER(RECT), wt.BOOL)
BeginPaint = api(user32, "BeginPaint", wt.HDC, H, POINTER(PAINTSTRUCT))
EndPaint = api(user32, "EndPaint", wt.BOOL, H, POINTER(PAINTSTRUCT))
GetClientRect = api(user32, "GetClientRect", wt.BOOL, H, POINTER(RECT))
GetWindowRect = api(user32, "GetWindowRect", wt.BOOL, H, POINTER(RECT))
FillRect = api(user32, "FillRect", I, wt.HDC, POINTER(RECT), wt.HBRUSH)
DrawTextW = api(user32, "DrawTextW", I, wt.HDC, wt.LPCWSTR, I, POINTER(RECT), U)
DrawIconEx = api(user32, "DrawIconEx", wt.BOOL, wt.HDC, I, I, wt.HICON, I, I, U,
                 wt.HBRUSH, U)
LoadCursorW = api(user32, "LoadCursorW", wt.HANDLE, wt.HINSTANCE, c_void_p)
LoadIconW = api(user32, "LoadIconW", wt.HICON, wt.HINSTANCE, c_void_p)
LoadImageW = api(user32, "LoadImageW", wt.HANDLE, wt.HINSTANCE, wt.LPCWSTR, U, I, I, U)
EnumWindows = api(user32, "EnumWindows", wt.BOOL, WNDENUMPROC, wt.LPARAM)
IsWindowVisible = api(user32, "IsWindowVisible", wt.BOOL, H)
IsIconic = api(user32, "IsIconic", wt.BOOL, H)
IsZoomed = api(user32, "IsZoomed", wt.BOOL, H)
GetWindowLongW = api(user32, "GetWindowLongW", wt.LONG, H, I)
SetWindowLongW = api(user32, "SetWindowLongW", wt.LONG, H, I, wt.LONG)
SetLayeredWindowAttributes = api(user32, "SetLayeredWindowAttributes", wt.BOOL, H,
                                 D, c_ubyte, D)
GetWindow = api(user32, "GetWindow", wt.HWND, H, U)
GetAncestor = api(user32, "GetAncestor", wt.HWND, H, U)
GetWindowTextW = api(user32, "GetWindowTextW", I, H, wt.LPWSTR, I)
SetWindowTextW = api(user32, "SetWindowTextW", wt.BOOL, H, wt.LPCWSTR)
GetClassNameW = api(user32, "GetClassNameW", I, H, wt.LPWSTR, I)
GetWindowThreadProcessId = api(user32, "GetWindowThreadProcessId", D, H, POINTER(D))
SendMessageTimeoutW = api(user32, "SendMessageTimeoutW", LRESULT, H, U, wt.WPARAM,
                          wt.LPARAM, U, U, POINTER(c_size_t))
try:
    _gclp = api(user32, "GetClassLongPtrW", c_size_t, H, I)
except (AttributeError, OSError):
    _gclp = api(user32, "GetClassLongW", c_size_t, H, I)
ShowWindow = api(user32, "ShowWindow", wt.BOOL, H, I)
SetForegroundWindow = api(user32, "SetForegroundWindow", wt.BOOL, H)
GetForegroundWindow = api(user32, "GetForegroundWindow", wt.HWND)
SetFocus = api(user32, "SetFocus", wt.HWND, H)
SetCapture = api(user32, "SetCapture", wt.HWND, H)
ReleaseCapture = api(user32, "ReleaseCapture", wt.BOOL)
GetKeyState = api(user32, "GetKeyState", c_short, I)
CreatePopupMenu = api(user32, "CreatePopupMenu", wt.HMENU)
AppendMenuW = api(user32, "AppendMenuW", wt.BOOL, wt.HMENU, U, c_size_t, wt.LPCWSTR)
TrackPopupMenu = api(user32, "TrackPopupMenu", wt.BOOL, wt.HMENU, U, I, I, I, H,
                     c_void_p)
DestroyMenu = api(user32, "DestroyMenu", wt.BOOL, wt.HMENU)
SetWindowPos = api(user32, "SetWindowPos", wt.BOOL, H, H, I, I, I, I, U)
SystemParametersInfoW = api(user32, "SystemParametersInfoW", wt.BOOL, U, U,
                            c_void_p, U)
GetSystemMetrics = api(user32, "GetSystemMetrics", I, I)
RegisterWindowMessageW = api(user32, "RegisterWindowMessageW", U, wt.LPCWSTR)
RegisterShellHookWindow = api(user32, "RegisterShellHookWindow", wt.BOOL, H)
DeregisterShellHookWindow = api(user32, "DeregisterShellHookWindow", wt.BOOL, H)
TrackMouseEvent = api(user32, "TrackMouseEvent", wt.BOOL, POINTER(TRACKMOUSEEVENT))
GetCursorPos = api(user32, "GetCursorPos", wt.BOOL, POINTER(wt.POINT))
GetIconInfo = api(user32, "GetIconInfo", wt.BOOL, wt.HICON, POINTER(ICONINFO))
DestroyIcon = api(user32, "DestroyIcon", wt.BOOL, wt.HICON)
GetDC = api(user32, "GetDC", wt.HDC, H)
ReleaseDC = api(user32, "ReleaseDC", I, H, wt.HDC)
FindWindowW = api(user32, "FindWindowW", wt.HWND, wt.LPCWSTR, wt.LPCWSTR)
ExtractIconExW = api(shell32, "ExtractIconExW", U, wt.LPCWSTR, I, POINTER(wt.HICON),
                     POINTER(wt.HICON), U)
SHGetFileInfoW = api(shell32, "SHGetFileInfoW", c_size_t, wt.LPCWSTR, D,
                     POINTER(SHFILEINFOW), U, U)
ShellExecuteW = api(shell32, "ShellExecuteW", wt.HINSTANCE, H, wt.LPCWSTR,
                    wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, I)
GetOpenFileNameW = api(comdlg32, "GetOpenFileNameW", wt.BOOL, POINTER(OPENFILENAMEW))

CreateSolidBrush = api(gdi32, "CreateSolidBrush", wt.HBRUSH, wt.DWORD)
CreatePen = api(gdi32, "CreatePen", wt.HANDLE, I, I, wt.DWORD)
GetStockObject = api(gdi32, "GetStockObject", c_void_p, I)
DeleteObject = api(gdi32, "DeleteObject", wt.BOOL, c_void_p)
CreateCompatibleDC = api(gdi32, "CreateCompatibleDC", wt.HDC, wt.HDC)
CreateCompatibleBitmap = api(gdi32, "CreateCompatibleBitmap", wt.HBITMAP, wt.HDC, I, I)
SelectObject = api(gdi32, "SelectObject", c_void_p, wt.HDC, c_void_p)
BitBlt = api(gdi32, "BitBlt", wt.BOOL, wt.HDC, I, I, I, I, wt.HDC, I, I, D)
StretchBlt = api(gdi32, "StretchBlt", wt.BOOL, wt.HDC, I, I, I, I, wt.HDC, I, I, I, I, D)
SetStretchBltMode = api(gdi32, "SetStretchBltMode", I, wt.HDC, I)
DeleteDC = api(gdi32, "DeleteDC", wt.BOOL, wt.HDC)
SetBkMode = api(gdi32, "SetBkMode", I, wt.HDC, I)
SetTextColor = api(gdi32, "SetTextColor", wt.DWORD, wt.HDC, wt.DWORD)
SetPixel = api(gdi32, "SetPixel", wt.DWORD, wt.HDC, I, I, wt.DWORD)
MoveToEx = api(gdi32, "MoveToEx", wt.BOOL, wt.HDC, I, I, c_void_p)
LineTo = api(gdi32, "LineTo", wt.BOOL, wt.HDC, I, I)
Rectangle = api(gdi32, "Rectangle", wt.BOOL, wt.HDC, I, I, I, I)
Ellipse = api(gdi32, "Ellipse", wt.BOOL, wt.HDC, I, I, I, I)
CreateEllipticRgn = api(gdi32, "CreateEllipticRgn", c_void_p, I, I, I, I)
SelectClipRgn = api(gdi32, "SelectClipRgn", I, wt.HDC, c_void_p)
CreateFontW = api(gdi32, "CreateFontW", wt.HFONT, I, I, I, I, I, D, D, D, D, D, D, D,
                  D, wt.LPCWSTR)
GetObjectW = api(gdi32, "GetObjectW", I, c_void_p, I, c_void_p)
GetDIBits = api(gdi32, "GetDIBits", I, wt.HDC, wt.HBITMAP, U, U, c_void_p, c_void_p, U)
AlphaBlend = (api(msimg32, "AlphaBlend", wt.BOOL, wt.HDC, I, I, I, I, wt.HDC, I, I, I,
                  I, wt.DWORD) if msimg32 else None)

SetSysColors = api(user32, "SetSysColors", wt.BOOL, I, POINTER(c_int), POINTER(wt.DWORD))
GetSysColor = api(user32, "GetSysColor", wt.DWORD, I)
RedrawWindow = api(user32, "RedrawWindow", wt.BOOL, H, c_void_p, c_void_p, U)
MessageBoxW = api(user32, "MessageBoxW", I, H, wt.LPCWSTR, wt.LPCWSTR, U)
CreateIconIndirect = api(user32, "CreateIconIndirect", wt.HICON, POINTER(ICONINFO))
GetAsyncKeyState = api(user32, "GetAsyncKeyState", c_short, I)
AppendMenuData = api(user32, "AppendMenuW", wt.BOOL, wt.HMENU, U, c_size_t, c_size_t)
SetMenuInfo = api(user32, "SetMenuInfo", wt.BOOL, wt.HMENU, POINTER(MENUINFO))
GetTextExtentPoint32W = api(gdi32, "GetTextExtentPoint32W", wt.BOOL, wt.HDC, wt.LPCWSTR, I,
                            POINTER(wt.SIZE))
SHBrowseForFolderW = api(shell32, "SHBrowseForFolderW", c_void_p, POINTER(BROWSEINFOW))
SHGetPathFromIDListW = api(shell32, "SHGetPathFromIDListW", wt.BOOL, c_void_p, wt.LPWSTR)
try:
    SetWinEventHook = api(user32, "SetWinEventHook", wt.HANDLE, wt.DWORD, wt.DWORD,
                          wt.HMODULE, WINEVENTPROC, wt.DWORD, wt.DWORD, wt.DWORD)
    UnhookWinEvent = api(user32, "UnhookWinEvent", wt.BOOL, wt.HANDLE)
except (AttributeError, OSError):
    SetWinEventHook = UnhookWinEvent = None
GetPixel = api(gdi32, "GetPixel", wt.DWORD, wt.HDC, I, I)
PrintWindow = api(user32, "PrintWindow", wt.BOOL, H, wt.HDC, U)
SetWindowRgn = api(user32, "SetWindowRgn", I, H, c_void_p, wt.BOOL)
ChooseColorW = api(comdlg32, "ChooseColorW", wt.BOOL, POINTER(CHOOSECOLORW))
SetBkColor = api(gdi32, "SetBkColor", wt.DWORD, wt.HDC, wt.DWORD)
CreateBitmap = api(gdi32, "CreateBitmap", wt.HBITMAP, I, I, U, U, c_void_p)
SetLocalTime = api(kernel32, "SetLocalTime", wt.BOOL, POINTER(SYSTEMTIME))
GetModuleHandleW = api(kernel32, "GetModuleHandleW", wt.HMODULE, wt.LPCWSTR)
CreateMutexW = api(kernel32, "CreateMutexW", wt.HANDLE, c_void_p, wt.BOOL, wt.LPCWSTR)
OpenProcess = api(kernel32, "OpenProcess", wt.HANDLE, D, wt.BOOL, D)
CloseHandle = api(kernel32, "CloseHandle", wt.BOOL, wt.HANDLE)
QueryFullProcessImageNameW = api(kernel32, "QueryFullProcessImageNameW", wt.BOOL,
                                 wt.HANDLE, D, wt.LPWSTR, POINTER(D))

# --- messages / styles / flags
WM_DESTROY, WM_ACTIVATE, WM_PAINT, WM_CLOSE = 0x2, 0x6, 0xF, 0x10
WM_ERASEBKGND, WM_MOUSEACTIVATE, WM_SETFONT = 0x14, 0x21, 0x30
WM_WINDOWPOSCHANGING, WM_DISPLAYCHANGE = 0x46, 0x7E
WM_KEYDOWN, WM_CHAR, WM_COMMAND, WM_SYSCOMMAND = 0x100, 0x102, 0x111, 0x112
WM_TIMER, WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x113, 0x200, 0x201, 0x202
WM_LBUTTONDBLCLK, WM_RBUTTONUP, WM_MBUTTONUP = 0x203, 0x205, 0x208
WM_MOUSEWHEEL, WM_MOUSELEAVE, WM_GETICON = 0x20A, 0x2A3, 0x7F
WS_POPUP, WS_VISIBLE, WS_CHILD = 0x80000000, 0x10000000, 0x40000000
WS_TABSTOP, WS_VSCROLL, WS_BORDER = 0x10000, 0x200000, 0x800000
WS_CAPTION, WS_SYSMENU, WS_MINIMIZEBOX = 0xC00000, 0x80000, 0x20000
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = 0x8, 0x80, 0x40000
WS_EX_NOACTIVATE, WS_EX_LAYERED, WS_EX_CLIENTEDGE = 0x8000000, 0x80000, 0x200
GWL_EXSTYLE, GW_OWNER, GA_ROOTOWNER = -20, 4, 3
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10
HWND_BOTTOM, HWND_TOPMOST, HWND_NOTOPMOST = 1, -1, -2
SPI_GETWORKAREA, SPI_SETWORKAREA, SPIF_SENDCHANGE = 48, 47, 2
SRCCOPY = 0x00CC0020
DT_CENTER, DT_VCENTER, DT_SINGLELINE, DT_WORDBREAK = 0x1, 0x4, 0x20, 0x10
DT_CALCRECT, DT_NOPREFIX, DT_END_ELLIPSIS = 0x400, 0x800, 0x8000
MF_STRING, MF_GRAYED, MF_CHECKED, MF_POPUP, MF_SEPARATOR = 0x0, 0x1, 0x8, 0x10, 0x800
TPM_RETURNCMD, TPM_BOTTOMALIGN, TPM_RIGHTBUTTON = 0x100, 0x20, 0x2
IGNORED_CLASSES = {"Progman", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "WorkerW",
                   "WinShellBar", "WinShellStart", "WinShellDesktop", "#32769",
                   "Program Manager"}


WM_SETICON, WM_CTLCOLOREDIT, WM_SIZE, EN_CHANGE = 0x80, 0x133, 0x5, 0x300
THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\ThemeManager"
LOOK_KEYS = {"window_look", "look_title_accent", "look_caption_height",
             "look_scrollbar_width", "theme_file", "accent"}


def screen_size():
    return GetSystemMetrics(0), GetSystemMetrics(1)


# ==========================================================================
# Drawing / path helpers
# ==========================================================================
def fill(hdc, rect, color):
    brush = CreateSolidBrush(color)
    FillRect(hdc, byref(RECT(*[int(v) for v in rect])), brush)
    DeleteObject(brush)


def frame(hdc, rect, color, t=1):
    l, tp, r, b = [int(v) for v in rect]
    fill(hdc, (l, tp, r, tp + t), color)
    fill(hdc, (l, b - t, r, b), color)
    fill(hdc, (l, tp, l + t, b), color)
    fill(hdc, (r - t, tp, r, b), color)


def alpha_rect(hdc, rect, color, alpha):
    l, t, r, b = [int(v) for v in rect]
    if r <= l or b <= t:
        return
    if AlphaBlend is None:
        return
    mem = CreateCompatibleDC(hdc)
    bmp = CreateCompatibleBitmap(hdc, 1, 1)
    old = SelectObject(mem, bmp)
    SetPixel(mem, 0, 0, color)
    AlphaBlend(hdc, l, t, r - l, b - t, mem, 0, 0, 1, 1, (alpha & 255) << 16)
    SelectObject(mem, old)
    DeleteObject(bmp)
    DeleteDC(mem)


def text_out(hdc, s, rect, flags, color):
    r = RECT(*[int(v) for v in rect])
    SetTextColor(hdc, color)
    DrawTextW(hdc, s, -1, byref(r), flags)


def make_font(name, size, weight=400):
    return CreateFontW(-int(size), 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 5, 0, str(name))


def apply_glass(hwnd, on, pct):
    ex = s32(GetWindowLongW(hwnd, GWL_EXSTYLE))
    if on:
        SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED)
        alpha = int(255 * max(30, min(100, int(pct))) / 100)
        SetLayeredWindowAttributes(hwnd, 0, alpha, 2)
    elif ex & WS_EX_LAYERED:
        SetWindowLongW(hwnd, GWL_EXSTYLE, ex & ~WS_EX_LAYERED)


def get_title(hwnd):
    buf = create_unicode_buffer(256)
    GetWindowTextW(hwnd, buf, 256)
    return buf.value


def get_class(hwnd):
    buf = create_unicode_buffer(128)
    GetClassNameW(hwnd, buf, 128)
    return buf.value


def process_path(hwnd):
    pid = wt.DWORD(0)
    GetWindowThreadProcessId(hwnd, byref(pid))
    if not pid.value:
        return ""
    handle = OpenProcess(0x1000, False, pid.value)
    if not handle:
        return ""
    try:
        buf = create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if QueryFullProcessImageNameW(handle, 0, buf, byref(size)):
            return buf.value
    except Exception as exc:
        log.info("process_path failed: %s", exc)
    finally:
        CloseHandle(handle)
    return ""


def find_exe(name):
    if os.path.isabs(name) or os.path.exists(name):
        return name
    root = os.environ.get("SystemRoot", r"C:\windows")
    for d in (root, os.path.join(root, "system32"), os.path.join(root, "syswow64")):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return name


def lnk_target(path):
    """Read the target path from a .lnk file (LinkInfo section)."""
    try:
        with open(path, "rb") as f:
            data = f.read(65536)
        if len(data) < 76 or struct.unpack_from("<I", data, 0)[0] != 0x4C:
            return None
        flags = struct.unpack_from("<I", data, 0x14)[0]
        pos = 76
        if flags & 1:
            pos += 2 + struct.unpack_from("<H", data, pos)[0]
        if not flags & 2:
            return None
        base = pos
        _sz, _hdr, lf, _vol, local_off, _net, suffix_off = struct.unpack_from(
            "<7I", data, base)
        if not lf & 1:
            return None

        def cstr(off):
            end = data.index(b"\0", base + off)
            raw = data[base + off:end]
            try:
                return raw.decode("mbcs")
            except Exception:
                return raw.decode("latin-1")

        return cstr(local_off) + (cstr(suffix_off) if suffix_off else "")
    except Exception:
        return None


def exe_for(path):
    if path.lower().endswith(".lnk"):
        t = lnk_target(path)
        if t and os.path.exists(t):
            return t
    return find_exe(path)


def app_key(path):
    return os.path.basename(path).lower()


def display_name(path):
    if path == "::thispc":
        return "This PC"
    base = os.path.basename(path.rstrip("\\/")) or path
    name = os.path.splitext(base)[0] if base.lower().endswith((".exe", ".lnk")) else base
    name = name.replace("_", " ")
    return name.title() if name.islower() else name


# ---- images (BMP natively, everything else through GDI+)
_IMAGES = {}
_gdip = {"ready": None, "lib": None}


def gdip_start():
    if _gdip["ready"] is not None:
        return _gdip["ready"]
    _gdip["ready"] = False
    try:
        lib = ctypes.WinDLL("gdiplus")
        lib["GdiplusStartup"].argtypes = [POINTER(c_size_t),
                                          POINTER(GdiplusStartupInput), c_void_p]
        lib["GdipCreateBitmapFromFile"].argtypes = [wt.LPCWSTR, POINTER(c_void_p)]
        lib["GdipCreateHBITMAPFromBitmap"].argtypes = [c_void_p, POINTER(wt.HBITMAP),
                                                       wt.DWORD]
        lib["GdipDisposeImage"].argtypes = [c_void_p]
        lib["GdipCreateHICONFromBitmap"].argtypes = [c_void_p, POINTER(wt.HICON)]
        token = c_size_t(0)
        inp = GdiplusStartupInput(1, None, False, False)
        if lib["GdiplusStartup"](byref(token), byref(inp), None) == 0:
            _gdip["lib"], _gdip["ready"] = lib, True
    except Exception as exc:
        log.info("GDI+ unavailable: %s", exc)
    return _gdip["ready"]


def load_image(path):
    """Return (HBITMAP, width, height) or None."""
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return None
    if key in _IMAGES:
        return _IMAGES[key]
    hbm = None
    if path.lower().endswith(".bmp"):
        hbm = LoadImageW(None, path, 0, 0, 0, 0x10 | 0x2000)
    if not hbm and gdip_start():
        lib = _gdip["lib"]
        bmp, out = c_void_p(), wt.HBITMAP()
        if lib["GdipCreateBitmapFromFile"](path, byref(bmp)) == 0:
            lib["GdipCreateHBITMAPFromBitmap"](bmp, byref(out), 0xFF202020)
            lib["GdipDisposeImage"](bmp)
            hbm = out.value
    if not hbm:
        return None
    bm = BITMAP()
    GetObjectW(hbm, sizeof(bm), byref(bm))
    if len(_IMAGES) >= 8:
        for old in list(_IMAGES.values()):
            DeleteObject(old[0])
        _IMAGES.clear()
    _IMAGES[key] = (hbm, bm.bmWidth, bm.bmHeight)
    return _IMAGES[key]


def browse_file(owner, title, flt):
    buf = create_unicode_buffer(1024)
    ofn = OPENFILENAMEW()
    ofn.lStructSize = sizeof(ofn)
    ofn.hwndOwner = owner
    ofn.lpstrFilter = flt
    ofn.lpstrFile = ctypes.cast(buf, wt.LPWSTR)
    ofn.nMaxFile = 1024
    ofn.lpstrTitle = title
    ofn.Flags = 0x1000 | 0x800 | 0x80000 | 0x8
    if GetOpenFileNameW(byref(ofn)):
        return buf.value
    return ""


FILTER_IMAGES = "Images\0*.png;*.jpg;*.jpeg;*.bmp;*.gif\0All files\0*.*\0\0"
FILTER_PROGRAMS = "Programs\0*.exe;*.lnk;*.bat\0All files\0*.*\0\0"
FILTER_ALL = "All files\0*.*\0\0"
FILTER_ICONS = "Icons\0*.ico;*.png\0All files\0*.*\0\0"
FILTER_THEME = "Visual styles\0*.msstyles\0All files\0*.*\0\0"


def render_wallpaper(c, sw, sh):
    """Wallpaper (or solid colour) rendered at full screen size -> HBITMAP."""
    hdc = GetDC(None)
    mem = CreateCompatibleDC(hdc)
    bmp = CreateCompatibleBitmap(hdc, sw, sh)
    old = SelectObject(mem, bmp)
    fill(mem, (0, 0, sw, sh), hex_color(c["desktop_color"], rgb(30, 58, 95)))
    img = load_image(c["wallpaper"]) if c["wallpaper"] else None
    if img:
        src = CreateCompatibleDC(hdc)
        so = SelectObject(src, img[0])
        w, h = max(1, img[1]), max(1, img[2])
        SetStretchBltMode(mem, 4)
        mode = c["wallpaper_mode"]
        if mode == "tile":
            for ty in range(0, sh, h):
                for tx in range(0, sw, w):
                    BitBlt(mem, tx, ty, w, h, src, 0, 0, SRCCOPY)
        else:
            if mode == "stretch":
                dw, dh = sw, sh
            elif mode == "center":
                dw, dh = w, h
            else:
                s = max(sw / w, sh / h) if mode == "fill" else min(sw / w, sh / h)
                dw, dh = int(w * s), int(h * s)
            StretchBlt(mem, (sw - dw) // 2, (sh - dh) // 2, dw, dh, src, 0, 0, w, h, SRCCOPY)
        SelectObject(src, so)
        DeleteDC(src)
    SelectObject(mem, old)
    DeleteDC(mem)
    ReleaseDC(None, hdc)
    return bmp


def blur_bitmap(src_bmp, sw, sh):
    """Cheap blur: shrink to 1/24 then stretch back with halftone filtering."""
    hdc = GetDC(None)
    a, b = CreateCompatibleDC(hdc), CreateCompatibleDC(hdc)
    tw, tht = max(1, sw // 24), max(1, sh // 24)
    small = CreateCompatibleBitmap(hdc, tw, tht)
    big = CreateCompatibleBitmap(hdc, sw, sh)
    oa, ob = SelectObject(a, src_bmp), SelectObject(b, small)
    SetStretchBltMode(b, 4)
    StretchBlt(b, 0, 0, tw, tht, a, 0, 0, sw, sh, SRCCOPY)
    SelectObject(a, oa)
    oa = SelectObject(a, big)
    SetStretchBltMode(a, 4)
    StretchBlt(a, 0, 0, sw, sh, b, 0, 0, tw, tht, SRCCOPY)
    SelectObject(a, oa)
    SelectObject(b, ob)
    DeleteDC(a)
    DeleteDC(b)
    DeleteObject(small)
    ReleaseDC(None, hdc)
    return big


_ICON_CACHE = {}


def load_icon_file(path, size):
    """HICON from a .ico or .png/.jpg file (alpha kept for PNG), cached."""
    try:
        key = (path, os.path.getmtime(path), size)
    except OSError:
        return 0
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    icon = 0
    if path.lower().endswith(".ico"):
        icon = LoadImageW(None, path, 1, size, size, 0x10) or 0
    if not icon and gdip_start():
        lib = _gdip["lib"]
        bmp, out = c_void_p(), wt.HICON()
        if lib["GdipCreateBitmapFromFile"](path, byref(bmp)) == 0:
            if lib["GdipCreateHICONFromBitmap"](bmp, byref(out)) == 0:
                icon = out.value or 0
            lib["GdipDisposeImage"](bmp)
    _ICON_CACHE[key] = icon
    return icon


def make_folder_icon(size=32):
    """Self-drawn yellow folder icon (our own artwork, not a Microsoft asset)."""
    w = h = size
    px = bytearray(w * h * 4)
    s = size / 32.0

    def rect(x0, y0, x1, y1, col):
        for y in range(int(y0 * s), int(y1 * s)):
            for x in range(int(x0 * s), int(x1 * s)):
                i = (y * w + x) * 4
                px[i], px[i + 1], px[i + 2], px[i + 3] = col[2], col[1], col[0], 255

    rect(2, 6, 14, 10, (222, 170, 30))          # tab
    rect(2, 8, 30, 26, (232, 184, 48))          # back panel
    rect(2, 12, 30, 27, (255, 216, 84))         # front panel
    rect(2, 12, 30, 13, (255, 238, 170))        # highlight
    color = CreateBitmap(w, h, 1, 32, (c_ubyte * len(px)).from_buffer(px))
    mask = CreateBitmap(w, h, 1, 1, (c_ubyte * (((w + 15) // 16) * 2 * h))())
    ii = ICONINFO()
    ii.fIcon, ii.hbmMask, ii.hbmColor = True, mask, color
    icon = CreateIconIndirect(byref(ii))
    DeleteObject(color)
    DeleteObject(mask)
    return icon or 0


def reg_set(path, name, value):
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
    except Exception:
        try:
            subprocess.run(["reg.exe", "add", "HKCU\\" + path, "/v", name, "/t", "REG_SZ",
                            "/d", value, "/f"], timeout=10)
        except Exception as exc:
            log.warning("reg_set failed: %s", exc)


def drive_list():
    return [d + ":\\" for d in "CDEFGHIJKLMNOPQRSTUVWXYZAB" if os.path.exists(d + ":\\")]


def look_palette(dark, acc, title_accent):
    """System colours (COLOR_* index -> rgb tuple) for the Windows 10 window look."""
    A = split_rgb(acc)
    cap = A if title_accent else ((0, 0, 0) if dark else (255, 255, 255))
    cap_text = (255, 255, 255) if (title_accent or dark) else (0, 0, 0)
    icap = (43, 43, 43) if dark else (255, 255, 255)
    win = (32, 32, 32) if dark else (255, 255, 255)
    face = (51, 51, 51) if dark else (240, 240, 240)
    text = (255, 255, 255) if dark else (0, 0, 0)
    return {0: (60, 60, 60) if dark else (200, 200, 200), 2: cap, 3: icap, 4: face, 5: win,
            6: (100, 100, 100), 7: text, 8: text, 9: cap_text,
            10: A if title_accent else ((60, 60, 60) if dark else (170, 170, 170)),
            11: (60, 60, 60) if dark else (170, 170, 170),
            12: (45, 45, 45) if dark else (171, 171, 171), 13: A, 14: (255, 255, 255),
            15: face, 16: (110, 110, 110) if dark else (160, 160, 160), 17: (140, 140, 140),
            18: text, 19: (170, 170, 170) if dark else (153, 153, 153),
            20: (80, 80, 80) if dark else (255, 255, 255), 21: (105, 105, 105),
            22: (70, 70, 70) if dark else (227, 227, 227), 23: text,
            24: (60, 60, 40) if dark else (255, 255, 225), 26: A, 27: cap, 28: icap,
            29: A, 30: win}


# ==========================================================================
# Icons: real icon of any app + colour adapted from the icon
# ==========================================================================
def icon_accent(hicon):
    ii = ICONINFO()
    if not hicon or not GetIconInfo(hicon, byref(ii)):
        return None
    try:
        if not ii.hbmColor:
            return None
        bm = BITMAP()
        if not GetObjectW(ii.hbmColor, sizeof(bm), byref(bm)):
            return None
        w, h = bm.bmWidth, bm.bmHeight
        if not (0 < w <= 256 and 0 < h <= 256):
            return None
        bih = BITMAPINFOHEADER()
        bih.biSize, bih.biWidth, bih.biHeight = sizeof(bih), w, -h
        bih.biPlanes, bih.biBitCount = 1, 32
        buf = (c_ubyte * (w * h * 4))()
        hdc = GetDC(None)
        try:
            lines = GetDIBits(hdc, ii.hbmColor, 0, h, buf, byref(bih), 0)
        finally:
            ReleaseDC(None, hdc)
        if lines != h:
            return None
        data = bytes(buf)
        has_alpha = any(data[i] for i in range(3, len(data), 4))
        rs = gs = bs = ws = 0
        for i in range(0, len(data), 4):
            b, g, r, a = data[i], data[i + 1], data[i + 2], data[i + 3]
            if has_alpha and a < 128:
                continue
            mx, mn = max(r, g, b), min(r, g, b)
            wgt = 1 if mx < 24 else (mx - mn) + 8
            rs, gs, bs, ws = rs + r * wgt, gs + g * wgt, bs + b * wgt, ws + wgt
        if not ws:
            return None
        r, g, b = rs // ws, gs // ws, bs // ws
        lum = (r * 299 + g * 587 + b * 114) // 1000
        if 0 < lum < 110:
            f = 110.0 / lum
            r, g, b = min(255, int(r * f)), min(255, int(g * f)), min(255, int(b * f))
        return rgb(r, g, b)
    except Exception as exc:
        log.info("icon_accent failed: %s", exc)
        return None
    finally:
        if ii.hbmColor:
            DeleteObject(ii.hbmColor)
        if ii.hbmMask:
            DeleteObject(ii.hbmMask)


class IconCache:
    def __init__(self):
        self.owned = []          # icons we must DestroyIcon
        self.exe_icons = {}
        self.file_icons = {}
        self.accents = {}
        self._generic = None

    def window_icon(self, hwnd, exe):
        result = c_size_t(0)
        for kind in (2, 0, 1):
            try:
                SendMessageTimeoutW(hwnd, WM_GETICON, kind, 0, 0x2, 100, byref(result))
            except Exception:
                break
            if result.value:
                return result.value
        for idx in (-34, -14):
            try:
                icon = _gclp(hwnd, idx)
            except Exception:
                icon = 0
            if icon:
                return icon
        return self.file_icon(exe, False) if exe else LoadIconW(None, 32512)

    def file_icon(self, path, large):
        """Icon of any exe / lnk / file / folder (cached). Large = 32 px."""
        if path == "::thispc":
            path = find_exe("explorer.exe")
        if path.lower().endswith(".lnk"):          # prefer the program's own icon
            icon = self.lnk_icon(path, large)
            if icon:
                return icon
        key = (path.lower(), bool(large))
        if key in self.file_icons:
            return self.file_icons[key]
        icon = 0
        try:
            sfi = SHFILEINFOW()
            if SHGetFileInfoW(path, 0, byref(sfi), sizeof(sfi),
                              0x100 | (0 if large else 1)) and sfi.hIcon:
                icon = sfi.hIcon
                self.owned.append(icon)
        except Exception as exc:
            log.info("SHGetFileInfo failed: %s", exc)
        if not icon and path.lower().endswith(".exe"):
            try:
                big, small = wt.HICON(), wt.HICON()
                if ExtractIconExW(path, 0, byref(big), byref(small), 1):
                    icon = (big.value if large else small.value) or big.value
                    for ic in (big.value, small.value):
                        if ic:
                            self.owned.append(ic)
            except Exception:
                pass
        if not icon:
            icon = LoadIconW(None, 32512)
        self.file_icons[key] = icon
        return icon

    def generic_icon(self):
        if self._generic is None:
            self._generic = LoadIconW(None, 32512)
        return self._generic

    def lnk_icon(self, path, large):
        """Icon of a shortcut: its IconLocation, else the target program."""
        info = lnk_info(path)
        if not info:
            return 0
        for loc, idx in ((info.get("icon"), info.get("icon_index", 0)), (info.get("target"), 0)):
            if not loc:
                continue
            loc = os.path.expandvars(loc)
            if not os.path.exists(loc):
                continue
            try:
                big, small = wt.HICON(), wt.HICON()
                if ExtractIconExW(loc, idx, byref(big), byref(small), 1):
                    icon = (big.value if large else small.value) or big.value or small.value
                    for ic in (big.value, small.value):
                        if ic:
                            self.owned.append(ic)
                    if icon:
                        return icon
            except Exception:
                pass
            if loc.lower().endswith(".exe"):
                got = self.file_icon(loc, large)
                if got and got != self.generic_icon():
                    return got
        return 0

    def type_icon(self, name, is_dir, large=False):
        """Shell icon for a file type / folder without touching the file (fast)."""
        ext = "<dir>" if is_dir else os.path.splitext(name)[1].lower()
        key = ("type", ext, bool(large))
        if key in self.file_icons:
            return self.file_icons[key]
        icon = 0
        try:
            sfi = SHFILEINFOW()
            fake = "folder" if is_dir else "file" + (ext or "")
            attrs = 0x10 if is_dir else 0x80
            if SHGetFileInfoW(fake, attrs, byref(sfi), sizeof(sfi),
                              0x100 | 0x10 | (0 if large else 1)) and sfi.hIcon:
                icon = sfi.hIcon
                self.owned.append(icon)
        except Exception as exc:
            log.info("type_icon failed: %s", exc)
        self.file_icons[key] = icon or LoadIconW(None, 32512)
        return self.file_icons[key]

    def accent(self, hicon, default):
        if not hicon:
            return default
        if hicon not in self.accents:
            if len(self.accents) > 500:
                self.accents.clear()
            self.accents[hicon] = icon_accent(hicon)
        return self.accents[hicon] or default

    def close(self):
        for icon in self.owned:
            DestroyIcon(icon)
        self.owned = []
        self.file_icons.clear()


ICONS = IconCache()


# ==========================================================================
# Window base class (one global WndProc dispatching to Python objects)
# ==========================================================================
# ==========================================================================
# UI themes, vector icons (GDI+), owner-drawn menus, shortcut icon resolving
# ==========================================================================
UI_THEMES = {   # name: (dark, bar bg, panel bg, text, accent)
    "dark": (True, (23, 23, 23), (31, 31, 31), (255, 255, 255), "#0078D7"),
    "light": (False, (240, 240, 240), (243, 243, 243), (0, 0, 0), "#0078D7"),
    "midnight": (True, (10, 16, 32), (16, 24, 44), (230, 236, 255), "#4C8DFF"),
    "amoled": (True, (0, 0, 0), (8, 8, 8), (240, 240, 240), "#00C8FF"),
    "nord": (True, (46, 52, 64), (59, 66, 82), (216, 222, 233), "#88C0D0"),
    "solarized_dark": (True, (0, 43, 54), (7, 54, 66), (147, 161, 161), "#268BD2"),
    "solarized_light": (False, (238, 232, 213), (253, 246, 227), (88, 110, 117), "#268BD2"),
    "forest": (True, (22, 36, 28), (28, 46, 36), (220, 235, 222), "#4CAF50"),
    "rose": (True, (44, 24, 32), (56, 30, 40), (250, 225, 232), "#F06292"),
    "sepia": (False, (233, 223, 200), (244, 236, 216), (60, 45, 30), "#A0522D"),
    "high_contrast": (True, (0, 0, 0), (0, 0, 0), (255, 255, 255), "#FFFF00"),
}
BLUR_KEYS = ("glass_blur_bar", "glass_blur_start", "glass_blur_title", "glass_blur_window")
TILE_PALETTE = ["#0078D7", "#8E24AA", "#E65100", "#00897B", "#C62828", "#2E7D32", "#5C6BC0",
                "#AD1457", "#00838F", "#EF6C00", "#6D4C41", "#455A64", "#7CB342", "#D81B60",
                "#3949AB", "#F9A825"]
CURRENT = {"app": None}


def ui_palette(name, accent_cfg):
    dark, bg, panel, text, acc = UI_THEMES.get(name, UI_THEMES["dark"])
    bgc, pc, tc = rgb(*bg), rgb(*panel), rgb(*text)
    accent = hex_color(accent_cfg, 0)
    if str(accent_cfg).upper() == DEFAULTS["accent"].upper():
        accent = hex_color(acc, 0)
    return {"dark": dark, "bg": bgc, "start_bg": pc, "win_bg": pc,
            "rail": mix(pc, rgb(0, 0, 0), 0.25 if dark else 0.06),
            "input": mix(pc, tc, 0.10), "hover": mix(pc, tc, 0.13), "active": mix(pc, tc, 0.26),
            "text": tc, "dim": mix(tc, pc, 0.45), "accent": accent, "line": mix(pc, tc, 0.2),
            "sel": mix(pc, accent, 0.45), "rib": mix(pc, tc, 0.05), "flash": rgb(214, 120, 0)}


def browse_folder(owner, title):
    bi = BROWSEINFOW()
    buf = create_unicode_buffer(1024)
    bi.hwndOwner, bi.lpszTitle, bi.ulFlags = owner, title, 0x41
    bi.pszDisplayName = ctypes.cast(buf, wt.LPWSTR)
    pidl = SHBrowseForFolderW(byref(bi))
    if pidl:
        out = create_unicode_buffer(1024)
        if SHGetPathFromIDListW(pidl, out):
            return out.value
    return ""


# ---- GDI+ anti-aliased drawing
class PointF(Structure):
    _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float)]


_GP = {}
F = ctypes.c_float
_SIG = {
    "GdipDrawLine": [c_void_p, c_void_p, F, F, F, F],
    "GdipDrawEllipse": [c_void_p, c_void_p, F, F, F, F],
    "GdipDrawArc": [c_void_p, c_void_p, F, F, F, F, F, F],
    "GdipDrawRectangle": [c_void_p, c_void_p, F, F, F, F],
    "GdipDrawLines": [c_void_p, c_void_p, POINTER(PointF), c_int],
    "GdipDrawPolygon": [c_void_p, c_void_p, POINTER(PointF), c_int],
    "GdipFillEllipse": [c_void_p, c_void_p, F, F, F, F],
    "GdipFillRectangle": [c_void_p, c_void_p, F, F, F, F],
    "GdipFillPolygon": [c_void_p, c_void_p, POINTER(PointF), c_int, c_int],
    "GdipCreateFromHDC": [wt.HDC, POINTER(c_void_p)],
    "GdipSetSmoothingMode": [c_void_p, c_int],
    "GdipDeleteGraphics": [c_void_p],
    "GdipCreatePen1": [wt.UINT, F, c_int, POINTER(c_void_p)],
    "GdipDeletePen": [c_void_p],
    "GdipSetPenStartCap": [c_void_p, c_int],
    "GdipSetPenEndCap": [c_void_p, c_int],
    "GdipSetPenLineJoin": [c_void_p, c_int],
    "GdipCreateSolidFill": [wt.UINT, POINTER(c_void_p)],
    "GdipDeleteBrush": [c_void_p],
}


def gcall(name, *args):
    fn = _GP.get(name)
    if fn is None:
        fn = _gdip["lib"][name]
        fn.argtypes = _SIG[name]
        _GP[name] = fn
    return fn(*args)


def argb(color, alpha=255):
    r, g, b = split_rgb(color)
    return (alpha << 24) | (r << 16) | (g << 8) | b


class Gfx:
    """Anti-aliased vector drawing on a DC; silently disabled if GDI+ is missing."""

    def __init__(self, hdc):
        self.ok, self.g, self.pen, self.brush = False, c_void_p(), None, None
        if gdip_start():
            try:
                if gcall("GdipCreateFromHDC", hdc, byref(self.g)) == 0:
                    gcall("GdipSetSmoothingMode", self.g, 4)
                    self.ok = True
            except Exception as exc:
                log.info("gdi+ graphics failed: %s", exc)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def close(self):
        try:
            if self.pen:
                gcall("GdipDeletePen", self.pen)
            if self.brush:
                gcall("GdipDeleteBrush", self.brush)
            if self.ok:
                gcall("GdipDeleteGraphics", self.g)
        except Exception:
            pass
        self.pen = self.brush = None
        self.ok = False

    def stroke(self, color, width=1.5, alpha=255):
        if not self.ok:
            return
        if self.pen:
            gcall("GdipDeletePen", self.pen)
        pen = c_void_p()
        gcall("GdipCreatePen1", argb(color, alpha), float(width), 2, byref(pen))
        gcall("GdipSetPenStartCap", pen, 2)
        gcall("GdipSetPenEndCap", pen, 2)
        gcall("GdipSetPenLineJoin", pen, 2)
        self.pen = pen

    def fillc(self, color, alpha=255):
        if not self.ok:
            return
        if self.brush:
            gcall("GdipDeleteBrush", self.brush)
        br = c_void_p()
        gcall("GdipCreateSolidFill", argb(color, alpha), byref(br))
        self.brush = br

    @staticmethod
    def pts(points):
        return (PointF * len(points))(*[PointF(x, y) for x, y in points])

    def line(self, a, b, c, d):
        gcall("GdipDrawLine", self.g, self.pen, a, b, c, d)

    def ellipse(self, x, y, w, h):
        gcall("GdipDrawEllipse", self.g, self.pen, x, y, w, h)

    def arc(self, x, y, w, h, a0, sw):
        gcall("GdipDrawArc", self.g, self.pen, x, y, w, h, a0, sw)

    def rect(self, x, y, w, h):
        gcall("GdipDrawRectangle", self.g, self.pen, x, y, w, h)

    def poly(self, points, closed=True):
        arr = self.pts(points)
        gcall("GdipDrawPolygon" if closed else "GdipDrawLines", self.g, self.pen, arr, len(points))

    def fill_ellipse(self, x, y, w, h):
        gcall("GdipFillEllipse", self.g, self.brush, x, y, w, h)

    def fill_rect(self, x, y, w, h):
        gcall("GdipFillRectangle", self.g, self.brush, x, y, w, h)

    def fill_poly(self, points):
        gcall("GdipFillPolygon", self.g, self.brush, self.pts(points), len(points), 0)


def _star_pts(cx, cy, ro, ri):
    out = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        r = ro if i % 2 == 0 else ri
        out.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return out


def draw_glyph(hdc, name, rect, color, size=None, width=None):
    """Windows 10 style line icon on a 24x24 grid, anti-aliased through GDI+."""
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    s = size or max(10, int(min(w, h) * 0.62))
    u = s / 24.0
    ox = (rect[0] + rect[2]) / 2.0 - 12 * u
    oy = (rect[1] + rect[3]) / 2.0 - 12 * u
    with Gfx(hdc) as g:
        if not g.ok:
            cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
            fill(hdc, (cx - 3, cy - 3, cx + 3, cy + 3), color)
            return
        g.stroke(color, width or max(1.25, 1.55 * u))
        g.fillc(color)

        def X(px, py):
            return (ox + px * u, oy + py * u)

        def L(a, b, c, d):
            g.line(*(X(a, b) + X(c, d)))

        def E(x, y, ww, hh):
            g.ellipse(ox + x * u, oy + y * u, ww * u, hh * u)

        def R(x, y, ww, hh):
            g.rect(ox + x * u, oy + y * u, ww * u, hh * u)

        def FE(x, y, ww, hh):
            g.fill_ellipse(ox + x * u, oy + y * u, ww * u, hh * u)

        def FR(x, y, ww, hh):
            g.fill_rect(ox + x * u, oy + y * u, ww * u, hh * u)

        def PL(points):
            g.poly([X(*p) for p in points], False)

        def PG(points):
            g.poly([X(*p) for p in points], True)

        def FP(points):
            g.fill_poly([X(*p) for p in points])

        n = name
        if n == "start":
            for px, py in ((3, 3), (13, 3), (3, 13), (13, 13)):
                FR(px, py, 8, 8)
        elif n == "power":
            g.arc(ox + 5 * u, oy + 5 * u, 14 * u, 14 * u, -60, 300)
            L(12, 3, 12, 12)
        elif n == "settings":
            E(5.5, 5.5, 13, 13)
            E(9, 9, 6, 6)
            for i in range(8):
                a = i * math.pi / 4
                L(12 + 6.5 * math.cos(a), 12 + 6.5 * math.sin(a),
                  12 + 9.5 * math.cos(a), 12 + 9.5 * math.sin(a))
        elif n == "docs":
            PG([(6, 3), (14, 3), (18, 7), (18, 21), (6, 21)])
            PL([(14, 3), (14, 7), (18, 7)])
            L(9, 12, 15, 12)
            L(9, 15, 15, 15)
            L(9, 18, 13, 18)
        elif n in ("pictures", "image"):
            R(3, 5, 18, 14)
            E(7, 8.5, 3, 3)
            PL([(3, 17), (9, 12), (13, 16), (16, 13), (21, 17)])
        elif n == "search":
            E(4, 4, 11, 11)
            L(13, 13, 20, 20)
        elif n == "plus":
            L(12, 5, 12, 19)
            L(5, 12, 19, 12)
        elif n == "minus":
            L(5, 12, 19, 12)
        elif n == "user":
            E(8.5, 4, 7, 7)
            g.arc(ox + 4 * u, oy + 13 * u, 16 * u, 14 * u, 180, 180)
        elif n in ("folder", "folder_plus"):
            PG([(3, 6), (10, 6), (12, 8), (21, 8), (21, 19), (3, 19)])
            if n == "folder_plus":
                L(12, 11, 12, 17)
                L(9, 14, 15, 14)
        elif n == "copy":
            R(4, 4, 11, 11)
            R(9, 9, 11, 11)
        elif n == "cut":
            E(4, 15, 5, 5)
            E(15, 15, 5, 5)
            L(7, 15, 15, 4)
            L(17, 15, 9, 4)
        elif n == "paste":
            R(5, 5, 14, 16)
            R(9, 3, 6, 4)
            L(9, 11, 15, 11)
            L(9, 14, 15, 14)
        elif n == "trash":
            L(4, 7, 20, 7)
            PL([(9, 7), (9, 4), (15, 4), (15, 7)])
            PG([(6, 7), (7, 20), (17, 20), (18, 7)])
            L(10, 10, 10, 17)
            L(14, 10, 14, 17)
        elif n == "rename":
            PG([(4, 20), (5, 15), (16, 4), (20, 8), (9, 19)])
            L(13, 7, 17, 11)
        elif n == "cmd":
            R(3, 5, 18, 14)
            PL([(7, 10), (11, 13), (7, 16)])
            L(13, 16, 17, 16)
        elif n in ("star", "star_fill"):
            pts = _star_pts(12, 12.5, 10, 4.3)
            if n == "star_fill":
                FP(pts)
            PG(pts)
        elif n in ("grid", "apps"):
            for px, py in ((4, 4), (14, 4), (4, 14), (14, 14)):
                R(px, py, 6, 6)
        elif n in ("list", "details"):
            L(8, 7, 20, 7)
            L(8, 12, 20, 12)
            L(8, 17, 20, 17)
            for py in (6, 11, 16):
                FE(3.5, py, 2, 2)
        elif n == "back":
            L(19, 12, 5, 12)
            PL([(11, 6), (5, 12), (11, 18)])
        elif n == "fwd":
            L(5, 12, 19, 12)
            PL([(13, 6), (19, 12), (13, 18)])
        elif n == "up":
            L(12, 19, 12, 5)
            PL([(6, 11), (12, 5), (18, 11)])
        elif n == "down":
            L(12, 5, 12, 19)
            PL([(6, 13), (12, 19), (18, 13)])
        elif n == "refresh":
            g.arc(ox + 5 * u, oy + 5 * u, 14 * u, 14 * u, 20, 270)
            PL([(13, 2.5), (14.4, 5.4), (17.6, 4.4)])
        elif n == "home":
            PG([(3, 12), (12, 4), (21, 12)])
            PL([(6, 11), (6, 20), (18, 20), (18, 11)])
        elif n == "menu":
            L(4, 7, 20, 7)
            L(4, 12, 20, 12)
            L(4, 17, 20, 17)
        elif n == "chev_left":
            PL([(15, 5), (8, 12), (15, 19)])
        elif n == "chev_right":
            PL([(9, 5), (16, 12), (9, 19)])
        elif n == "eye":
            E(3, 7, 18, 10)
            E(9.5, 9.5, 5, 5)
        elif n == "info":
            E(3, 3, 18, 18)
            L(12, 11, 12, 17)
            FE(11, 6.5, 2, 2)
        elif n in ("open", "open_with"):
            PL([(14, 4), (20, 4), (20, 10)])
            L(20, 4, 11, 13)
            PL([(17, 14), (17, 19), (5, 19), (5, 7), (10, 7)])
        elif n == "close":
            L(6, 6, 18, 18)
            L(18, 6, 6, 18)
        elif n == "min":
            L(5, 12, 19, 12)
        elif n == "max":
            R(5, 5, 14, 14)
        elif n == "restore":
            R(5, 8, 11, 11)
            PL([(8, 8), (8, 5), (19, 5), (19, 16), (16, 16)])
        elif n in ("snap_left", "snap_right"):
            R(3, 5, 18, 14)
            FR(3, 5, 9, 14) if n == "snap_left" else FR(12, 5, 9, 14)
        elif n == "shade":
            R(4, 5, 16, 4)
            PL([(8, 13), (12, 17), (16, 13)])
        elif n == "unshade":
            R(4, 5, 16, 4)
            PL([(8, 17), (12, 13), (16, 17)])
        elif n == "pin":
            PG([(9, 4), (15, 4), (14, 12), (16, 14), (8, 14), (10, 12)])
            L(12, 14, 12, 21)
        elif n == "check":
            PL([(5, 12), (10, 17), (19, 7)])
        elif n == "palette":
            E(3, 4, 18, 16)
            FE(7, 9, 3, 3)
            FE(12, 7, 3, 3)
            FE(16, 11, 3, 3)
        elif n == "window":
            R(3, 5, 18, 14)
            L(3, 9, 21, 9)
        elif n == "taskbar":
            R(3, 5, 18, 14)
            FR(3, 15, 18, 4)
        elif n == "monitor":
            R(3, 4, 18, 12)
            L(9, 20, 15, 20)
            L(12, 16, 12, 20)
        elif n == "play":
            PG([(8, 5), (8, 19), (19, 12)])
        elif n == "taskview":
            R(3, 5, 12, 11)
            R(9, 9, 12, 11)
        elif n == "sort":
            L(8, 5, 8, 19)
            PL([(5, 8), (8, 5), (11, 8)])
            L(16, 5, 16, 19)
            PL([(13, 16), (16, 19), (19, 16)])
        elif n == "clock":
            E(3, 3, 18, 18)
            PL([(12, 7), (12, 12), (16, 14)])
        elif n == "bookmark":
            PG([(6, 3), (18, 3), (18, 21), (12, 16), (6, 21)])
        else:
            E(8, 8, 8, 8)


# ---- Windows 10 style file type icons (our own artwork)
FILE_CATS = {
    "video": "mp4 mkv avi mov wmv flv webm m4v mpg mpeg 3gp ts",
    "audio": "mp3 wav flac aac ogg m4a wma opus mid",
    "image": "jpg jpeg png gif bmp webp tif tiff svg heic jfif",
    "archive": "zip rar 7z tar gz bz2 xz iso cab tgz wcp",
    "doc": "doc docx pdf rtf odt xls xlsx ppt pptx csv",
    "text": "txt md log ini cfg conf",
    "code": "py js c cpp h java html htm css json xml bat cmd sh reg lua cs php",
}
_EXT_CAT = {e: c for c, exts in FILE_CATS.items() for e in exts.split()}


def file_category(name):
    return _EXT_CAT.get(os.path.splitext(name)[1].lower().lstrip("."), "file")


def draw_file_icon(hdc, cat, x, y, size):
    u = size / 24.0
    with Gfx(hdc) as g:
        if not g.ok:
            fill(hdc, (x + 3, y + 2, x + size - 3, y + size - 2), rgb(225, 225, 230))
            return

        def X(px, py):
            return (x + px * u, y + py * u)

        def PGf(pts, col, edge=None, sw=1.0):
            g.fillc(col)
            g.fill_poly([X(*p) for p in pts])
            if edge:
                g.stroke(edge, max(1.0, sw * u))
                g.poly([X(*p) for p in pts], True)

        if cat == "folder":
            PGf([(2, 5), (10, 5), (12, 7), (22, 7), (22, 20), (2, 20)], rgb(240, 180, 20),
                rgb(206, 150, 10))
            PGf([(2, 10), (22, 10), (22, 20), (2, 20)], rgb(255, 214, 80), rgb(224, 170, 20))
            return
        if cat == "drive":
            PGf([(2, 8), (22, 8), (22, 18), (2, 18)], rgb(205, 208, 214), rgb(120, 124, 134))
            PGf([(17, 15), (20, 15), (20, 16.5), (17, 16.5)], rgb(60, 190, 80))
            return
        PGf([(5, 2), (15, 2), (20, 7), (20, 22), (5, 22)], rgb(252, 252, 252), rgb(140, 140, 152))
        PGf([(15, 2), (15, 7), (20, 7)], rgb(222, 224, 232), rgb(140, 140, 152))
        if cat == "video":
            PGf([(7, 11), (18, 11), (18, 19), (7, 19)], rgb(122, 62, 170))
            PGf([(11, 12.5), (11, 17.5), (15, 15)], rgb(255, 255, 255))
        elif cat == "image":
            PGf([(7, 11), (18, 11), (18, 19), (7, 19)], rgb(90, 175, 232))
            PGf([(7, 19), (10, 15), (12, 17), (14, 14), (18, 19)], rgb(70, 160, 90))
            g.fillc(rgb(255, 214, 60))
            g.fill_ellipse(*(X(14, 12) + (2.5 * u, 2.5 * u)))
        elif cat == "audio":
            g.fillc(rgb(230, 120, 40))
            g.fill_ellipse(*(X(8, 16) + (4.5 * u, 3.5 * u)))
            g.stroke(rgb(230, 120, 40), max(1.2, 1.4 * u))
            g.line(*(X(12.3, 17.5) + X(12.3, 9)))
            g.line(*(X(12.3, 9) + X(16.5, 11)))
        elif cat == "archive":
            PGf([(7, 10), (18, 10), (18, 20), (7, 20)], rgb(214, 164, 44))
            g.stroke(rgb(255, 255, 255), max(1.0, 1.2 * u))
            for yy in (11, 13.5, 16, 18.5):
                g.line(*(X(12.5, yy) + X(12.5, yy + 1.2)))
        elif cat in ("doc", "text"):
            g.stroke(rgb(60, 110, 200) if cat == "doc" else rgb(130, 130, 140), max(1.0, 1.3 * u))
            for yy, xe in ((11, 17), (14, 17), (17, 14)):
                g.line(*(X(8, yy) + X(xe, yy)))
        elif cat == "code":
            g.stroke(rgb(60, 160, 90), max(1.1, 1.4 * u))
            g.poly([X(11, 11), X(8, 14.5), X(11, 18)], False)
            g.poly([X(14, 11), X(17, 14.5), X(14, 18)], False)


LETTER_COLORS = [(0, 120, 215), (232, 17, 35), (16, 124, 16), (136, 23, 152), (255, 140, 0),
                 (0, 153, 188), (194, 57, 179), (0, 99, 177)]


def draw_letter_tile(hdc, x, y, size, name):
    name = name or "?"
    ch = (name.strip()[:1] or "?").upper()
    col = rgb(*LETTER_COLORS[sum(map(ord, name)) % len(LETTER_COLORS)])
    fill(hdc, (x, y, x + size, y + size), col)
    text_out(hdc, ch, (x, y, x + size, y + size), DT_CENTER | DT_VCENTER | DT_SINGLELINE,
             rgb(255, 255, 255))


def draw_icon_or_letter(hdc, icon, x, y, size, name):
    """Real icon if we have one, otherwise a coloured letter tile (never blank)."""
    if icon and icon != ICONS.generic_icon():
        DrawIconEx(hdc, x, y, icon, size, size, 0, None, 3)
    else:
        draw_letter_tile(hdc, x, y, size, name)


# ---- full .lnk parsing (target, icon location, icon index)
def lnk_info(path):
    try:
        with open(path, "rb") as f:
            data = f.read(65536)
        if len(data) < 76 or struct.unpack_from("<I", data, 0)[0] != 0x4C:
            return None
        flags = struct.unpack_from("<I", data, 0x14)[0]
        info = {"icon_index": struct.unpack_from("<i", data, 0x38)[0]}
        pos = 76
        if flags & 1:
            pos += 2 + struct.unpack_from("<H", data, pos)[0]
        if flags & 2:
            base = pos
            size, hdr, lf, _vol, local_off, _net, suffix_off = struct.unpack_from("<7I", data, base)

            def cstr(off):
                end = data.index(b"\0", base + off)
                raw = data[base + off:end]
                try:
                    return raw.decode("mbcs")
                except Exception:
                    return raw.decode("latin-1")

            if lf & 1:
                info["target"] = cstr(local_off) + (cstr(suffix_off) if suffix_off else "")
            pos = base + size
        uni = bool(flags & 0x80)

        def read_str():
            nonlocal pos
            n = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            if uni:
                s = data[pos:pos + 2 * n].decode("utf-16le", "replace")
                pos += 2 * n
            else:
                s = data[pos:pos + n].decode("latin-1")
                pos += n
            return s

        for bit, key in ((4, "name"), (8, "relative"), (0x10, "workdir"), (0x20, "args"),
                         (0x40, "icon")):
            if flags & bit:
                info[key] = read_str()
        if "target" not in info and info.get("relative"):
            info["target"] = os.path.normpath(os.path.join(os.path.dirname(path), info["relative"]))
        return info
    except Exception:
        return None


def lnk_target(path):
    return (lnk_info(path) or {}).get("target")


# ---- owner-drawn popup menus (themed, with icons)
MENU = {"items": {}, "brush": None}
MENU_ICONS = [("open with", "open_with"), ("open command", "cmd"), ("command window", "cmd"),
              ("file location", "folder"), ("new window", "window"), ("open", "open"),
              ("copy", "copy"), ("cut", "cut"), ("paste", "paste"), ("new folder", "folder_plus"),
              ("delete", "trash"), ("remove", "trash"), ("rename", "rename"),
              ("refresh", "refresh"), ("favorite", "star"), ("starred", "star"),
              ("unpin", "pin"), ("pin", "pin"), ("close", "close"), ("minimize", "min"),
              ("maximize", "max"), ("restore", "restore"), ("settings", "settings"),
              ("personalize", "palette"), ("wallpaper", "pictures"), ("picture", "pictures"),
              ("show desktop", "monitor"), ("exit", "power"), ("restart", "refresh"),
              ("shut", "power"), ("end task", "close"), ("always on top", "pin"),
              ("size", "grid"), ("grid", "grid"), ("details", "list"), ("hidden", "eye"),
              ("add", "plus"), ("change", "user"), ("reload", "refresh"), ("edit", "rename"),
              ("sort", "sort"), ("go to", "open")]


def menu_icon_for(label):
    low = label.lower()
    for key, icon in MENU_ICONS:
        if key in low:
            return icon
    return ""


def on_menu_measure(lp):
    app = CURRENT["app"]
    mi = ctypes.cast(lp, POINTER(MEASUREITEMSTRUCT)).contents
    d = MENU["items"].get(mi.itemData)
    if not d or not app:
        return False
    p = app.px
    if d.get("sep"):
        mi.itemWidth, mi.itemHeight = p(60), p(9)
        return True
    hdc = GetDC(None)
    old = SelectObject(hdc, app.font)
    sz = wt.SIZE()
    GetTextExtentPoint32W(hdc, d["label"], len(d["label"]), byref(sz))
    SelectObject(hdc, old)
    ReleaseDC(None, hdc)
    mi.itemWidth, mi.itemHeight = sz.cx + p(76), p(30)
    return True


def on_menu_draw(lp):
    app = CURRENT["app"]
    di = ctypes.cast(lp, POINTER(DRAWITEMSTRUCT)).contents
    d = MENU["items"].get(di.itemData)
    if not d or not app:
        return False
    th, p, hdc = app.theme(), app.px, di.hDC
    rc = di.rcItem
    box = (rc.left, rc.top, rc.right, rc.bottom)
    gray, sel = bool(di.itemState & 2), bool(di.itemState & 1) and not (di.itemState & 2)
    fill(hdc, box, th["hover"] if sel else th["start_bg"])
    if d.get("sep"):
        fill(hdc, (box[0] + p(10), (box[1] + box[3]) // 2, box[2] - p(10), (box[1] + box[3]) // 2 + 1),
             th["line"])
        return True
    col = th["dim"] if gray else th["text"]
    icon = d.get("icon") or menu_icon_for(d["label"])
    if icon:
        draw_glyph(hdc, icon, (box[0] + p(6), box[1], box[0] + p(32), box[3]), col, size=p(16))
    if di.itemState & 8:
        draw_glyph(hdc, "check", (box[0] + p(6), box[1], box[0] + p(32), box[3]), th["accent"],
                   size=p(16))
    old = SelectObject(hdc, app.font)
    SetBkMode(hdc, 1)
    text_out(hdc, d["label"], (box[0] + p(40), box[1], box[2] - p(26), box[3]),
             DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX, col)
    SelectObject(hdc, old)
    if d.get("sub"):
        draw_glyph(hdc, "chev_right", (box[2] - p(26), box[1], box[2] - p(6), box[3]), col, size=p(12))
    return True


WINDOWS = {}


def _global_proc(hwnd, msg, wp, lp):
    if msg in (0x2B, 0x2C) and lp:                    # owner-drawn popup menus
        try:
            if c_uint.from_address(lp).value == 1:       # ODT_MENU
                if msg == 0x2C and on_menu_measure(lp):
                    return 1
                if msg == 0x2B and on_menu_draw(lp):
                    return 1
        except Exception:
            log.exception("menu draw failed")
    obj = WINDOWS.get(hwnd)
    if obj is None:
        obj = Window.creating
        if obj is not None and hwnd:
            WINDOWS[hwnd] = obj
            obj.hwnd = hwnd
    if obj is None:
        return DefWindowProcW(hwnd, msg, wp, lp)
    try:
        result = obj.on_message(hwnd, msg, wp, lp)
        return 0 if result is None else result
    except Exception:
        log.exception("window procedure error (msg 0x%X)", msg)
        return DefWindowProcW(hwnd, msg, wp, lp)


GLOBAL_PROC = WNDPROC(_global_proc)


class Window:
    creating = None
    classes = set()

    def __init__(self):
        self.hwnd = None

    @staticmethod
    def register(name, style=0, brush=None, icon=None):
        if name in Window.classes:
            return
        wc = WNDCLASSW()
        wc.style = style
        wc.lpfnWndProc = GLOBAL_PROC
        wc.hInstance = GetModuleHandleW(None)
        wc.hCursor = LoadCursorW(None, 32512)
        wc.hbrBackground = brush
        wc.hIcon = icon
        wc.lpszClassName = name
        if not RegisterClassW(byref(wc)):
            log.warning("RegisterClassW(%s) failed: %s", name, ctypes.get_last_error())
        Window.classes.add(name)

    def create_window(self, cls, title, style, ex, x, y, w, h):
        Window.creating = self
        try:
            hwnd = CreateWindowExW(ex, cls, title, style, x, y, w, h, None, None,
                                   GetModuleHandleW(None), None)
        finally:
            Window.creating = None
        if not hwnd:
            raise RuntimeError("CreateWindowExW(%s) failed: %s" % (cls, ctypes.get_last_error()))
        WINDOWS[hwnd] = self
        self.hwnd = hwnd
        return hwnd

    def on_message(self, hwnd, msg, wp, lp):
        return DefWindowProcW(hwnd, msg, wp, lp)

    def invalidate(self):
        if self.hwnd:
            InvalidateRect(self.hwnd, None, False)


def xy(lp):
    return c_short(lp & 0xFFFF).value, c_short((lp >> 16) & 0xFFFF).value


def inside(rect, x, y):
    return rect[0] <= x < rect[2] and rect[1] <= y < rect[3]


# ==========================================================================
# Taskbar
# ==========================================================================
class Entry:
    """One taskbar button: a pinned app and/or a running app (windows grouped)."""

    def __init__(self, key, path):
        self.key = key
        self.path = path
        self.pinned = False
        self.tasks = []
        self.hicon = 0
        self.accent = None
        self.icon_time = 0.0
        self.title = ""


class Taskbar(Window):
    CLASS = "WinShellBar"

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.entries = []
        self.win_exe = {}
        self.hover = None
        self.tracking = False
        self.flashing = set()
        self.hidden_by_desktop = []
        self.orig_work = None
        self.press = None
        self.drag = None
        self.drag_dx = 0
        self.drag_x = 0
        self.clock_text = ""
        self.last_fg = None
        self.tick = 0
        self.bar_hidden = False
        self.div_rect = None
        self.close_rect = (0, 0, 0, 0)
        self.peek_until = 0.0
        self.work_full = False
        self.hover_entry = None
        self.hv_start = 0.0
        self.shellhook_msg = RegisterWindowMessageW("SHELLHOOK")

    # ---- setup
    def create(self):
        Window.register(self.CLASS)
        x, y, w, h = self.app.bar_rect()
        self.create_window(self.CLASS, "WinShell Taskbar", WS_POPUP | WS_VISIBLE,
                           WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                           x, y, w, h)
        SetTimer(self.hwnd, 1, 1000, None)
        SetTimer(self.hwnd, 3, 80, None)      # keep the bar in front of windows
        SetTimer(self.hwnd, 4, 150, None)     # hover previews
        if not RegisterShellHookWindow(self.hwnd):
            log.info("shell hook unavailable, timer only")
        self.apply()

    def apply(self):
        if not self.hwnd:
            return
        a, c = self.app, self.app.cfg
        x, y, w, h = a.bar_rect()
        SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE)
        self.apply_work_area(h)
        apply_glass(self.hwnd, c["glass"], c["glass_opacity"])
        wine_bar = FindWindowW("Shell_TrayWnd", None)
        if wine_bar:
            ShowWindow(wine_bar, 0 if c["hide_wine_taskbar"] else 5)
        self.rebuild_pins()
        self.refresh(force=True)
        if c["custom_titlebar"]:
            SetTimer(self.hwnd, 2, 100, None)            # follow app windows
        else:
            KillTimer(self.hwnd, 2)
            a.clear_titlebars()
        if a.float.visible:
            a.float.show()
        self.invalidate()

    def apply_work_area(self, bar_h):
        self.work_full = False
        if self.orig_work is None:
            rc = RECT()
            SystemParametersInfoW(SPI_GETWORKAREA, 0, byref(rc), 0)
            self.orig_work = rc
        if not self.app.cfg["reserve_work_area"]:
            self.restore_work_area()
            return
        rc = RECT(*self.app.work_rect())
        SystemParametersInfoW(SPI_SETWORKAREA, 0, byref(rc), SPIF_SENDCHANGE)

    def restore_work_area(self):
        if self.orig_work is not None:
            SystemParametersInfoW(SPI_SETWORKAREA, 0, byref(self.orig_work),
                                  SPIF_SENDCHANGE)

    # ---- entries
    def rebuild_pins(self):
        old = {e.key: e for e in self.entries}
        new = []
        for p in self.app.cfg["pinned"]:
            path = find_exe(p) if not os.path.isabs(p) else p
            key = app_key(exe_for(path))
            e = old.pop(key, None) or Entry(key, path)
            e.pinned, e.path = True, path
            new.append(e)
        for e in self.entries:
            if e.key in old and (e.tasks):
                e.pinned = False
                new.append(e)
        self.entries = new

    def is_task_window(self, hwnd):
        if hwnd == self.hwnd or not IsWindowVisible(hwnd):
            return False
        ex = GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
        if (ex & WS_EX_TOOLWINDOW) and not (ex & WS_EX_APPWINDOW):
            return False
        if GetWindow(hwnd, GW_OWNER) and not (ex & WS_EX_APPWINDOW):
            return False
        if get_class(hwnd) in IGNORED_CLASSES:
            return False
        return bool(get_title(hwnd))

    def refresh(self, force=False):
        wins = []

        def cb(hwnd, _lp):
            if hwnd and self.is_task_window(hwnd):
                wins.append(hwnd)
            return True

        callback = WNDENUMPROC(cb)
        EnumWindows(callback, 0)
        for h in list(self.win_exe):
            if h not in wins:
                del self.win_exe[h]
        groups = {}
        for h in wins:
            if h not in self.win_exe:
                self.win_exe[h] = process_path(h)
            exe = self.win_exe[h]
            key = app_key(exe) if exe else "hwnd:%d" % h
            if get_class(h) == "WinShellExplorer":       # our File Explorer = explorer.exe
                key, exe = "explorer.exe", find_exe("explorer.exe")
            groups.setdefault(key, []).append((h, exe))
        changed = False
        known = {e.key for e in self.entries}
        for e in self.entries:
            g = groups.get(e.key, [])
            tasks = [h for h, _ in g]
            if tasks != e.tasks:
                e.tasks, changed = tasks, True
            if g and g[0][1] and not e.pinned:
                e.path = g[0][1]
        for key, g in groups.items():
            if key not in known:
                e = Entry(key, g[0][1])
                e.tasks = [h for h, _ in g]
                self.entries.append(e)
                changed = True
        keep = [e for e in self.entries if e.pinned or e.tasks]
        if len(keep) != len(self.entries):
            self.entries, changed = keep, True
        now = time.time()
        for e in self.entries:
            if force or not e.hicon or now - e.icon_time > 10:
                if e.key == "explorer.exe" and self.app.cfg["use_winshell_explorer"]:
                    icon = self.app.explorer_icon()
                elif e.tasks:
                    icon = ICONS.window_icon(e.tasks[0], e.path)
                else:
                    icon = ICONS.file_icon(e.path, False)
                if icon != e.hicon:
                    e.hicon, e.accent, changed = icon, None, True
                e.icon_time = now
            title = get_title(e.tasks[0]) if e.tasks else display_name(e.path)
            if title != e.title:
                e.title, changed = title, True
        self.flashing &= set(wins)
        return changed

    def is_active_hwnd(self, h):
        fg = GetForegroundWindow()
        return bool(fg) and (fg == h or GetAncestor(fg, GA_ROOTOWNER) == h)

    def entry_active(self, e):
        return any(self.is_active_hwnd(h) for h in e.tasks)

    def primary(self, e):
        for h in e.tasks:
            if self.is_active_hwnd(h):
                return h
        return e.tasks[0] if e.tasks else None

    # ---- layout / hit test
    def layout(self, W, H):
        a, c = self.app, self.app.cfg
        start_w = int(H * 1.2)
        clock_w, desk_w, close_w = a.px(96), a.px(10), a.px(30)
        desk = (W - desk_w, 0, W, H)
        close = (desk[0] - close_w, 0, desk[0], H)
        clock = (close[0] - clock_w, 0, close[0], H)
        self.close_rect = close
        pins = [e for e in self.entries if e.pinned]
        runs = [e for e in self.entries if not e.pinned]
        bw_p = int(H * 1.15)                      # pinned apps are always icon-only
        div_w = a.px(9) if pins and runs else 0
        avail = max(0, clock[0] - start_w - bw_p * len(pins) - div_w)
        wanted = a.px(c["button_width"]) if c["show_titles"] else bw_p
        bw_u = max(a.px(28), min(wanted, avail // len(runs))) if runs else 0
        group_w = start_w + bw_p * len(pins) + div_w + bw_u * len(runs)
        if c["alignment"] == "center":
            x0 = max(0, (clock[0] - group_w) // 2)
        elif c["alignment"] == "right":
            x0 = max(0, clock[0] - group_w)
        else:
            x0 = 0
        start = (x0, 0, x0 + start_w, H)
        rects, x = [], x0 + start_w
        for e in pins:
            rects.append((e, (x, 0, x + bw_p, H)))
            x += bw_p
        self.div_rect = (x, 0, x + div_w, H) if div_w else None
        x += div_w
        for e in runs:
            rects.append((e, (x, 0, x + bw_u, H)))
            x += bw_u
        return start, rects, clock, desk

    def client(self):
        rc = RECT()
        GetClientRect(self.hwnd, byref(rc))
        return rc.right, rc.bottom

    def hit(self, x, y):
        W, Hh = self.client()
        start, rects, clock, desk = self.layout(W, Hh)
        if inside(start, x, y):
            return "start", None
        for e, r in rects:
            if inside(r, x, y):
                return "entry", e
        if inside(self.close_rect, x, y):
            return "preview", None
        if inside(desk, x, y):
            return "desk", None
        return "bar", None

    # ---- painting
    def paint(self):
        ps = PAINTSTRUCT()
        hdc = BeginPaint(self.hwnd, byref(ps))
        try:
            W, Hh = self.client()
            if W > 0 and Hh > 0:
                mem = CreateCompatibleDC(hdc)
                bmp = CreateCompatibleBitmap(hdc, W, Hh)
                old = SelectObject(mem, bmp)
                self.draw(mem, W, Hh)
                BitBlt(hdc, 0, 0, W, Hh, mem, 0, 0, SRCCOPY)
                SelectObject(mem, old)
                DeleteObject(bmp)
                DeleteDC(mem)
        finally:
            EndPaint(self.hwnd, byref(ps))

    def draw(self, hdc, W, Hh):
        a, c = self.app, self.app.cfg
        th = a.theme()
        fill(hdc, (0, 0, W, Hh), th["bg"])
        if c["glass_blur_bar"]:              # blurred wallpaper behind a tint
            bx, by = a.bar_rect()[:2]
            if a.paint_blur(hdc, W, Hh, bx, by):
                alpha_rect(hdc, (0, 0, W, Hh), th["bg"], 150)
        if c["glass"]:      # gloss: lighter top half + highlight line
            alpha_rect(hdc, (0, 0, W, Hh // 2), rgb(255, 255, 255), 14)
            alpha_rect(hdc, (0, 0, W, 1), rgb(255, 255, 255), 70)
        SetBkMode(hdc, 1)
        old_font = SelectObject(hdc, a.font)
        start, rects, clock, desk = self.layout(W, Hh)

        # Windows 10 Start button: four panes
        if self.hover == "start" or a.start.visible:
            fill(hdc, start, th["hover"])
        custom = max(8, int(Hh * 0.55))
        start_icon = a.start_icon(custom)
        if start_icon:                       # user supplied .ico / .png
            DrawIconEx(hdc, start[0] + (start[2] - start[0] - custom) // 2,
                       (Hh - custom) // 2, start_icon, custom, custom, 0, None, 3)
        else:
            pane = max(4, int(Hh * 0.2))
            gap = max(1, int(Hh * 0.03))
            total = 2 * pane + gap
            sx = start[0] + (start[2] - start[0] - total) // 2
            sy = (Hh - total) // 2
            for dx in (0, pane + gap):
                for dy in (0, pane + gap):
                    fill(hdc, (sx + dx, sy + dy, sx + dx + pane, sy + dy + pane),
                         th["accent"] if self.hover == "start" else th["text"])

        isz = a.px(c["icon_size"])
        dragged = None
        for e, r in rects:
            if e is self.drag:
                dragged = (e, r)
                continue
            self.draw_entry(hdc, e, r, isz, th, Hh)
        if dragged:
            e, r = dragged
            w = r[2] - r[0]
            r2 = (self.drag_x - self.drag_dx, r[1], self.drag_x - self.drag_dx + w, r[3])
            self.draw_entry(hdc, e, r2, isz, th, Hh, lifted=True)

        if self.div_rect:                    # divider: pinned | running
            dvx = (self.div_rect[0] + self.div_rect[2]) // 2
            fill(hdc, (dvx, int(Hh * 0.22), dvx + 1, int(Hh * 0.78)), th["active"])
        self.clock_text = a.clock_str()
        calc = RECT(*clock)
        DrawTextW(hdc, self.clock_text, -1, byref(calc), DT_CALCRECT | DT_CENTER | DT_NOPREFIX)
        top = clock[1] + max(0, (clock[3] - clock[1] - (calc.bottom - calc.top)) // 2)
        text_out(hdc, self.clock_text, (clock[0], top, clock[2], top + calc.bottom - calc.top),
                 DT_CENTER | DT_NOPREFIX, th["text"])
        cr = self.close_rect                 # window preview button
        if self.hover == "preview" or a.preview.visible:
            fill(hdc, cr, th["hover"])
        draw_glyph(hdc, "taskview", cr, th["text"], size=int(Hh * 0.5))
        if self.hover == "desk":
            fill(hdc, desk, th["hover"])
        fill(hdc, (desk[0], 4, desk[0] + 1, Hh - 4), th["active"])
        SelectObject(hdc, old_font)

    def draw_entry(self, hdc, e, r, isz, th, Hh, lifted=False):
        a, c = self.app, self.app.cfg
        active = self.entry_active(e)
        if lifted:
            fill(hdc, r, th["active"])
        elif any(h in self.flashing for h in e.tasks):
            fill(hdc, r, th["flash"])
        elif active:
            fill(hdc, r, th["active"])
        elif self.hover == id(e):
            fill(hdc, r, th["hover"])
        bw = r[2] - r[0]
        show_text = c["show_titles"] and not e.pinned and bw > isz + a.px(40)
        ix = r[0] + (a.px(10) if show_text else (bw - isz) // 2)
        iy = r[1] + (Hh - isz) // 2
        if e.hicon or e.title:
            draw_icon_or_letter(hdc, e.hicon, ix, iy, isz, e.title or display_name(e.path))
        if show_text:
            color = th["text"] if e.tasks else th["dim"]
            text_out(hdc, e.title, (ix + isz + a.px(8), r[1], r[2] - a.px(6), r[3]),
                     DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS | DT_NOPREFIX, color)
        if e.tasks:
            if e.accent is None:
                e.accent = (ICONS.accent(e.hicon, th["accent"])
                            if c["icon_accent"] else th["accent"])
            thick = a.px(3 if active else 2)
            if active:
                u0, u1 = r[0] + 2, r[2] - 2
            else:
                u0, u1 = r[0] + bw // 4, r[2] - bw // 4
            fill(hdc, (u0, r[3] - thick, u1, r[3]), e.accent)
            if len(e.tasks) > 1:      # grouped windows: second thin stripe
                fill(hdc, (u0 + 3, r[3] - thick - 3, u1 - 3, r[3] - thick - 2), e.accent)

    # ---- actions
    def toggle_window(self, h):
        if IsIconic(h):
            ShowWindow(h, 9)
            SetForegroundWindow(h)
        elif self.is_active_hwnd(h):
            ShowWindow(h, 6)
        else:
            SetForegroundWindow(h)
        self.flashing.discard(h)
        self.invalidate()

    def click_entry(self, e):
        if not e.tasks:
            self.app.run(e.path)
        elif len(e.tasks) == 1:
            self.toggle_window(e.tasks[0])
        else:
            items = [(3000 + i, (get_title(h) or "(window)").replace("&", "&&")[:60])
                     for i, h in enumerate(e.tasks)]
            cmd = self.popup(items)
            if cmd >= 3000 and cmd - 3000 < len(e.tasks):
                self.toggle_window(e.tasks[cmd - 3000])

    def popup(self, items):
        _x, y, _w, h = self.app.bar_rect()
        flags = TPM_RETURNCMD | TPM_RIGHTBUTTON
        if self.app.cfg["position"] == "bottom":
            flags |= TPM_BOTTOMALIGN
        else:
            y += h
        return self.app.popup(self.hwnd, items, flags, None, y)

    def entry_menu(self, e):
        h = self.primary(e)
        topmost = bool(h and (GetWindowLongW(h, GWL_EXSTYLE) & WS_EX_TOPMOST))
        items = [(0, (e.title or display_name(e.path)).replace("&", "&&")[:40], MF_GRAYED),
                 None, (1, "Open new window")]
        if h:
            items += [(2, "Restore"), (3, "Minimize"), (4, "Maximize"), (5, "Close window")]
        if len(e.tasks) > 1:
            items.append((6, "Close all windows"))
        if h:
            items += [None, (7, "Always on top", MF_CHECKED if topmost else 0)]
        items += [None, (8, "Unpin from taskbar" if e.pinned else "Pin to taskbar"),
                  (9, "Open file location")]
        if h:
            items.append((10, "End task (force quit)"))
        cmd = self.popup(items)
        if cmd == 1:
            self.app.run(e.path)
        elif cmd == 2 and h:
            ShowWindow(h, 9)
            SetForegroundWindow(h)
        elif cmd == 3 and h:
            ShowWindow(h, 6)
        elif cmd == 4 and h:
            ShowWindow(h, 3)
            SetForegroundWindow(h)
        elif cmd == 5 and h:
            PostMessageW(h, WM_CLOSE, 0, 0)
        elif cmd == 6:
            for w in e.tasks:
                PostMessageW(w, WM_CLOSE, 0, 0)
        elif cmd == 7 and h:
            SetWindowPos(h, HWND_NOTOPMOST if topmost else HWND_TOPMOST, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        elif cmd == 8:
            if e.pinned:
                self.app.unpin_taskbar(e.key)
            else:
                self.app.pin_taskbar(e.path)
        elif cmd == 9:
            self.app.run("explorer.exe", '/select,"%s"' % exe_for(e.path))
        elif cmd == 10 and h:
            pid = wt.DWORD(0)
            GetWindowThreadProcessId(h, byref(pid))
            self.app.run("taskkill.exe", "/F /PID %d" % pid.value, 0)

    def bar_menu(self):
        cmd = self.popup([(1, "Show desktop"), (2, "Settings"), (3, "Edit config file"),
                          (4, "Reload settings"), None, (5, "Exit taskbar")])
        if cmd == 1:
            self.show_desktop()
        elif cmd == 2:
            self.app.open_settings()
        elif cmd == 3:
            self.app.run("notepad.exe", '"%s"' % CONFIG_PATH)
        elif cmd == 4:
            self.app.reload()
        elif cmd == 5:
            PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def show_desktop(self):
        if self.hidden_by_desktop:
            for h in self.hidden_by_desktop:
                ShowWindow(h, 9)
            self.hidden_by_desktop = []
        else:
            for e in self.entries:
                for h in e.tasks:
                    if not IsIconic(h):
                        ShowWindow(h, 7)
                        self.hidden_by_desktop.append(h)

    def close_all_windows(self):
        wins = [h for e in self.entries for h in e.tasks]
        if not wins:
            return
        msg = "Close all %d running window(s)?\nUnsaved work may be lost." % len(wins)
        if MessageBoxW(self.hwnd, msg, "WinShell", 0x4 | 0x20 | 0x40000) == 6:
            for h in wins:
                PostMessageW(h, WM_CLOSE, 0, 0)

    def ensure_front(self):
        """The bar must always stay in front of windows (also while they are dragged)."""
        if self.bar_hidden or not self.hwnd:
            return
        down = GetAsyncKeyState(0x01) & 0x8000
        fg = GetForegroundWindow()
        near = False
        if fg and fg != self.hwnd and fg not in WINDOWS:
            rc = RECT()
            if GetWindowRect(fg, byref(rc)):
                bx, by, bw, bh = self.app.bar_rect()
                near = rc.bottom > by and rc.top < by + bh and rc.right > bx and rc.left < bx + bw
        prev = GetWindow(self.hwnd, 3)
        behind = bool(prev) and not (GetWindowLongW(prev, GWL_EXSTYLE) & WS_EX_TOPMOST)
        if down or near or behind:
            self.raise_bar()

    def hover_tick(self):
        a, c = self.app, self.app.cfg
        hp = a.hover_prev
        if not c["preview_on_hover"] or self.drag or a.start.visible or self.bar_hidden:
            hp.hide()
            return
        pt = wt.POINT()
        GetCursorPos(byref(pt))
        rc = RECT()
        GetWindowRect(self.hwnd, byref(rc))
        over_bar = rc.left <= pt.x < rc.right and rc.top <= pt.y < rc.bottom
        e = self.hover_entry if over_bar else None
        if hp.visible:
            if hp.contains(pt.x, pt.y) or e is hp.entry:
                return
            if e is not None and e.tasks:
                hp.show(e)
            elif not over_bar:
                hp.hide()
            return
        if e is not None and e.tasks and time.time() - self.hv_start >= \
                max(0, int(c["preview_hover_delay"])) / 1000.0:
            hp.show(e)

    # ---- drag to reorder
    def reorder_drag(self, x):
        W, Hh = self.client()
        _s, rects, _c, _d = self.layout(W, Hh)
        e = self.drag
        grp = [(ent, r) for ent, r in rects if ent.pinned == e.pinned]   # stay in own group
        bw = next((r[2] - r[0] for ent, r in grp if ent is e), 0)
        center = x - self.drag_dx + bw // 2
        others = [ent for ent, r in grp if ent is not e]
        pos = sum(1 for ent, r in grp if ent is not e and (r[0] + r[2]) // 2 < center)
        others.insert(pos, e)
        if e.pinned:
            new = others + [t for t in self.entries if not t.pinned]
        else:
            new = [t for t in self.entries if t.pinned] + others
        if new != self.entries:
            self.entries = new

    def finish_drag(self):
        self.drag = None
        self.app.cfg["pinned"] = [e.path for e in self.entries if e.pinned]
        self.app.save()
        self.invalidate()

    # ---- full-screen / maximized policy
    def show_bar(self, on):
        if on and self.bar_hidden:
            ShowWindow(self.hwnd, 8)
            self.bar_hidden = False
        elif not on and not self.bar_hidden:
            ShowWindow(self.hwnd, 0)
            self.bar_hidden = True

    def raise_bar(self):
        SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def set_work_full(self, full):
        if full == self.work_full:
            return
        if full:
            sw, sh = screen_size()
            rc = RECT(0, 0, sw, sh)
            SystemParametersInfoW(SPI_SETWORKAREA, 0, byref(rc), SPIF_SENDCHANGE)
            self.work_full = True
        else:
            self.apply_work_area(0)          # restores the reserved bar strip

    def peek(self):
        """Floating icon clicked: show the full taskbar in front of the app for a while."""
        self.peek_until = time.time() + 5
        self.show_bar(True)
        self.raise_bar()
        self.app.float.hide()
        self.invalidate()

    def check_fullscreen(self):
        a, c = self.app, self.app.cfg
        fg = GetForegroundWindow()
        full = maxed = False
        if fg and fg != self.hwnd and fg not in WINDOWS and IsWindowVisible(fg) \
                and not IsIconic(fg) and get_class(fg) not in IGNORED_CLASSES:
            if IsZoomed(fg):
                maxed = True
            else:
                rc = RECT()
                GetWindowRect(fg, byref(rc))
                sw, sh = screen_size()
                full = rc.left <= 0 and rc.top <= 0 and rc.right >= sw and rc.bottom >= sh
        trig, mode = c["fs_trigger"], c["fs_mode"]
        covering = (full and trig in ("fullscreen", "both")) or \
                   (maxed and trig in ("maximized", "both"))
        if mode == "keep_visible":            # apps are resized to stay above the bar
            if full:
                l, t, r, b = a.work_rect()
                SetWindowPos(fg, None, l, t, r - l, b - t, SWP_NOACTIVATE | SWP_NOZORDER)
            self.show_bar(True)
            self.set_work_full(False)
            a.float.hide()
            return
        busy = (time.time() < self.peek_until or a.start.visible or a.preview.visible
                or a.menu_depth > 0)
        if not covering:
            self.show_bar(True)
            self.set_work_full(False)
            a.float.hide()
        elif mode == "bar_over_app":          # force the bar on top of the app
            self.show_bar(True)
            self.raise_bar()
            a.float.hide()
        elif mode == "floating_icon":         # bar hidden, small floating button instead
            self.set_work_full(True)
            if busy:
                self.show_bar(True)
                self.raise_bar()
                a.float.hide()
            else:
                self.show_bar(False)
                a.float.show()
        else:                                 # hide_bar
            self.set_work_full(True)
            self.show_bar(busy)
            a.float.hide()

    # ---- messages
    def on_message(self, hwnd, msg, wp, lp):
        if self.shellhook_msg and msg == self.shellhook_msg:
            event = wp & 0x7FFF
            if wp == 0x8006:
                self.flashing.add(lp)
            elif event == 4:
                self.flashing.discard(lp)
            self.refresh(force=(event == 6))
            self.invalidate()
            return 0
        if msg == WM_PAINT:
            self.paint()
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_MOUSEACTIVATE:
            return 3
        if msg == WM_TIMER:
            try:
                if wp == 2:
                    self.app.update_titlebars()
                elif wp == 3:
                    self.ensure_front()
                elif wp == 4:
                    self.hover_tick()
                else:
                    self.on_timer()
            except Exception:
                log.exception("timer %s failed", wp)
            return 0
        if msg in (WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONUP, WM_MBUTTONUP, WM_MOUSEMOVE):
            x, y = xy(lp)
            kind, obj = self.hit(x, y)
            if self.peek_until > time.time():            # keep a peeked bar open
                self.peek_until = time.time() + 4
            if msg == WM_MOUSEMOVE:
                self.on_move(x, kind, obj)
            elif msg == WM_LBUTTONDOWN:
                if kind == "entry":
                    self.press = (obj, x)
                    SetCapture(hwnd)
            elif msg == WM_LBUTTONUP:
                self.on_left_up(kind, obj)
            elif msg == WM_RBUTTONUP:
                if kind == "entry":
                    self.entry_menu(obj)
                elif kind in ("bar", "desk", "start"):
                    self.bar_menu()
            elif msg == WM_MBUTTONUP and kind == "entry" and obj.path:
                self.app.run(obj.path)
            return 0
        if msg == WM_MOUSELEAVE:
            self.tracking, self.hover = False, None
            self.invalidate()
            return 0
        if msg == 0x4A:                                  # WM_COPYDATA: open a folder here
            try:
                cds = ctypes.cast(lp, POINTER(COPYDATASTRUCT)).contents
                text = ctypes.wstring_at(cds.lpData, cds.cbData // 2).rstrip("\0")
                self.app.open_explorer(os.path.dirname(text) if cds.dwData == 2 else text,
                                       text if cds.dwData == 2 else None)
            except Exception:
                log.exception("copydata failed")
            return 1
        if msg == WM_DISPLAYCHANGE:
            self.app.apply_all()
            return 0
        if msg == WM_DESTROY:
            self.app.shutdown()
            return 0
        return DefWindowProcW(hwnd, msg, wp, lp)

    def on_move(self, x, kind, obj):
        a = self.app
        if self.press and not self.drag and abs(x - self.press[1]) > a.px(6):
            e = self.press[0]
            W, Hh = self.client()
            for ent, r in self.layout(W, Hh)[1]:
                if ent is e:
                    self.drag_dx = x - r[0]
            self.drag = e
        if self.drag:
            self.drag_x = x
            self.reorder_drag(x)
            self.invalidate()
            return
        key = id(obj) if kind == "entry" else (
            kind if kind in ("start", "desk", "preview") else None)
        if kind == "entry":
            if self.hover_entry is not obj:
                self.hover_entry, self.hv_start = obj, time.time()
        else:
            self.hover_entry = None
        if not self.tracking:
            TrackMouseEvent(byref(TRACKMOUSEEVENT(sizeof(TRACKMOUSEEVENT), 2, self.hwnd, 0)))
            self.tracking = True
        if key != self.hover:
            self.hover = key
            self.invalidate()

    def on_left_up(self, kind, obj):
        if self.press:
            ReleaseCapture()
            pressed = self.press[0]
            self.press = None
            if self.drag:
                self.finish_drag()
                return
            if kind == "entry" and obj is pressed:
                self.click_entry(obj)
            return
        if kind == "start":
            self.app.start.toggle()
        elif kind == "desk":
            self.show_desktop()
        elif kind == "preview":
            self.app.preview.toggle()

    def on_timer(self):
        self.tick += 1
        dirty = False
        self.app.check_config()
        if not self.app.autostarted and self.tick >= max(1, int(self.app.cfg["autostart_delay"])):
            self.app.run_autostart()
        if self.tick % 2 == 0 and self.refresh():
            dirty = True
        self.check_fullscreen()
        fg = GetForegroundWindow()
        if fg != self.last_fg:
            self.last_fg, dirty = fg, True
        if self.app.clock_str() != self.clock_text:
            dirty = True
        if dirty:
            self.invalidate()


# ==========================================================================
# Start menu (Windows 10 layout: rail, user + app list, pinned tiles)
# ==========================================================================
class StartMenu(Window):
    CLASS = "WinShellStart"
    SIZES = {"small": (1, 1), "medium": (2, 2), "wide": (4, 2), "large": (4, 4)}

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.visible = False
        self.query = ""
        self.scroll = 0
        self.apps = []
        self.rows = []
        self.hover = None
        self.press = None
        self.dragging = False
        self.closed_at = 0.0
        self.edit = None
        self.edit_brush = None
        self.tile_drag = None
        self.drag_pos = (0, 0)
        self.shuffle_perm = None
        self.last_shuffle = 0.0

    # ---- geometry
    def dims(self):
        p = self.app.px
        sw, _sh = screen_size()
        l, t, r, b = self.app.work_rect()
        rail, listw, tilesw = p(48), (0 if self.app.cfg["start_collapsed"] else p(290)), p(330)
        W = min(rail + listw + tilesw, sw)
        Hh = min(p(620), b - t)
        return rail, listw, tilesw, W, Hh

    def position(self):
        rail, listw, tilesw, W, Hh = self.dims()
        sw, _sh = screen_size()
        al = self.app.cfg["alignment"]
        x = (sw - W) // 2 if al == "center" else (sw - W if al == "right" else 0)
        l, t, r, b = self.app.work_rect()
        y = b - Hh if self.app.cfg["position"] == "bottom" else t
        return x, y, W, Hh

    def search_rect(self):
        rail, listw = self.dims()[:2]
        p = self.app.px
        return (rail + p(10), p(60), rail + listw - p(10), p(92))

    def edit_rect(self):
        l, t, r, b = self.search_rect()
        p = self.app.px
        return (l + p(30), t + 5, r - p(36), b - 5)

    def add_rect(self):
        l, t, r, b = self.search_rect()
        return (r - self.app.px(32), t, r, b)

    # ---- open / close
    def toggle(self):
        if self.visible:
            self.close()
        elif time.time() - self.closed_at > 0.3:
            self.open()

    def apply_edit(self):
        if not self.edit:
            return
        l, t, r, b = self.edit_rect()
        SetWindowPos(self.edit, None, l, t, r - l, b - t, SWP_NOZORDER | SWP_NOACTIVATE)
        SendMessageW(self.edit, WM_SETFONT, self.app.font or 0, 1)
        ShowWindow(self.edit, 0 if self.app.cfg["start_collapsed"] else 5)
        if self.edit_brush:
            DeleteObject(self.edit_brush)
        self.edit_brush = CreateSolidBrush(self.app.theme()["input"])

    def open(self):
        self.scan()
        self.query, self.scroll = "", 0
        x, y, W, Hh = self.position()
        if not self.hwnd:
            Window.register(self.CLASS)
            self.create_window(self.CLASS, "Start", WS_POPUP,
                               WS_EX_TOPMOST | WS_EX_TOOLWINDOW, x, y, W, Hh)
            self.edit = make_child("EDIT", "", 0x80, 0, 0, 10, 10, 200, self.hwnd)
        self.apply_edit()
        SetWindowTextW(self.edit, "")
        self.build_rows()
        SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, W, Hh, 0)
        apply_glass(self.hwnd, self.app.cfg["glass"], self.app.cfg["glass_opacity"])
        self.visible = True
        ShowWindow(self.hwnd, 5)
        SetForegroundWindow(self.hwnd)
        SetFocus(self.edit)
        SetTimer(self.hwnd, 5, 1000, None)
        self.invalidate()
        self.app.bar.invalidate()

    def close(self):
        if self.visible:
            self.visible = False
            self.closed_at = time.time()
            KillTimer(self.hwnd, 5)
            ShowWindow(self.hwnd, 0)
            self.app.bar.invalidate()

    def apply(self):
        if self.hwnd:
            apply_glass(self.hwnd, self.app.cfg["glass"], self.app.cfg["glass_opacity"])
            self.apply_edit()
            if self.visible:
                x, y, W, Hh = self.position()
                SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, W, Hh, 0)
                self.invalidate()

    # ---- data
    def scan(self):
        c = self.app.cfg
        seen = {}
        roots = [os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                              r"Microsoft\Windows\Start Menu\Programs"),
                 os.path.join(os.environ.get("APPDATA", ""),
                              r"Microsoft\Windows\Start Menu\Programs")]

        def walk(path, depth):
            try:
                entries = list(os.scandir(path))
            except OSError:
                return
            for e in entries:
                if e.is_dir():
                    if depth < 4:
                        walk(e.path, depth + 1)
                elif e.name.lower().endswith(".lnk"):
                    name = os.path.splitext(e.name)[0]
                    if not name.lower().startswith("uninstall"):
                        seen.setdefault(name.lower(), (name, e.path))

        for r in roots:
            walk(r, 0)
        for pth in c["start_extra"]:                 # apps the user added
            name = display_name(pth)
            seen[name.lower()] = (name, pth)
        hidden = {h.lower() for h in c["start_hidden"]}
        self.apps = sorted((v for v in seen.values() if v[1].lower() not in hidden),
                           key=lambda t: t[0].lower())

    def build_rows(self):
        c = self.app.cfg
        q = self.query.lower().strip()
        by_path = {p.lower(): (n, p) for n, p in self.apps}
        rows = []
        if q:
            rows = [("app", p, n) for n, p in self.apps if q in n.lower()]
        else:
            starred = [by_path[p.lower()] for p in c["start_starred"] if p.lower() in by_path]
            if starred:
                rows.append(("head", "Starred", "Starred"))
                rows += [("app", p, n) for n, p in starred]
            usage = sorted(c["start_usage"].items(), key=lambda kv: -kv[1])
            used = [by_path[p.lower()] for p, cnt in usage[:8]
                    if cnt > 0 and p.lower() in by_path][:5]
            if used:
                rows.append(("head", "Most used", "Most used"))
                rows += [("app", p, n) for n, p in used]
            last = ""
            for n, p in self.apps:
                letter = n[0].upper() if n[0].isalpha() else "#"
                if letter != last:
                    rows.append(("head", letter, letter))
                    last = letter
                rows.append(("app", p, n))
        self.rows = rows
        self.scroll = 0

    # ---- layout helpers
    def row_h(self, kind):
        return self.app.px(30 if kind == "head" else 40)

    def list_top(self):
        return self.app.px(56) + self.app.px(40)

    def content_h(self):
        return sum(self.row_h(r[0]) for r in self.rows)

    def clamp_scroll(self):
        Hh = self.dims()[4]
        self.scroll = max(0, min(self.scroll, max(0, self.content_h() - (Hh - self.list_top()))))

    def rail_items(self):
        Hh = self.dims()[4]
        r = self.app.px(48)
        ids = ["power", "settings", "pictures", "docs"]
        out = [(ids[i], (0, Hh - r * (i + 1), r, Hh - r * i)) for i in range(4)]
        out.append(("menu", (0, 0, r, r)))
        return out

    def pins(self):
        pins = list(self.app.cfg["start_pins"])
        if self.shuffle_perm and sorted(self.shuffle_perm) == sorted(pins):
            return list(self.shuffle_perm)
        return pins

    def tile_color(self, path, icon, th):
        c = self.app.cfg
        if not c["tile_random_colors"]:
            return shade(ICONS.accent(icon, th["accent"]), 0.55)
        cols = c["tile_colors"]
        if path not in cols or hex_color(cols[path], None) is None:
            used = {cols.get(p) for p in c["start_pins"] if p != path}
            free = [h for h in TILE_PALETTE if h not in used] or TILE_PALETTE
            cols[path] = random.choice(free)
            self.app.save()
        return hex_color(cols[path], th["accent"])

    def shuffle_tick(self):
        c = self.app.cfg
        if not c["tile_shuffle"] or self.tile_drag:
            return
        if time.time() - self.last_shuffle < float(c["tile_shuffle_seconds"]):
            return
        self.last_shuffle = time.time()
        pins, sizes, groups = self.pins(), c["start_tile_sizes"], {}
        for i, p in enumerate(pins):
            groups.setdefault(sizes.get(p, "medium"), []).append(i)
        cands = [g for g in groups.values() if len(g) > 1]
        if cands:
            i, j = random.sample(random.choice(cands), 2)
            pins[i], pins[j] = pins[j], pins[i]
            self.shuffle_perm = pins
            self.invalidate()

    def drop_tile(self, x, y):
        a, c = self.app, self.app.cfg
        src, self.tile_drag = self.tile_drag, None
        kind, path, _s = self.hit(x, y)
        if kind == "tile" and path == src:
            self.invalidate()
            return
        pins = self.pins()
        if src in pins:
            pins.remove(src)
            if kind == "tile" and path in pins:
                pins.insert(pins.index(path), src)
            else:
                pins.append(src)
            c["start_pins"], self.shuffle_perm = pins, None
            a.save()
        self.invalidate()

    def tile_rects(self):
        """Pack pinned tiles on a 6-unit grid (small 1x1, medium 2x2, wide 4x2, large 4x4)."""
        a, c = self.app, self.app.cfg
        rail, listw, tilesw, _W, Hh = self.dims()
        cu = (tilesw - a.px(24)) / 6.0
        gap = a.px(4)
        x0, y0 = rail + listw + a.px(12), a.px(44)
        max_rows = int((Hh - y0) / cu)
        occ, out = set(), []
        for pth in self.pins():
            name = c["start_tile_sizes"].get(pth, "medium")
            w, h = self.SIZES.get(name, (2, 2))
            spot = None
            for row in range(0, max(0, max_rows - h + 1)):
                for col in range(0, 6 - w + 1):
                    if all((col + i, row + j) not in occ for i in range(w) for j in range(h)):
                        spot = (col, row)
                        break
                if spot:
                    break
            if not spot:
                continue
            col, row = spot
            for i in range(w):
                for j in range(h):
                    occ.add((col + i, row + j))
            x, y = x0 + col * cu, y0 + row * cu
            out.append((pth, (int(x), int(y), int(x + w * cu - gap), int(y + h * cu - gap)), name))
        return out

    def hit(self, x, y):
        a = self.app
        rail, listw, tilesw, W, Hh = self.dims()
        for rid, r in self.rail_items():
            if inside(r, x, y):
                return "rail", rid, ""
        if rail <= x < rail + listw:
            if y < a.px(56):
                return "user", "user", ""
            if y < self.list_top():
                if inside(self.add_rect(), x, y):
                    return "add", "add", ""
                return "search", "search", ""
            ry = self.list_top() - self.scroll
            for kind, path, name in self.rows:
                h = self.row_h(kind)
                if ry <= y < ry + h and kind == "app":
                    return "app", path, name
                ry += h
        for pth, r, sz in self.tile_rects():
            if inside(r, x, y):
                return "tile", pth, sz
        return None, None, None

    # ---- painting
    def paint(self):
        ps = PAINTSTRUCT()
        hdc = BeginPaint(self.hwnd, byref(ps))
        try:
            W, Hh = self.dims()[3:5]
            mem = CreateCompatibleDC(hdc)
            bmp = CreateCompatibleBitmap(hdc, W, Hh)
            old = SelectObject(mem, bmp)
            self.draw(mem, W, Hh)
            BitBlt(hdc, 0, 0, W, Hh, mem, 0, 0, SRCCOPY)
            SelectObject(mem, old)
            DeleteObject(bmp)
            DeleteDC(mem)
        finally:
            EndPaint(self.hwnd, byref(ps))

    def draw(self, hdc, W, Hh):
        a = self.app
        th = a.theme()
        rail, listw, tilesw, _W, _H = self.dims()
        p = a.px
        base = th["start_bg"]
        fill(hdc, (0, 0, W, Hh), base)
        if a.cfg["glass_blur_start"]:
            sx, sy = self.position()[:2]
            if a.paint_blur(hdc, W, Hh, sx, sy):
                alpha_rect(hdc, (0, 0, W, Hh), base, 165)
        if a.cfg["glass"]:
            alpha_rect(hdc, (0, 0, W, Hh // 3), rgb(255, 255, 255), 12)
        SetBkMode(hdc, 1)
        old = SelectObject(hdc, a.font)

        ry = self.list_top() - self.scroll
        for kind, path, name in (self.rows if listw else []):
            h = self.row_h(kind)
            if ry + h > self.list_top() and ry < Hh:
                if kind == "head":
                    text_out(hdc, name, (rail + p(16), ry, rail + listw, ry + h),
                             DT_VCENTER | DT_SINGLELINE, th["accent"])
                else:
                    if self.hover == ("app", path):
                        fill(hdc, (rail, ry, rail + listw, ry + h), th["hover"])
                    ic = ICONS.file_icon(path, False)
                    isz = p(24)
                    draw_icon_or_letter(hdc, ic, rail + p(14), ry + (h - isz) // 2, isz, name)
                    text_out(hdc, name, (rail + p(50), ry, rail + listw - p(8), ry + h),
                             DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS | DT_NOPREFIX,
                             th["text"])
            ry += h
        if listw and not self.rows:
            text_out(hdc, "No matching apps", (rail + p(16), self.list_top(), rail + listw,
                                              self.list_top() + p(40)),
                     DT_VCENTER | DT_SINGLELINE, th["dim"])

        if listw:
            fill(hdc, (rail, 0, rail + listw, self.list_top()), base)
            if self.hover == ("user", "user"):
                fill(hdc, (rail, 0, rail + listw, p(56)), th["hover"])
            a.draw_avatar(hdc, rail + p(34), p(28), p(40))
            old2 = SelectObject(hdc, a.font_big)
            text_out(hdc, a.cfg["user_name"], (rail + p(64), 0, rail + listw - p(8), p(56)),
                     DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS | DT_NOPREFIX, th["text"])
            SelectObject(hdc, old2)
            sr = self.search_rect()
            fill(hdc, sr, th["input"])
            frame(hdc, sr, th["accent"] if self.query else th["active"])
            self.glyph(hdc, "search", (sr[0], sr[1], sr[0] + p(30), sr[3]), th["dim"])
            ar = self.add_rect()
            if self.hover == ("add", "add"):
                fill(hdc, ar, th["hover"])
            self.glyph(hdc, "plus", ar, th["text"])

        fill(hdc, (0, 0, rail, Hh), th["rail"])
        for rid, r in self.rail_items():
            if self.hover == ("rail", rid):
                fill(hdc, r, th["hover"])
            self.glyph(hdc, rid, r, th["text"])

        text_out(hdc, "Pinned", (rail + listw + p(12), p(10), W - p(8), p(40)),
                 DT_VCENTER | DT_SINGLELINE, th["text"])
        for pth, r, sz in self.tile_rects():
            ic = ICONS.file_icon(pth, True)
            fill(hdc, r, self.tile_color(pth, ic, th))
            if self.hover == ("tile", pth):
                frame(hdc, r, rgb(255, 255, 255), 2)
            w, h = r[2] - r[0], r[3] - r[1]
            isz = min(p(64), max(16, int(min(w, h) * (0.6 if sz == "small" else 0.42))))
            iy = r[1] + (h - isz) // 2 if sz == "small" else r[1] + int(h * 0.14)
            draw_icon_or_letter(hdc, ic, r[0] + (w - isz) // 2, iy, isz, display_name(pth))
            if sz != "small":
                text_out(hdc, display_name(pth), (r[0] + p(6), r[3] - p(26), r[2] - p(4), r[3] - p(4)),
                         DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS | DT_NOPREFIX,
                         rgb(255, 255, 255))
        if self.tile_drag:                    # tile being dragged follows the pointer
            ic = ICONS.file_icon(self.tile_drag, True)
            gx, gy, gz = self.drag_pos[0], self.drag_pos[1], p(60)
            fill(hdc, (gx - gz // 2, gy - gz // 2, gx + gz // 2, gy + gz // 2),
                 self.tile_color(self.tile_drag, ic, th))
            draw_icon_or_letter(hdc, ic, gx - p(16), gy - p(16), p(32), display_name(self.tile_drag))
        SelectObject(hdc, old)

    def glyph(self, hdc, kind, rect, color):
        draw_glyph(hdc, kind, rect, color, size=self.app.px(22))

    # ---- actions
    def launch(self, path):
        c = self.app.cfg
        c["start_usage"][path] = c["start_usage"].get(path, 0) + 1
        self.app.save()
        self.close()
        self.app.run(path)

    def add_app(self):
        a = self.app
        a.menu_depth += 1
        try:
            pth = browse_file(self.hwnd, "Add an app to the Start menu", FILTER_PROGRAMS)
        finally:
            a.menu_depth -= 1
        if pth:
            if pth not in a.cfg["start_extra"]:
                a.cfg["start_extra"].append(pth)
            a.cfg["start_hidden"] = [h for h in a.cfg["start_hidden"] if h.lower() != pth.lower()]
            a.save()
            self.scan()
            self.build_rows()
        SetForegroundWindow(self.hwnd)
        self.invalidate()

    def item_menu(self, kind, path, name):
        a, c = self.app, self.app.cfg
        pinned_bar = app_key(exe_for(path)) in [app_key(exe_for(x)) for x in c["pinned"]]
        starred = path in c["start_starred"]
        if kind == "tile":
            cur = c["start_tile_sizes"].get(path, "medium")
            items = [(1, "Open"), (2, "Unpin from Start"), None,
                     (11, "Size: Small", MF_CHECKED if cur == "small" else 0),
                     (12, "Size: Medium", MF_CHECKED if cur == "medium" else 0),
                     (13, "Size: Wide", MF_CHECKED if cur == "wide" else 0),
                     (14, "Size: Large", MF_CHECKED if cur == "large" else 0), None,
                     (3, "Unpin from taskbar" if pinned_bar else "Pin to taskbar")]
        else:
            items = [(1, "Open"),
                     (2, "Unpin from Start" if path in c["start_pins"] else "Pin to Start"),
                     (3, "Unpin from taskbar" if pinned_bar else "Pin to taskbar"),
                     (4, "Remove from Starred" if starred else "Add to Starred"),
                     (5, "Remove from this list"), (6, "Open file location")]
        cmd = a.popup(self.hwnd, items, TPM_RETURNCMD | TPM_RIGHTBUTTON)
        if cmd == 1:
            self.launch(path)
        elif cmd == 2:
            a.toggle_list("start_pins", path)
        elif cmd == 3:
            if pinned_bar:
                a.unpin_taskbar(app_key(exe_for(path)))
            else:
                a.pin_taskbar(path)
        elif cmd == 4:
            a.toggle_list("start_starred", path)
            self.build_rows()
        elif cmd == 5:
            if path in c["start_extra"]:
                c["start_extra"].remove(path)
            elif path not in c["start_hidden"]:
                c["start_hidden"].append(path)
            a.save()
            self.scan()
            self.build_rows()
        elif cmd == 6:
            a.run("explorer.exe", '/select,"%s"' % exe_for(path))
        elif cmd in (11, 12, 13, 14):
            c["start_tile_sizes"][path] = {11: "small", 12: "medium", 13: "wide", 14: "large"}[cmd]
            a.save()
        self.invalidate()

    def user_menu(self):
        a = self.app
        cmd = a.popup(self.hwnd, [(1, "Change account picture..."), (2, "Change user name...")],
                      TPM_RETURNCMD | TPM_RIGHTBUTTON)
        if cmd == 1:
            a.menu_depth += 1
            try:
                path = browse_file(self.hwnd, "Choose your picture", FILTER_IMAGES)
            finally:
                a.menu_depth -= 1
            if path:
                a.cfg["user_photo"] = path
                a.save()
            SetForegroundWindow(self.hwnd)
            self.invalidate()
        elif cmd == 2:
            self.close()
            a.open_settings("User")

    def power_menu(self):
        cmd = self.app.popup(self.hwnd, [(1, "Restart taskbar"), (2, "Exit taskbar"),
                                         None, (3, "Shut down Wine session")],
                             TPM_RETURNCMD | TPM_RIGHTBUTTON)
        if cmd == 1:
            self.app.restart()
        elif cmd == 2:
            self.close()
            PostMessageW(self.app.bar.hwnd, WM_CLOSE, 0, 0)
        elif cmd == 3:
            self.app.run("wineboot.exe", "-s", 0)

    def rail_action(self, rid):
        home = os.environ.get("USERPROFILE", r"C:\users\Public")
        if rid == "menu":                       # collapse / expand the app list
            c = self.app.cfg
            c["start_collapsed"] = not c["start_collapsed"]
            self.app.save()
            self.apply()
            self.invalidate()
            return
        if rid == "docs":
            self.launch(os.path.join(home, "Documents"))
        elif rid == "pictures":
            self.launch(os.path.join(home, "Pictures"))
        elif rid == "settings":
            self.close()
            self.app.open_settings()
        elif rid == "power":
            self.power_menu()

    # ---- messages
    def on_message(self, hwnd, msg, wp, lp):
        a = self.app
        if msg == WM_TIMER and wp == 5:
            self.shuffle_tick()
            return 0
        if msg == WM_PAINT:
            self.paint()
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_ACTIVATE:
            if (wp & 0xFFFF) == 0 and self.visible and a.menu_depth == 0:
                self.close()
            return 0
        if msg == WM_COMMAND:                 # search box changed
            if (wp & 0xFFFF) == 200 and ((wp >> 16) & 0xFFFF) == EN_CHANGE:
                buf = create_unicode_buffer(256)
                GetWindowTextW(self.edit, buf, 256)
                if buf.value != self.query:
                    self.query = buf.value
                    self.build_rows()
                    self.invalidate()
            return 0
        if msg == WM_CTLCOLOREDIT:
            th = a.theme()
            SetTextColor(wp, th["text"])
            SetBkColor(wp, th["input"])
            return self.edit_brush or 0
        if msg == WM_MOUSEMOVE:
            x, y = xy(lp)
            if self.press and self.press[3] == "tile" and \
                    abs(x - self.press[0]) + abs(y - self.press[1]) > a.px(8):
                self.tile_drag = self.press[4]
            if self.tile_drag:
                self.drag_pos = (x, y)
                self.invalidate()
                return 0
            if self.press and abs(y - self.press[1]) > a.px(6) and self.press[3] == "app":
                self.dragging = True
            if self.dragging:
                self.scroll = self.press[2] - (y - self.press[1])
                self.clamp_scroll()
                self.invalidate()
                return 0
            kind, path, _n = self.hit(x, y)
            key = (kind, path) if kind else None
            if key != self.hover:
                self.hover = key
                self.invalidate()
            return 0
        if msg == WM_LBUTTONDOWN:
            x, y = xy(lp)
            kind, path, name = self.hit(x, y)
            self.press = (x, y, self.scroll, kind, path, name)
            self.dragging = False
            SetCapture(hwnd)
            return 0
        if msg == WM_LBUTTONUP:
            ReleaseCapture()
            press, dragged = self.press, self.dragging
            self.press, self.dragging = None, False
            if self.tile_drag:
                self.drop_tile(*xy(lp))
                return 0
            if press and not dragged:
                kind, path = press[3], press[4]
                x, y = xy(lp)
                if self.hit(x, y)[:2] == (kind, path):
                    if kind in ("app", "tile"):
                        self.launch(path)
                    elif kind == "rail":
                        self.rail_action(path)
                    elif kind == "user":
                        self.user_menu()
                    elif kind == "add":
                        self.add_app()
                    elif kind == "search":
                        SetFocus(self.edit)
            return 0
        if msg == WM_RBUTTONUP:
            x, y = xy(lp)
            kind, path, name = self.hit(x, y)
            if kind in ("app", "tile"):
                self.item_menu(kind, path, name)
            elif kind == "user":
                self.user_menu()
            return 0
        if msg == WM_MOUSEWHEEL:
            delta = c_short((wp >> 16) & 0xFFFF).value
            self.scroll -= (delta // 120) * a.px(60)
            self.clamp_scroll()
            self.invalidate()
            return 0
        if msg == WM_CHAR and self.edit:      # typing anywhere goes to the search box
            SetFocus(self.edit)
            PostMessageW(self.edit, WM_CHAR, wp, lp)
            return 0
        return DefWindowProcW(hwnd, msg, wp, lp)


# ==========================================================================
# Desktop (full desktop mode: wallpaper + movable icons on a grid)
# ==========================================================================
class Item:
    def __init__(self, path):
        self.path = path
        self.label = display_name(path)
        self.col = None
        self.row = None
        self.start = (0, 0)


class Desktop(Window):
    CLASS = "WinShellDesktop"

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.items = []
        self.selected = set()
        self.wall = None
        self.wall_sig = None
        self.hover = None
        self.press = None
        self.dragging = False
        self.rubber = None
        self.renaming = None
        self.rename_text = ""

    def desktop_dir(self):
        return os.path.join(os.environ.get("USERPROFILE", r"C:\users\Public"), "Desktop")

    # ---- lifecycle
    def apply(self, changed=None):
        a, c = self.app, self.app.cfg
        if not c["full_desktop"]:
            if self.hwnd:
                ShowWindow(self.hwnd, 0)
            return
        sw, sh = screen_size()
        # The desktop window covers only the work area (not the whole monitor): a window
        # that covers the full screen is treated as full-screen by Wine/X11 and ends up
        # ABOVE the taskbar. Leaving the bar strip free keeps the taskbar visible.
        wl, wtop, wr, wb = a.work_rect()
        if not self.hwnd:
            Window.register(self.CLASS, 0x8)       # CS_DBLCLKS
            self.create_window(self.CLASS, "WinShell Desktop", WS_POPUP | WS_VISIBLE,
                               WS_EX_TOOLWINDOW, wl, wtop, wr - wl, wb - wtop)
        SetWindowPos(self.hwnd, HWND_BOTTOM, wl, wtop, wr - wl, wb - wtop, SWP_NOACTIVATE)
        ShowWindow(self.hwnd, 8)
        sig = (c["wallpaper"], c["wallpaper_mode"], c["desktop_color"], sw, sh)
        if sig != self.wall_sig:
            self.wall_sig = sig
            self.build_wall()
        self.rebuild()
        self.invalidate()

    def build_wall(self):
        if self.wall:
            DeleteObject(self.wall)
        sw, sh = screen_size()
        self.wall = render_wallpaper(self.app.cfg, sw, sh)

    # ---- items
    def grid(self):
        return max(48, int(self.app.cfg["grid_size"]))

    def rebuild(self):
        c = self.app.cfg
        hidden = {h.lower() for h in c["desktop_hidden"]}
        paths = ["::thispc"]
        try:
            for e in sorted(os.scandir(self.desktop_dir()), key=lambda e: e.name.lower()):
                if not e.name.startswith(".") and e.name.lower() != "desktop.ini":
                    paths.append(e.path)
        except OSError:
            pass
        paths += [p for p in c["desktop_extra"] if p not in paths]
        old = {it.path.lower(): it for it in self.items}
        items = []
        for p in paths:
            if p.lower() in hidden:
                continue
            it = old.get(p.lower()) or Item(p)
            saved = c["desktop_layout"].get(p)
            if saved:
                it.col, it.row = saved.get("c"), saved.get("r")
                if saved.get("label"):
                    it.label = saved["label"]
            items.append(it)
        self.items = items
        self.selected &= set(items)
        self.assign_cells()

    def cells_per_col(self):
        l, t, r, b = self.app.work_rect()
        return max(1, (b - t) // self.grid())

    def assign_cells(self):
        used = {(round(i.col), round(i.row)) for i in self.items if i.col is not None}
        rows = self.cells_per_col()
        for it in self.items:
            if it.col is None:
                n = 0
                while True:
                    cell = (n // rows, n % rows)
                    if cell not in used:
                        break
                    n += 1
                it.col, it.row = cell
                used.add(cell)

    def save_layout(self):
        lay = self.app.cfg["desktop_layout"]
        for it in self.items:
            default = display_name(it.path)
            lay[it.path] = {"c": it.col, "r": it.row,
                            "label": it.label if it.label != default else ""}
        self.app.save()

    def cell_rect(self, it):
        g = self.grid()
        x, y = int(it.col * g), int(it.row * g)
        return (x, y, x + g, y + g)

    def item_at(self, x, y):
        for it in reversed(self.items):
            if inside(self.cell_rect(it), x, y):
                return it
        return None

    # ---- painting
    def paint(self):
        ps = PAINTSTRUCT()
        hdc = BeginPaint(self.hwnd, byref(ps))
        try:
            rc = RECT()
            GetClientRect(self.hwnd, byref(rc))
            W, Hh = rc.right, rc.bottom
            if W > 0 and Hh > 0:
                mem = CreateCompatibleDC(hdc)
                bmp = CreateCompatibleBitmap(hdc, W, Hh)
                old = SelectObject(mem, bmp)
                self.draw(mem, W, Hh)
                BitBlt(hdc, 0, 0, W, Hh, mem, 0, 0, SRCCOPY)
                SelectObject(mem, old)
                DeleteObject(bmp)
                DeleteDC(mem)
        finally:
            EndPaint(self.hwnd, byref(ps))

    def draw(self, hdc, W, Hh):
        a, c = self.app, self.app.cfg
        th = a.theme()
        if self.wall:
            src = CreateCompatibleDC(hdc)
            so = SelectObject(src, self.wall)
            wo = a.work_rect()
            BitBlt(hdc, 0, 0, W, Hh, src, wo[0], wo[1], SRCCOPY)
            SelectObject(src, so)
            DeleteDC(src)
        else:
            fill(hdc, (0, 0, W, Hh), hex_color(c["desktop_color"], rgb(30, 58, 95)))
        if c["show_desktop_icons"]:
            SetBkMode(hdc, 1)
            old = SelectObject(hdc, a.font)
            g = self.grid()
            isz = max(24, min(64, int(g * 0.45)))
            for it in self.items:
                r = self.cell_rect(it)
                if it in self.selected:
                    alpha_rect(hdc, r, th["accent"], 90)
                    frame(hdc, r, th["accent"])
                elif self.hover is it:
                    alpha_rect(hdc, r, rgb(255, 255, 255), 40)
                icon = ICONS.file_icon(it.path, True)
                draw_icon_or_letter(hdc, icon, r[0] + (g - isz) // 2, r[1] + int(g * 0.08), isz,
                                    it.label)
                label_rect = (r[0] + 2, r[1] + int(g * 0.08) + isz + 4, r[2] - 2, r[3] - 1)
                if it is self.renaming:
                    fill(hdc, label_rect, rgb(255, 255, 255))
                    text_out(hdc, self.rename_text + "|", label_rect,
                             DT_CENTER | DT_WORDBREAK | DT_NOPREFIX, rgb(0, 0, 0))
                else:
                    shadow = (label_rect[0] + 1, label_rect[1] + 1, label_rect[2] + 1,
                              label_rect[3] + 1)
                    flags = DT_CENTER | DT_WORDBREAK | DT_END_ELLIPSIS | DT_NOPREFIX
                    text_out(hdc, it.label, shadow, flags, rgb(0, 0, 0))
                    text_out(hdc, it.label, label_rect, flags, rgb(255, 255, 255))
            SelectObject(hdc, old)
        if self.rubber:
            x0, y0, x1, y1 = self.rubber
            rr = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            alpha_rect(hdc, rr, th["accent"], 70)
            frame(hdc, rr, th["accent"])

    # ---- actions
    def launch(self, it):
        if it.path == "::thispc" and self.app.cfg["use_winshell_explorer"]:
            self.app.open_explorer("")
        else:
            self.app.run("explorer.exe" if it.path == "::thispc" else it.path)

    def commit_rename(self):
        if self.renaming and self.rename_text.strip():
            self.renaming.label = self.rename_text.strip()
            self.save_layout()
        self.renaming = None

    def remove_items(self, items):
        c = self.app.cfg
        for it in items:
            if it.path in c["desktop_extra"]:
                c["desktop_extra"].remove(it.path)
            elif it.path not in c["desktop_hidden"]:
                c["desktop_hidden"].append(it.path)
        self.selected.clear()
        self.app.save()
        self.rebuild()
        self.invalidate()

    def new_folder(self):
        base, n = os.path.join(self.desktop_dir(), "New folder"), 1
        path = base
        while os.path.exists(path):
            n += 1
            path = "%s (%d)" % (base, n)
        try:
            os.makedirs(path)
        except OSError as exc:
            log.warning("new folder failed: %s", exc)
        self.rebuild()
        self.invalidate()

    def item_menu(self, it):
        cmd = self.app.popup(self.hwnd, [(1, "Open"), (2, "Rename"), (3, "Remove from desktop"),
                                         (4, "Show in file manager")],
                             TPM_RETURNCMD | TPM_RIGHTBUTTON)
        if cmd == 1:
            self.launch(it)
        elif cmd == 2:
            self.renaming, self.rename_text = it, it.label
        elif cmd == 3:
            self.remove_items(list(self.selected) or [it])
        elif cmd == 4 and it.path != "::thispc":
            self.app.run("explorer.exe", '/select,"%s"' % exe_for(it.path))
        self.invalidate()

    def empty_menu(self):
        a, c = self.app, self.app.cfg
        g = int(c["grid_size"])
        items = [(1, "Refresh"), None,
                 (2, "Large icons", MF_CHECKED if g >= 120 else 0),
                 (3, "Medium icons", MF_CHECKED if 84 <= g < 120 else 0),
                 (4, "Small icons", MF_CHECKED if g < 84 else 0),
                 (5, "Align icons to grid", MF_CHECKED if c["grid_snap"] else 0),
                 (6, "Show desktop icons", MF_CHECKED if c["show_desktop_icons"] else 0),
                 None, (7, "New folder"), (8, "Add shortcut..."), None,
                 (9, "Change wallpaper..."), (10, "Personalize / Settings")]
        cmd = a.popup(self.hwnd, items, TPM_RETURNCMD | TPM_RIGHTBUTTON)
        if cmd == 1:
            self.rebuild()
        elif cmd in (2, 3, 4):
            c["grid_size"] = {2: 128, 3: 96, 4: 72}[cmd]
            self.relayout()
        elif cmd == 5:
            c["grid_snap"] = not c["grid_snap"]
        elif cmd == 6:
            c["show_desktop_icons"] = not c["show_desktop_icons"]
        elif cmd == 7:
            self.new_folder()
        elif cmd == 8:
            p = browse_file(self.hwnd, "Add a shortcut to the desktop", FILTER_PROGRAMS)
            if p and p not in c["desktop_extra"]:
                c["desktop_extra"].append(p)
        elif cmd == 9:
            p = browse_file(self.hwnd, "Choose a wallpaper", FILTER_IMAGES)
            if p:
                c["wallpaper"] = p
                a.save()
                a.apply_all()
        elif cmd == 10:
            a.open_settings("Desktop")
        if cmd:
            a.save()
            self.rebuild()
        self.invalidate()

    def relayout(self):
        for it in self.items:        # re-flow only items without stored cells
            pass
        self.app.save()
        self.invalidate()

    # ---- messages
    def on_message(self, hwnd, msg, wp, lp):
        a, c = self.app, self.app.cfg
        if msg == WM_PAINT:
            self.paint()
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_WINDOWPOSCHANGING:      # always stay at the bottom of the z-order
            wpos = ctypes.cast(lp, POINTER(WINDOWPOS)).contents
            wpos.hwndInsertAfter = HWND_BOTTOM
            wpos.flags &= ~SWP_NOZORDER
            return 0
        if msg == WM_MOUSEACTIVATE:
            return 1
        if msg == WM_LBUTTONDOWN:
            SetFocus(hwnd)
            x, y = xy(lp)
            self.commit_rename()
            it = self.item_at(x, y) if c["show_desktop_icons"] else None
            ctrl = bool(GetKeyState(0x11) & 0x8000)
            if it:
                if ctrl:
                    self.selected ^= {it}
                elif it not in self.selected:
                    self.selected = {it}
                self.press = (x, y)
                for s in self.selected:
                    s.start = (s.col, s.row)
            else:
                if not ctrl:
                    self.selected = set()
                self.rubber = (x, y, x, y)
            self.dragging = False
            SetCapture(hwnd)
            self.invalidate()
            return 0
        if msg == WM_MOUSEMOVE:
            x, y = xy(lp)
            if self.rubber:
                x0, y0 = self.rubber[:2]
                self.rubber = (x0, y0, x, y)
                rr = (min(x0, x), min(y0, y), max(x0, x), max(y0, y))
                self.selected = {it for it in self.items
                                 if self.rects_overlap(self.cell_rect(it), rr)}
                self.invalidate()
            elif self.press:
                if abs(x - self.press[0]) + abs(y - self.press[1]) > a.px(6):
                    self.dragging = True
                if self.dragging:
                    g = float(self.grid())
                    dc, dr = (x - self.press[0]) / g, (y - self.press[1]) / g
                    for s in self.selected:
                        s.col, s.row = max(0.0, s.start[0] + dc), max(0.0, s.start[1] + dr)
                    self.invalidate()
            else:
                it = self.item_at(x, y)
                if it is not self.hover:
                    self.hover = it
                    self.invalidate()
            return 0
        if msg == WM_LBUTTONUP:
            ReleaseCapture()
            if self.dragging and c["grid_snap"]:
                for s in self.selected:
                    s.col, s.row = int(round(s.col)), int(round(s.row))
            if self.dragging:
                self.save_layout()
            self.press, self.dragging, self.rubber = None, False, None
            self.invalidate()
            return 0
        if msg == WM_LBUTTONDBLCLK:
            x, y = xy(lp)
            it = self.item_at(x, y)
            if it:
                self.launch(it)
            return 0
        if msg == WM_RBUTTONUP:
            x, y = xy(lp)
            it = self.item_at(x, y)
            if it:
                if it not in self.selected:
                    self.selected = {it}
                self.item_menu(it)
            else:
                self.empty_menu()
            return 0
        if msg == WM_MOUSEWHEEL and (GetKeyState(0x11) & 0x8000):   # Ctrl+wheel = grid size
            delta = c_short((wp >> 16) & 0xFFFF).value
            c["grid_size"] = max(48, min(240, int(c["grid_size"]) + (8 if delta > 0 else -8)))
            a.save()
            self.invalidate()
            return 0
        if msg == WM_CHAR and self.renaming:
            ch = wp
            if ch == 13:
                self.commit_rename()
            elif ch == 27:
                self.renaming = None
            elif ch == 8:
                self.rename_text = self.rename_text[:-1]
            elif ch >= 32:
                self.rename_text += chr(ch)
            self.invalidate()
            return 0
        if msg == WM_KEYDOWN and not self.renaming:
            if wp == 0x71 and self.selected:             # F2
                self.renaming = next(iter(self.selected))
                self.rename_text = self.renaming.label
            elif wp == 0x2E and self.selected:           # Delete
                self.remove_items(list(self.selected))
            elif wp == 0x74:                             # F5
                self.rebuild()
            self.invalidate()
            return 0
        return DefWindowProcW(hwnd, msg, wp, lp)

    @staticmethod
    def rects_overlap(a, b):
        return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


# ==========================================================================
# File Explorer (Windows 10 style: tabs, ribbon, address bar, favorites, grid view)
# ==========================================================================
RIBBON = {
    "Home": [("Copy", "copy", "copy"), ("Cut", "cut", "cut"), ("Paste", "paste", "paste"),
             ("New folder", "newdir", "folder_plus"), ("Delete", "delete", "trash"),
             ("Rename", "rename", "rename"), ("Favorite", "fav", "star"),
             ("Open CMD", "cmd", "cmd"), ("Refresh", "refresh", "refresh")],
    "View": [("Details", "v_details", "list"), ("Grid", "v_grid", "grid"),
             ("Larger", "g_plus", "plus"), ("Smaller", "g_minus", "minus"),
             ("Hidden", "hidden", "eye"), ("By name", "s_name", "sort"),
             ("By date", "s_date", "sort"), ("By size", "s_size", "sort"),
             ("By type", "s_type", "sort")],
}


class Explorer(Window):
    CLASS = "WinShellExplorer"

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.path = ""
        self.history, self.hpos = [], -1
        self.all_items, self.items = [], []
        self.sel = set()
        self.scroll = 0
        self.sort, self.sort_rev = "name", False
        self.tab = "Home"
        self.edit = None            # None | addr | search | rename
        self.edit_text = ""
        self.search = ""
        self.hover = None

    def pal(self):
        t = self.app.theme()
        return {"bg": t["win_bg"], "rib": t["rib"], "text": t["text"], "dim": t["dim"],
                "line": t["line"], "sel": t["sel"], "hover": t["hover"], "input": t["input"],
                "accent": t["accent"]}

    def bgfill(self, hdc, rect, color):
        if self.app.cfg["glass_blur_window"]:
            alpha_rect(hdc, rect, color, 205)
        else:
            fill(hdc, rect, color)

    # ---- lifecycle / navigation
    def create(self, path=None, select=None):
        a = self.app
        Window.register(self.CLASS, 0x8, None, a.explorer_icon())
        sw, sh = screen_size()
        w, h = min(1000, sw - 40), min(640, sh - 80)
        self.create_window(self.CLASS, "File Explorer", 0xCF0000 | WS_VISIBLE, 0,
                           max(0, (sw - w) // 2), max(0, (sh - h) // 2 - 20), w, h)
        icon = a.explorer_icon()
        SendMessageW(self.hwnd, WM_SETICON, 1, icon)
        SendMessageW(self.hwnd, WM_SETICON, 0, icon)
        a.explorers.append(self)
        if path is None:
            docs = os.path.join(os.environ.get("USERPROFILE", ""), "Documents")
            path = docs if os.path.isdir(docs) else ""
        self.go(path)
        if select:
            for i, it in enumerate(self.items):
                if it["path"].lower() == select.lower():
                    self.sel = {i}
        SetForegroundWindow(self.hwnd)

    def go(self, path, push=True):
        if len(path) == 2 and path[1] == ":":
            path += "\\"
        if path and not os.path.isdir(path):
            return False
        if push:
            self.history = self.history[:self.hpos + 1] + [path]
            self.hpos = len(self.history) - 1
        self.path, self.search, self.scroll, self.sel, self.edit = path, "", 0, set(), None
        self.load()
        title = "This PC" if not path else (os.path.basename(path.rstrip("\\/")) or path)
        SetWindowTextW(self.hwnd, title)
        return True

    def up(self):
        if self.path:
            parent = os.path.dirname(self.path.rstrip("\\/"))
            self.go(parent if parent and parent != self.path.rstrip("\\/") else "")

    def load(self):
        items = []
        if not self.path:
            for d in drive_list():
                items.append({"name": "Local Disk (%s)" % d[:2], "path": d, "is_dir": True,
                              "size": 0, "mtime": 0, "type": "Local Disk", "drive": True})
        else:
            try:
                for e in os.scandir(self.path):
                    if e.name.startswith(".") and not self.app.cfg["explorer_show_hidden"]:
                        continue
                    try:
                        st = e.stat()
                        size, mt = st.st_size, st.st_mtime
                    except OSError:
                        size, mt = 0, 0
                    isd = e.is_dir()
                    ext = os.path.splitext(e.name)[1]
                    items.append({"name": e.name, "path": e.path, "is_dir": isd,
                                  "size": 0 if isd else size, "mtime": mt,
                                  "type": "File folder" if isd else
                                  ((ext[1:].upper() + " File") if ext else "File")})
            except OSError as exc:
                log.info("explorer load failed: %s", exc)
        self.all_items = items
        self.apply_filter()

    def apply_filter(self):
        q = self.search.lower()
        items = [i for i in self.all_items if q in i["name"].lower()]
        keys = {"name": lambda i: i["name"].lower(), "date": lambda i: i["mtime"],
                "size": lambda i: i["size"], "type": lambda i: (i["type"].lower(), i["name"].lower())}
        items.sort(key=keys[self.sort], reverse=self.sort_rev)
        items.sort(key=lambda i: not i["is_dir"])
        self.items = items
        self.sel = set()
        self.invalidate()

    # ---- geometry
    def client(self):
        rc = RECT()
        GetClientRect(self.hwnd, byref(rc))
        return rc.right, rc.bottom

    def regions(self, W, H):
        P = self.app.px
        grid = self.app.cfg["explorer_view"] == "grid"
        tab_h, rib_h, bar_h, stat_h = P(28), P(86), P(38), P(26)
        hdr_h = 0 if grid else P(26)
        yb, yo = tab_h + rib_h, tab_h + rib_h + bar_h
        nav_w = P(220)
        ay0, ay1 = yb + P(5), yb + bar_h - P(5)
        sy0, sy1 = H - stat_h + P(3), H - P(3)
        return {"tab_h": tab_h, "rib": (0, tab_h, W, yb), "bar": (0, yb, W, yo),
                "nav": (0, yo, nav_w, H - stat_h), "hdr": (nav_w, yo, W, yo + hdr_h),
                "list": (nav_w, yo + hdr_h, W, H - stat_h), "stat": (0, H - stat_h, W, H),
                "back": (P(8), ay0, P(36), ay1), "fwd": (P(38), ay0, P(66), ay1),
                "up": (P(68), ay0, P(96), ay1), "refresh": (P(100), ay0, P(128), ay1),
                "addr": (P(134), ay0, W - P(240), ay1), "search": (W - P(230), ay0, W - P(8), ay1),
                "vdetails": (W - P(62), sy0, W - P(34), sy1), "vgrid": (W - P(32), sy0, W - P(4), sy1)}

    def tab_rects(self, r):
        P = self.app.px
        return [("File", (0, 0, P(64), r["tab_h"])), ("Home", (P(64), 0, P(128), r["tab_h"])),
                ("View", (P(128), 0, P(192), r["tab_h"]))]

    def ribbon_rects(self, r):
        P = self.app.px
        out, x = [], P(8)
        for label, act, icon in RIBBON.get(self.tab, []):
            out.append((act, label, icon, (x, r["tab_h"] + P(4), x + P(76), r["rib"][3] - P(4))))
            x += P(80)
        return out

    def cols(self, W, r):
        P = self.app.px
        x_size = W - P(90)
        x_type = x_size - P(120)
        x_date = x_type - P(150)
        return r["list"][0], x_date, x_type, x_size

    def view_info(self, W, r):
        P = self.app.px
        if self.app.cfg["explorer_view"] == "grid":
            g = P(int(self.app.cfg["explorer_grid_size"]))
            cols = max(1, (r["list"][2] - r["list"][0] - P(10)) // g)
            return "grid", g, g + P(26), cols
        return "details", 0, P(26), 1

    def item_rect(self, i, W, r):
        P = self.app.px
        mode, cw, chh, cols = self.view_info(W, r)
        lx, ltop = r["list"][0], r["list"][1]
        if mode == "grid":
            col, row = i % cols, i // cols
            x = lx + P(5) + col * cw
            return (x, ltop + row * chh - self.scroll, x + cw, ltop + (row + 1) * chh - self.scroll)
        return (lx, ltop + i * chh - self.scroll, r["list"][2], ltop + (i + 1) * chh - self.scroll)

    def content_h(self, W, r):
        mode, cw, chh, cols = self.view_info(W, r)
        return chh * (-(-len(self.items) // cols))

    def clamp_scroll(self, W, H):
        r = self.regions(W, H)
        span = r["list"][3] - r["list"][1]
        self.scroll = max(0, min(self.scroll, max(0, self.content_h(W, r) - span)))

    def nav_entries(self):
        cfg = self.app.cfg
        home = os.environ.get("USERPROFILE", "C:\\")
        out = []
        if cfg["bookmarks"]:
            out.append(("head", "Favorites", None, ""))
            for p in cfg["bookmarks"]:
                out.append(("fav", display_name(p), p, "star_fill"))
        out.append(("head", "Quick access", None, ""))
        for n in ("Desktop", "Downloads", "Documents", "Pictures", "Music", "Videos"):
            out.append(("item", n, os.path.join(home, n), "folder"))
        out += [("head", "This PC", None, ""), ("item", "This PC", "", "monitor")]
        for d in drive_list():
            out.append(("item", "Local Disk (%s)" % d[:2], d, "drive"))
        return out

    def hit(self, x, y):
        W, H = self.client()
        r = self.regions(W, H)
        P = self.app.px
        for name, rc in self.tab_rects(r):
            if inside(rc, x, y):
                return "tab", name
        if inside(r["rib"], x, y):
            for act, label, icon, rc in self.ribbon_rects(r):
                if inside(rc, x, y):
                    return "rib", act
            return "blank", None
        for k in ("back", "fwd", "up", "refresh", "addr", "search", "vdetails", "vgrid"):
            if inside(r[k], x, y):
                return k, None
        if inside(r["nav"], x, y):
            idx = (y - r["nav"][1] - P(6)) // P(28)
            ents = self.nav_entries()
            if 0 <= idx < len(ents) and ents[idx][0] != "head":
                return ("favnav" if ents[idx][0] == "fav" else "nav"), ents[idx][2]
            return "blank", None
        if inside(r["hdr"], x, y) and r["hdr"][3] > r["hdr"][1]:
            lx, xd, xt, xs = self.cols(W, r)
            return "hdr", ("name" if x < xd else "date" if x < xt else "type" if x < xs else "size")
        if inside(r["list"], x, y):
            mode, cw, chh, cols = self.view_info(W, r)
            row = (y - r["list"][1] + self.scroll) // chh
            if mode == "grid":
                col = (x - r["list"][0] - P(5)) // cw
                idx = row * cols + col if 0 <= col < cols else -1
            else:
                idx = row
            if 0 <= idx < len(self.items):
                return "row", idx
            return "blank", None
        return None, None

    # ---- painting
    def paint(self):
        ps = PAINTSTRUCT()
        hdc = BeginPaint(self.hwnd, byref(ps))
        try:
            W, H = self.client()
            if W > 0 and H > 0:
                mem = CreateCompatibleDC(hdc)
                bmp = CreateCompatibleBitmap(hdc, W, H)
                old = SelectObject(mem, bmp)
                self.draw(mem, W, H)
                BitBlt(hdc, 0, 0, W, H, mem, 0, 0, SRCCOPY)
                SelectObject(mem, old)
                DeleteObject(bmp)
                DeleteDC(mem)
        finally:
            EndPaint(self.hwnd, byref(ps))

    def draw_item_icon(self, hdc, it, x, y, size):
        if it.get("drive"):
            draw_file_icon(hdc, "drive", x, y, size)
        elif it["is_dir"]:
            draw_file_icon(hdc, "folder", x, y, size)
        elif it["name"].lower().endswith((".exe", ".lnk", ".ico", ".msi", ".bat")):
            draw_icon_or_letter(hdc, ICONS.file_icon(it["path"], size > 24), x, y, size, it["name"])
        else:
            draw_file_icon(hdc, file_category(it["name"]), x, y, size)

    def is_fav(self, path):
        return path in self.app.cfg["bookmarks"]

    def draw(self, hdc, W, H):
        a = self.app
        P = a.px
        th = self.pal()
        acc = th["accent"]
        r = self.regions(W, H)
        fill(hdc, (0, 0, W, H), th["bg"])
        if a.cfg["glass_blur_window"]:
            rc = RECT()
            GetWindowRect(self.hwnd, byref(rc))
            if a.paint_blur(hdc, W, H, rc.left, rc.top):
                alpha_rect(hdc, (0, 0, W, H), th["bg"], 200)
        SetBkMode(hdc, 1)
        old = SelectObject(hdc, a.font)
        txt = DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS | DT_NOPREFIX
        mode, cw, chh, cols = self.view_info(W, r)
        lx, xd, xt, xs = self.cols(W, r)
        ltop, lbot = r["list"][1], r["list"][3]

        # items (header / bars are painted over any overflow afterwards)
        for i, it in enumerate(self.items):
            ir = self.item_rect(i, W, r)
            if ir[3] < ltop or ir[1] > lbot:
                continue
            if i in self.sel:
                fill(hdc, ir, th["sel"])
            elif self.hover == ("row", i):
                fill(hdc, ir, th["hover"])
            if mode == "grid":
                isz = int((ir[2] - ir[0]) * 0.55)
                self.draw_item_icon(hdc, it, ir[0] + ((ir[2] - ir[0]) - isz) // 2, ir[1] + P(6), isz)
                label = (ir[0] + 2, ir[1] + P(10) + isz, ir[2] - 2, ir[3] - 2)
                if self.edit == "rename" and i in self.sel:
                    fill(hdc, label, th["input"])
                    text_out(hdc, self.edit_text + "|", label, DT_CENTER | DT_WORDBREAK | DT_NOPREFIX, th["text"])
                else:
                    text_out(hdc, it["name"], label, DT_CENTER | DT_WORDBREAK | DT_END_ELLIPSIS | DT_NOPREFIX, th["text"])
                continue
            self.draw_item_icon(hdc, it, lx + P(8), ir[1] + (ir[3] - ir[1] - P(18)) // 2, P(18))
            if self.edit == "rename" and i in self.sel:
                nb = (lx + P(32), ir[1] + 1, xd - 4, ir[3] - 1)
                fill(hdc, nb, th["input"])
                frame(hdc, nb, acc)
                text_out(hdc, self.edit_text + "|", (nb[0] + 4, ir[1], nb[2] - 2, ir[3]), txt, th["text"])
            else:
                text_out(hdc, it["name"], (lx + P(32), ir[1], xd - 6, ir[3]), txt, th["text"])
                if self.is_fav(it["path"]):
                    draw_glyph(hdc, "star_fill", (xd - P(26), ir[1], xd - P(4), ir[3]), rgb(255, 200, 0), size=P(13))
            if it["mtime"]:
                text_out(hdc, time.strftime("%d/%m/%Y %H:%M", time.localtime(it["mtime"])),
                         (xd + P(6), ir[1], xt, ir[3]), txt, th["dim"])
            text_out(hdc, it["type"], (xt + P(6), ir[1], xs, ir[3]), txt, th["dim"])
            if not it["is_dir"]:
                text_out(hdc, "%s KB" % format((it["size"] + 1023) // 1024, ","),
                         (xs, ir[1], W - P(14), ir[3]), txt | DT_CENTER, th["dim"])
        total = self.content_h(W, r)
        if total > lbot - ltop:                       # thin Windows 10 scroll bar
            span = lbot - ltop
            thumb = max(P(24), span * span // total)
            ty = ltop + (span - thumb) * self.scroll // max(1, total - span)
            fill(hdc, (W - P(9), ty, W - P(2), ty + thumb), rgb(160, 160, 160))

        # column header (details view)
        if r["hdr"][3] > r["hdr"][1]:
            self.bgfill(hdc, r["hdr"], th["bg"])
            fill(hdc, (r["hdr"][0], r["hdr"][3] - 1, W, r["hdr"][3]), th["line"])
            for label, x0, key in (("Name", lx + P(32), "name"), ("Date modified", xd + P(6), "date"),
                                   ("Type", xt + P(6), "type"), ("Size", xs, "size")):
                mark = (" v" if self.sort_rev else " ^") if self.sort == key else ""
                text_out(hdc, label + mark, (x0, r["hdr"][1], W, r["hdr"][3]), txt, th["dim"])

        # navigation pane
        self.bgfill(hdc, r["nav"], th["bg"])
        fill(hdc, (r["nav"][2] - 1, r["nav"][1], r["nav"][2], r["nav"][3]), th["line"])
        ny = r["nav"][1] + P(6)
        for kind, label, pth, icon in self.nav_entries():
            row = (0, ny, r["nav"][2] - 1, ny + P(28))
            if kind == "head":
                text_out(hdc, label, (P(10), ny, row[2], ny + P(28)), txt, acc)
            else:
                if pth == self.path:
                    fill(hdc, row, th["sel"])
                elif self.hover == ("nav", pth):
                    fill(hdc, row, th["hover"])
                ic = P(18)
                iy = ny + (P(28) - ic) // 2
                if icon == "folder":
                    draw_file_icon(hdc, "folder", P(16), iy, ic)
                elif icon == "drive":
                    draw_file_icon(hdc, "drive", P(16), iy, ic)
                else:
                    draw_glyph(hdc, icon, (P(14), ny, P(36), ny + P(28)),
                               rgb(255, 200, 0) if icon == "star_fill" else acc, size=P(16))
                text_out(hdc, label, (P(42), ny, row[2] - 4, ny + P(28)), txt, th["text"])
            ny += P(28)

        # navigation / address bar row
        self.bgfill(hdc, r["bar"], th["bg"])
        for k, g in (("back", "back"), ("fwd", "fwd"), ("up", "up"), ("refresh", "refresh")):
            if self.hover == (k, None):
                fill(hdc, r[k], th["hover"])
            ok = (k == "back" and self.hpos > 0) or (k == "fwd" and self.hpos < len(self.history) - 1) \
                or (k == "up" and bool(self.path)) or k == "refresh"
            draw_glyph(hdc, g, r[k], th["text"] if ok else th["line"], size=P(16))
        for key in ("addr", "search"):
            fill(hdc, r[key], th["input"])
            frame(hdc, r[key], acc if self.edit == key else th["line"])
        crumb = "This PC" if not self.path else self.path.rstrip("\\").replace("\\", "   >   ")
        shown = (self.edit_text + "|") if self.edit == "addr" else crumb
        draw_glyph(hdc, "folder", (r["addr"][0], r["addr"][1], r["addr"][0] + P(26), r["addr"][3]), th["dim"], size=P(15))
        text_out(hdc, shown, (r["addr"][0] + P(28), r["addr"][1], r["addr"][2] - P(6), r["addr"][3]), txt, th["text"])
        folder = "This PC" if not self.path else (os.path.basename(self.path.rstrip("\\")) or self.path)
        if self.edit == "search":
            shown, col = self.edit_text + "|", th["text"]
        elif self.search:
            shown, col = self.search, th["text"]
        else:
            shown, col = "Search " + folder, th["dim"]
        draw_glyph(hdc, "search", (r["search"][2] - P(28), r["search"][1], r["search"][2] - P(4), r["search"][3]), th["dim"], size=P(15))
        text_out(hdc, shown, (r["search"][0] + P(8), r["search"][1], r["search"][2] - P(32), r["search"][3]), txt, col)

        # tabs + ribbon (Windows 10 big icon buttons)
        self.bgfill(hdc, (0, 0, W, r["tab_h"]), th["bg"])
        for name, rc in self.tab_rects(r):
            if name == "File":
                fill(hdc, rc, rgb(25, 121, 202))
                text_out(hdc, name, rc, DT_CENTER | txt, rgb(255, 255, 255))
            else:
                if name == self.tab:
                    fill(hdc, rc, th["rib"])
                    fill(hdc, (rc[0], rc[1], rc[2], rc[1] + 2), acc)
                text_out(hdc, name, rc, DT_CENTER | txt, th["text"])
        self.bgfill(hdc, r["rib"], th["rib"])
        fill(hdc, (0, r["rib"][3] - 1, W, r["rib"][3]), th["line"])
        view = a.cfg["explorer_view"]
        cur = (self.selected_items()[0]["path"] if len(self.sel) == 1 else self.path)
        for act, label, icon, rc in self.ribbon_rects(r):
            on = (act == "v_details" and view == "details") or (act == "v_grid" and view == "grid") or \
                 (act == "hidden" and a.cfg["explorer_show_hidden"]) or (act == "fav" and cur and self.is_fav(cur))
            if on:
                fill(hdc, rc, th["sel"])
            elif self.hover == ("rib", act):
                fill(hdc, rc, th["hover"])
            draw_glyph(hdc, "star_fill" if (act == "fav" and on) else icon,
                       (rc[0], rc[1] + P(2), rc[2], rc[1] + P(44)),
                       rgb(255, 200, 0) if (act == "fav" and on) else acc, size=P(30))
            text_out(hdc, label, (rc[0], rc[3] - P(24), rc[2], rc[3]), DT_CENTER | txt, th["text"])

        # status bar with view switch
        self.bgfill(hdc, r["stat"], th["bg"])
        fill(hdc, (0, r["stat"][1], W, r["stat"][1] + 1), th["line"])
        msg = "%d items" % len(self.items) + ("    %d selected" % len(self.sel) if self.sel else "")
        text_out(hdc, msg, (P(10), r["stat"][1], W - P(80), r["stat"][3]), txt, th["dim"])
        for key, g, vv in (("vdetails", "list", "details"), ("vgrid", "grid", "grid")):
            if view == vv:
                fill(hdc, r[key], th["sel"])
            draw_glyph(hdc, g, r[key], th["text"], size=P(16))
        SelectObject(hdc, old)

    # ---- file operations
    def selected_items(self):
        return [self.items[i] for i in sorted(self.sel) if i < len(self.items)]

    @staticmethod
    def unique(path):
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        n = 1
        while True:
            cand = "%s - Copy%s%s" % (base, "" if n == 1 else " (%d)" % n, ext)
            if not os.path.exists(cand):
                return cand
            n += 1

    def toggle_fav(self, path):
        bk = self.app.cfg["bookmarks"]
        if path in bk:
            bk.remove(path)
        elif path:
            bk.append(path)
        self.app.save()
        self.invalidate()

    def do(self, act):
        a, cfg = self.app, self.app.cfg
        sel = [it["path"] for it in self.selected_items()]
        if act in ("copy", "cut") and sel:
            a.clip = (act, sel)
        elif act == "paste" and a.clip and self.path:
            mode, paths = a.clip
            for srcp in paths:
                dst = self.unique(os.path.join(self.path, os.path.basename(srcp.rstrip("\\/"))))
                try:
                    if mode == "cut":
                        shutil.move(srcp, dst)
                    elif os.path.isdir(srcp):
                        shutil.copytree(srcp, dst)
                    else:
                        shutil.copy2(srcp, dst)
                except (OSError, shutil.Error) as exc:
                    log.warning("paste failed: %s", exc)
            if mode == "cut":
                a.clip = None
            self.load()
        elif act == "newdir" and self.path:
            base, n, new = os.path.join(self.path, "New folder"), 1, os.path.join(self.path, "New folder")
            while os.path.exists(new):
                n += 1
                new = "%s (%d)" % (base, n)
            try:
                os.makedirs(new)
            except OSError as exc:
                log.warning("mkdir failed: %s", exc)
            self.load()
            for i, it in enumerate(self.items):
                if it["path"] == new:
                    self.sel = {i}
                    self.begin_edit("rename", it["name"])
        elif act == "delete" and sel:
            msg = "Permanently delete %d item(s)?" % len(sel)
            a.menu_depth += 1
            try:
                ans = MessageBoxW(self.hwnd, msg, "Delete", 0x4 | 0x30)
            finally:
                a.menu_depth -= 1
            if ans == 6:
                for pth in sel:
                    try:
                        shutil.rmtree(pth) if os.path.isdir(pth) else os.remove(pth)
                    except OSError as exc:
                        log.warning("delete failed: %s", exc)
                self.load()
        elif act == "rename" and len(sel) == 1:
            self.begin_edit("rename", self.selected_items()[0]["name"])
        elif act == "refresh":
            self.load()
        elif act == "fav":
            target = sel[0] if len(sel) == 1 else self.path
            self.toggle_fav(target)
        elif act == "cmd":
            a.run("cmd.exe", '/K cd /d "%s"' % (self.path or "C:\\"))
        elif act == "hidden":
            cfg["explorer_show_hidden"] = not cfg["explorer_show_hidden"]
            a.save()
            self.load()
        elif act in ("v_details", "v_grid"):
            cfg["explorer_view"] = "grid" if act == "v_grid" else "details"
            self.scroll = 0
            a.save()
        elif act in ("g_plus", "g_minus"):
            cfg["explorer_grid_size"] = max(64, min(200, int(cfg["explorer_grid_size"]) + (16 if act == "g_plus" else -16)))
            cfg["explorer_view"] = "grid"
            a.save()
        elif act.startswith("s_"):
            key = act[2:]
            self.sort_rev = (not self.sort_rev) if self.sort == key else False
            self.sort = key
            self.apply_filter()
        self.invalidate()

    def open_item(self, it):
        if it["is_dir"]:
            self.go(it["path"])
        else:
            self.app.open_path(it["path"])

    def begin_edit(self, target, text):
        self.edit, self.edit_text = target, text
        self.invalidate()

    def end_edit(self, commit):
        target, text = self.edit, self.edit_text
        self.edit = None
        if commit and target == "addr":
            t = text.strip().strip('"')
            self.go("" if t == "" or t.lower() == "this pc" else t)
        elif commit and target == "rename":
            sel = self.selected_items()
            if len(sel) == 1 and text.strip() and text != sel[0]["name"]:
                try:
                    os.rename(sel[0]["path"], os.path.join(os.path.dirname(sel[0]["path"]), text.strip()))
                except OSError as exc:
                    log.warning("rename failed: %s", exc)
                self.load()
        elif target == "search" and not commit:
            self.search = ""
            self.apply_filter()
        self.invalidate()

    def click(self, kind, data):
        if self.edit and not (kind in ("addr", "search") and self.edit == kind):
            self.end_edit(self.edit == "rename")
        a = self.app
        if kind == "tab":
            if data == "File":
                cmd = a.popup(self.hwnd, [(1, "Open new window"), (2, "Open command window here"),
                                          None, (3, "Close")], TPM_RETURNCMD | TPM_RIGHTBUTTON)
                if cmd == 1:
                    a.open_explorer(self.path)
                elif cmd == 2:
                    self.do("cmd")
                elif cmd == 3:
                    PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            else:
                self.tab = data
        elif kind == "rib":
            self.do(data)
        elif kind == "back" and self.hpos > 0:
            self.hpos -= 1
            self.go(self.history[self.hpos], False)
        elif kind == "fwd" and self.hpos < len(self.history) - 1:
            self.hpos += 1
            self.go(self.history[self.hpos], False)
        elif kind == "up":
            self.up()
        elif kind == "refresh":
            self.load()
        elif kind == "addr":
            self.begin_edit("addr", self.path)
        elif kind == "search":
            self.begin_edit("search", self.search)
        elif kind in ("nav", "favnav"):
            self.go(data)
        elif kind in ("vdetails", "vgrid"):
            self.do("v_details" if kind == "vdetails" else "v_grid")
        elif kind == "hdr":
            self.sort_rev = (not self.sort_rev) if self.sort == data else False
            self.sort = data
            self.apply_filter()
        elif kind == "row":
            if GetKeyState(0x11) & 0x8000:
                self.sel ^= {data}
            else:
                self.sel = {data}
        elif kind == "blank":
            self.sel = set()
        self.invalidate()

    # ---- context menus
    def apps_for_open_with(self):
        a = self.app
        apps = [(display_name(p), p) for p in a.cfg["open_with_apps"]]
        have = {p.lower() for _n, p in apps}
        for nm, exe in (("Notepad", "notepad.exe"), ("WordPad", "wordpad.exe"), ("Paint", "mspaint.exe")):
            full = find_exe(exe)
            if os.path.exists(full) and full.lower() not in have:
                apps.append((nm, full))
        return apps[:20]

    def item_menu(self, it):
        a = self.app
        apps = self.apps_for_open_with()
        fav = self.is_fav(it["path"])
        items = [(1, "Open")]
        if it["is_dir"]:
            items += [(2, "Open in new window"), (8, "Open command window here")]
        else:
            items.append(("sub", "Open with", [(100 + i, nm) for i, (nm, _p) in enumerate(apps)] +
                          [None, (150, "Choose another app...")], "open_with"))
            items.append(("sub", "Always open with", [(200 + i, nm) for i, (nm, _p) in enumerate(apps)] +
                          [None, (250, "Choose app...")], "open_with"))
        items += [None, (3, "Copy"), (4, "Cut"), None, (5, "Rename"), (6, "Delete"), None,
                  (7, "Remove from favorites" if fav else "Add to favorites")]
        cmd = a.popup(self.hwnd, items, TPM_RETURNCMD | TPM_RIGHTBUTTON)
        path = it["path"]
        if cmd == 1:
            self.open_item(it)
        elif cmd == 2:
            a.open_explorer(path)
        elif cmd == 3:
            self.do("copy")
        elif cmd == 4:
            self.do("cut")
        elif cmd == 5:
            self.do("rename")
        elif cmd == 6:
            self.do("delete")
        elif cmd == 7:
            self.toggle_fav(path)
        elif cmd == 8:
            a.run("cmd.exe", '/K cd /d "%s"' % path)
        elif 100 <= cmd < 150 and cmd - 100 < len(apps):
            a.run(apps[cmd - 100][1], '"%s"' % path)
        elif cmd in (150, 250):
            exe = self.choose_app()
            if exe:
                if cmd == 250:
                    a.cfg["assoc"][os.path.splitext(path)[1].lower()] = exe
                a.run(exe, '"%s"' % path)
                a.save()
        elif 200 <= cmd < 250 and cmd - 200 < len(apps):
            a.cfg["assoc"][os.path.splitext(path)[1].lower()] = apps[cmd - 200][1]
            a.save()
            a.run(apps[cmd - 200][1], '"%s"' % path)

    def choose_app(self):
        a = self.app
        a.menu_depth += 1
        try:
            exe = browse_file(self.hwnd, "Choose an app", FILTER_PROGRAMS)
        finally:
            a.menu_depth -= 1
        if exe and exe not in a.cfg["open_with_apps"]:
            a.cfg["open_with_apps"].append(exe)
            a.save()
        return exe

    # ---- messages
    def on_message(self, hwnd, msg, wp, lp):
        a = self.app
        if msg == WM_PAINT:
            self.paint()
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_SIZE:
            self.invalidate()
            return DefWindowProcW(hwnd, msg, wp, lp)
        if msg == WM_MOUSEMOVE:
            x, y = xy(lp)
            kind, data = self.hit(x, y)
            key = (kind, data) if kind in ("row", "nav", "rib", "back", "fwd", "up", "refresh") else None
            if key != self.hover:
                self.hover = key
                self.invalidate()
            return 0
        if msg == WM_LBUTTONDOWN:
            SetFocus(hwnd)
            x, y = xy(lp)
            self.click(*self.hit(x, y))
            return 0
        if msg == WM_LBUTTONDBLCLK:
            x, y = xy(lp)
            kind, data = self.hit(x, y)
            if kind == "row":
                self.open_item(self.items[data])
            return 0
        if msg == WM_RBUTTONUP:
            x, y = xy(lp)
            kind, data = self.hit(x, y)
            if kind == "row":
                if data not in self.sel:
                    self.sel = {data}
                self.item_menu(self.items[data])
            elif kind == "favnav":
                if a.popup(hwnd, [(1, "Remove from favorites"), (2, "Open")], TPM_RETURNCMD | TPM_RIGHTBUTTON) == 1:
                    self.toggle_fav(data)
                else:
                    self.go(data)
            elif kind in ("blank", "nav"):
                cmd = a.popup(hwnd, [(1, "Paste"), (2, "New folder"), (3, "Refresh"), None,
                                     (4, "Open command window here"),
                                     (5, "Details view"), (6, "Grid view")], TPM_RETURNCMD | TPM_RIGHTBUTTON)
                acts = {1: "paste", 2: "newdir", 3: "refresh", 4: "cmd", 5: "v_details", 6: "v_grid"}
                if cmd:
                    self.do(acts[cmd])
            self.invalidate()
            return 0
        if msg == WM_MOUSEWHEEL:
            delta = c_short((wp >> 16) & 0xFFFF).value
            W, H = self.client()
            if GetKeyState(0x11) & 0x8000 and a.cfg["explorer_view"] == "grid":
                self.do("g_plus" if delta > 0 else "g_minus")
                return 0
            self.scroll -= (delta // 120) * a.px(72)
            self.clamp_scroll(W, H)
            self.invalidate()
            return 0
        if msg == WM_CHAR and self.edit:
            ch = wp
            if ch == 13:
                self.end_edit(True)
            elif ch == 27:
                self.end_edit(False)
            elif ch == 8:
                self.edit_text = self.edit_text[:-1]
            elif ch >= 32:
                self.edit_text += chr(ch)
            if self.edit == "search":
                self.search = self.edit_text
                self.apply_filter()
            self.invalidate()
            return 0
        if msg == WM_KEYDOWN and not self.edit:
            if wp == 0x08:
                self.up()
            elif wp == 0x0D and self.sel:
                self.open_item(self.selected_items()[0])
            elif wp == 0x2E:
                self.do("delete")
            elif wp == 0x74:
                self.do("refresh")
            elif wp == 0x71:
                self.do("rename")
            elif wp in (0x25, 0x26, 0x27, 0x28) and self.items:
                W, H = self.client()
                cols = self.view_info(W, self.regions(W, H))[3]
                step = {0x25: -1, 0x27: 1, 0x26: -cols, 0x28: cols}[wp]
                cur = min(self.sel) if self.sel else -step
                self.sel = {max(0, min(len(self.items) - 1, cur + step))}
                self.invalidate()
            return 0
        if msg == WM_DESTROY:
            if self in a.explorers:
                a.explorers.remove(self)
            WINDOWS.pop(hwnd, None)
            return 0
        return DefWindowProcW(hwnd, msg, wp, lp)


# ==========================================================================
# Window preview panel, floating taskbar icon, custom title bars
# ==========================================================================
SC_MIN, SC_MAX, SC_RESTORE, SC_CLOSE = 0xF020, 0xF030, 0xF120, 0xF060
WM_NCLBUTTONDOWN = 0xA1


OWN_CLASSES = {"WinShellBar", "WinShellStart", "WinShellTitle", "WinShellFloat",
               "WinShellPreview", "WinShellHover", "WinShellDesktop"}


def window_occluded(hwnd):
    """True when another visible window covers part of this one (screen copies would be wrong)."""
    rc = RECT()
    if not GetWindowRect(hwnd, byref(rc)):
        return True
    h = GetWindow(hwnd, 3)
    while h:
        if IsWindowVisible(h) and not IsIconic(h):
            cls = get_class(h)
            if cls not in OWN_CLASSES and cls not in IGNORED_CLASSES:
                r2 = RECT()
                if GetWindowRect(h, byref(r2)) and r2.left < rc.right and r2.right > rc.left \
                        and r2.top < rc.bottom and r2.bottom > rc.top:
                    return True
        h = GetWindow(h, 3)
    return False


def capture_window(hwnd, tw, tht, allow_screen):
    """Snapshot of a window scaled into a tw x tht thumbnail (HBITMAP) or None."""
    rc = RECT()
    if IsIconic(hwnd) or not GetWindowRect(hwnd, byref(rc)):
        return None
    w, h = rc.right - rc.left, rc.bottom - rc.top
    if w < 8 or h < 8 or w > 4096 or h > 4096:
        return None
    hdc = GetDC(None)
    full = CreateCompatibleDC(hdc)
    fb = CreateCompatibleBitmap(hdc, w, h)
    old = SelectObject(full, fb)
    try:
        ok = bool(PrintWindow(hwnd, full, 0))
    except Exception:
        ok = False
    if ok:                                       # reject empty (all black) captures
        pts = [GetPixel(full, int(w * i / 6), int(h * j / 6))
               for i in range(1, 6) for j in range(1, 6)]
        ok = any(p not in (0, 0xFFFFFFFF) for p in pts)
    if not ok and allow_screen:                  # unobscured: copy straight from the screen
        BitBlt(full, 0, 0, w, h, hdc, rc.left, rc.top, SRCCOPY | 0x40000000)
        ok = True
    thumb = None
    if ok:
        thumb = CreateCompatibleBitmap(hdc, tw, tht)
        td = CreateCompatibleDC(hdc)
        to = SelectObject(td, thumb)
        fill(td, (0, 0, tw, tht), rgb(40, 40, 40))
        s = min(tw / w, tht / h)
        dw, dh = max(1, int(w * s)), max(1, int(h * s))
        SetStretchBltMode(td, 4)
        StretchBlt(td, (tw - dw) // 2, (tht - dh) // 2, dw, dh, full, 0, 0, w, h, SRCCOPY)
        SelectObject(td, to)
        DeleteDC(td)
    SelectObject(full, old)
    DeleteDC(full)
    DeleteObject(fb)
    ReleaseDC(None, hdc)
    return thumb


def pick_color(owner, initial):
    custom = (wt.DWORD * 16)()
    cc = CHOOSECOLORW()
    cc.lStructSize = sizeof(cc)
    cc.hwndOwner = owner
    cc.rgbResult = initial
    cc.lpCustColors = ctypes.cast(custom, POINTER(wt.DWORD))
    cc.Flags = 3                                 # CC_RGBINIT | CC_FULLOPEN
    return cc.rgbResult if ChooseColorW(byref(cc)) else None


class PreviewPanel(Window):
    """Open-window overview: live preview card per window with Go to / Close / Pin."""
    CLASS = "WinShellPreview"

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.cards = []
        self.visible = False
        self.hover = None
        self.closed_at = 0.0

    def thumb_size(self):
        tw = self.app.px(self.app.cfg["preview_width"])
        return tw, int(tw * 9 / 16)

    def dims(self):
        p = self.app.px
        tw, tht = self.thumb_size()
        return tw + p(16), tht + p(8) + p(8) + p(26) + p(34), p(8), p(46)

    def layout(self):
        cw, ch, gap, foot = self.dims()
        sw, _sh = screen_size()
        n = len(self.cards)
        cols = max(1, min(max(n, 1), (sw - gap) // (cw + gap)))
        rows = max(1, -(-n // cols))
        return cols, rows, cols * (cw + gap) + gap, rows * (ch + gap) + gap + foot

    def card_rect(self, i):
        cw, ch, gap, _f = self.dims()
        cols = self.layout()[0]
        x, y = gap + (i % cols) * (cw + gap), gap + (i // cols) * (ch + gap)
        return (x, y, x + cw, y + ch)

    def parts(self, i):
        p = self.app.px
        r = self.card_rect(i)
        tw, tht = self.thumb_size()
        thumb = (r[0] + p(8), r[1] + p(8), r[0] + p(8) + tw, r[1] + p(8) + tht)
        title = (r[0] + p(8), thumb[3] + p(2), r[2] - p(8), thumb[3] + p(26))
        by0, by1 = r[3] - p(34), r[3] - p(8)
        bw = (r[2] - r[0] - p(16) - 2 * p(4)) // 3
        btns = [("goto", (r[0] + p(8), by0, r[0] + p(8) + bw, by1)),
                ("close", (r[0] + p(12) + bw, by0, r[0] + p(12) + 2 * bw, by1)),
                ("pin", (r[0] + p(16) + 2 * bw, by0, r[0] + p(16) + 3 * bw, by1))]
        return thumb, title, btns

    def closeall_rect(self):
        p = self.app.px
        W, Hh = self.layout()[2:]
        return (W - p(8) - p(210), Hh - p(46) + p(7), W - p(8), Hh - p(7))

    def hit(self, x, y):
        if inside(self.closeall_rect(), x, y):
            return "closeall", None
        for i in range(len(self.cards)):
            for name, r in self.parts(i)[2]:
                if inside(r, x, y):
                    return name, i
            if inside(self.card_rect(i), x, y):
                return "goto", i
        return None, None

    def snapshot(self):
        a = self.app
        tw, tht = self.thumb_size()
        cards = []
        for e in a.bar.entries:
            for h in e.tasks:
                cards.append({"hwnd": h, "title": get_title(h) or e.title, "exe": e.path,
                              "key": e.key, "icon": e.hicon, "active": a.bar.is_active_hwnd(h),
                              "thumb": a.thumb(h, tw, tht, True), "pinned": e.pinned})
        cards.sort(key=lambda cd: not cd["active"])
        self.cards = cards[:12]

    def refresh(self):
        tw, tht = self.thumb_size()
        for cd in self.cards:
            cd["thumb"] = self.app.thumb(cd["hwnd"], tw, tht, True)
        self.invalidate()

    def geometry(self):
        a = self.app
        sw, sh = screen_size()
        W, Hh = self.layout()[2:]
        bx, by, bw, bh = a.bar_rect()
        x = max(0, min(sw - W, a.bar.close_rect[2] - W))
        y = by - Hh - 4 if a.cfg["position"] == "bottom" else by + bh + 4
        return x, max(0, y), W, Hh

    def toggle(self):
        if self.visible:
            self.close()
        elif time.time() - self.closed_at > 0.3:
            self.open()

    def open(self):
        self.app.hover_prev.hide()
        self.snapshot()
        x, y, W, Hh = self.geometry()
        if not self.hwnd:
            Window.register(self.CLASS)
            self.create_window(self.CLASS, "Windows", WS_POPUP,
                               WS_EX_TOPMOST | WS_EX_TOOLWINDOW, x, y, W, Hh)
        SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, W, Hh, 0)
        apply_glass(self.hwnd, self.app.cfg["glass"], self.app.cfg["glass_opacity"])
        self.visible = True
        ShowWindow(self.hwnd, 5)
        SetForegroundWindow(self.hwnd)
        if self.app.cfg["preview_live"]:             # live previews
            SetTimer(self.hwnd, 1, max(200, int(self.app.cfg["preview_refresh_ms"])), None)
        self.invalidate()
        self.app.bar.invalidate()

    def close(self):
        if self.visible:
            self.visible = False
            self.closed_at = time.time()
            KillTimer(self.hwnd, 1)
            ShowWindow(self.hwnd, 0)
            self.cards = []
            self.app.bar.invalidate()

    def reposition(self):
        x, y, W, Hh = self.geometry()
        SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, W, Hh, 0)
        self.invalidate()

    def goto(self, i):
        h = self.cards[i]["hwnd"]
        self.close()
        if IsIconic(h):
            ShowWindow(h, 9)
        SetForegroundWindow(h)

    def close_card(self, i):
        cd = self.cards.pop(i)
        PostMessageW(cd["hwnd"], WM_CLOSE, 0, 0)
        if self.cards:
            self.reposition()
        else:
            self.close()

    def toggle_pin(self, i):
        cd = self.cards[i]
        if cd["pinned"]:
            self.app.unpin_taskbar(cd["key"])
        else:
            self.app.pin_taskbar(cd["exe"])
        cd["pinned"] = not cd["pinned"]
        self.invalidate()

    def paint(self):
        ps = PAINTSTRUCT()
        hdc = BeginPaint(self.hwnd, byref(ps))
        try:
            W, Hh = self.layout()[2:]
            mem = CreateCompatibleDC(hdc)
            bmp = CreateCompatibleBitmap(hdc, W, Hh)
            old = SelectObject(mem, bmp)
            self.draw(mem, W, Hh)
            BitBlt(hdc, 0, 0, W, Hh, mem, 0, 0, SRCCOPY)
            SelectObject(mem, old)
            DeleteObject(bmp)
            DeleteDC(mem)
        finally:
            EndPaint(self.hwnd, byref(ps))

    def draw(self, hdc, W, Hh):
        a = self.app
        p = a.px
        th = a.theme()
        base = th["start_bg"]
        fill(hdc, (0, 0, W, Hh), base)
        if a.cfg["glass_blur_start"]:
            x, y = self.geometry()[:2]
            if a.paint_blur(hdc, W, Hh, x, y):
                alpha_rect(hdc, (0, 0, W, Hh), base, 165)
        frame(hdc, (0, 0, W, Hh), th["active"])
        SetBkMode(hdc, 1)
        old = SelectObject(hdc, a.font)
        txt = DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS | DT_NOPREFIX
        if not self.cards:
            text_out(hdc, "No open windows", (0, 0, W, Hh - p(46)), DT_CENTER | txt, th["dim"])
        for i, cd in enumerate(self.cards):
            r = self.card_rect(i)
            thumb, title, btns = self.parts(i)
            fill(hdc, r, th["hover"] if cd["active"] else th["rail"])
            if cd["active"]:
                frame(hdc, r, th["accent"], 2)
            if cd["thumb"]:
                src_dc = CreateCompatibleDC(hdc)
                so = SelectObject(src_dc, cd["thumb"])
                BitBlt(hdc, thumb[0], thumb[1], thumb[2] - thumb[0], thumb[3] - thumb[1],
                       src_dc, 0, 0, SRCCOPY)
                SelectObject(src_dc, so)
                DeleteDC(src_dc)
            else:
                fill(hdc, thumb, rgb(40, 40, 40))
                isz = p(40)
                draw_icon_or_letter(hdc, cd["icon"], (thumb[0] + thumb[2] - isz) // 2,
                                    (thumb[1] + thumb[3] - isz) // 2, isz, cd["title"])
            draw_icon_or_letter(hdc, cd["icon"], title[0], title[1] + p(4), 16, cd["title"])
            text_out(hdc, cd["title"], (title[0] + p(22), title[1], title[2], title[3]), txt, th["text"])
            for name, br in btns:
                label = {"goto": "Go to", "close": "Close", "pin": "Unpin" if cd["pinned"] else "Pin"}[name]
                col = th["active"]
                if self.hover == (name, i):
                    col = rgb(196, 43, 28) if name == "close" else th["accent"]
                fill(hdc, br, col)
                text_out(hdc, label, br, DT_CENTER | txt, rgb(255, 255, 255))
        cr = self.closeall_rect()
        fill(hdc, cr, rgb(232, 17, 35) if self.hover == ("closeall", None) else rgb(176, 30, 30))
        text_out(hdc, "Close all windows", cr, DT_CENTER | txt, rgb(255, 255, 255))
        text_out(hdc, "%d open window(s)" % len(self.cards), (p(12), Hh - p(46), W // 2, Hh), txt, th["dim"])
        SelectObject(hdc, old)

    def on_message(self, hwnd, msg, wp, lp):
        a = self.app
        if msg == WM_PAINT:
            self.paint()
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_TIMER:
            self.refresh()
            return 0
        if msg == WM_ACTIVATE:
            if (wp & 0xFFFF) == 0 and self.visible and a.menu_depth == 0:
                self.close()
            return 0
        if msg == WM_MOUSEMOVE:
            x, y = xy(lp)
            key = self.hit(x, y)
            key = None if key[0] is None else key
            if key != self.hover:
                self.hover = key
                self.invalidate()
            return 0
        if msg == WM_LBUTTONUP:
            x, y = xy(lp)
            kind, i = self.hit(x, y)
            if kind == "goto":
                self.goto(i)
            elif kind == "close":
                self.close_card(i)
            elif kind == "pin":
                self.toggle_pin(i)
            elif kind == "closeall":
                self.close()
                a.confirm_close_all(self.hwnd if self.hwnd else None)
            return 0
        return DefWindowProcW(hwnd, msg, wp, lp)


class HoverPreview(Window):
    """Windows 10 style live preview shown above a taskbar button on hover."""
    CLASS = "WinShellHover"

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.entry = None
        self.visible = False
        self.hover = None

    def sizes(self):
        p = self.app.px
        tw = p(self.app.cfg["preview_width"])
        tht = int(tw * 9 / 16)
        return tw, tht, tw + p(16), tht + p(8) + p(30) + p(8), p(6)

    def hwnds(self):
        return list(self.entry.tasks)[:8] if self.entry else []

    def layout(self):
        tw, tht, cw, ch, gap = self.sizes()
        sw, _sh = screen_size()
        n = max(1, len(self.hwnds()))
        cols = max(1, min(n, (sw - gap) // (cw + gap)))
        rows = -(-n // cols)
        return cols, cols * (cw + gap) + gap, rows * (ch + gap) + gap

    def card_rect(self, i):
        tw, tht, cw, ch, gap = self.sizes()
        cols = self.layout()[0]
        x, y = gap + (i % cols) * (cw + gap), gap + (i // cols) * (ch + gap)
        return (x, y, x + cw, y + ch)

    def parts(self, i):
        p = self.app.px
        r = self.card_rect(i)
        tw, tht = self.sizes()[:2]
        thumb = (r[0] + p(8), r[1] + p(8), r[0] + p(8) + tw, r[1] + p(8) + tht)
        title = (r[0] + p(8), thumb[3] + p(4), r[2] - p(34), thumb[3] + p(30))
        close = (r[2] - p(32), thumb[3] + p(4), r[2] - p(8), thumb[3] + p(28))
        return thumb, title, close

    def contains(self, x, y):
        if not self.visible or not self.hwnd:
            return False
        rc = RECT()
        GetWindowRect(self.hwnd, byref(rc))
        return rc.left <= x < rc.right and rc.top <= y < rc.bottom

    def show(self, entry):
        a = self.app
        self.entry = entry
        cols, W, Hh = self.layout()
        bx, by, bw, bh = a.bar_rect()
        cw_, ch_ = a.bar.client()
        rect = next((r for e, r in a.bar.layout(cw_, ch_)[1] if e is entry), (0, 0, 0, 0))
        sw, _sh = screen_size()
        x = max(0, min(sw - W, bx + (rect[0] + rect[2]) // 2 - W // 2))
        y = by - Hh - a.px(4) if a.cfg["position"] == "bottom" else by + bh + a.px(4)
        if not self.hwnd:
            Window.register(self.CLASS)
            self.create_window(self.CLASS, "", WS_POPUP,
                               WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, x, y, W, Hh)
        tw, tht = self.sizes()[:2]
        for h in self.hwnds():
            a.thumb(h, tw, tht, True)
        SetWindowPos(self.hwnd, HWND_TOPMOST, x, max(0, y), W, Hh, SWP_NOACTIVATE | 0x40)
        self.visible = True
        if a.cfg["preview_live"]:
            SetTimer(self.hwnd, 1, max(200, int(a.cfg["preview_refresh_ms"])), None)
        self.invalidate()

    def hide(self):
        if self.visible and self.hwnd:
            KillTimer(self.hwnd, 1)
            ShowWindow(self.hwnd, 0)
        self.visible = False
        self.entry = None

    def draw(self, hdc, W, Hh):
        a = self.app
        p = a.px
        th = a.theme()
        fill(hdc, (0, 0, W, Hh), th["start_bg"])
        frame(hdc, (0, 0, W, Hh), th["active"])
        SetBkMode(hdc, 1)
        old = SelectObject(hdc, a.font)
        tw, tht = self.sizes()[:2]
        for i, h in enumerate(self.hwnds()):
            r = self.card_rect(i)
            thumb, title, close = self.parts(i)
            active = a.bar.is_active_hwnd(h)
            fill(hdc, r, th["hover"] if (self.hover and self.hover[1] == i) or active else th["rail"])
            ent = a.thumbs.get(h)
            if ent and ent[0]:
                src_dc = CreateCompatibleDC(hdc)
                so = SelectObject(src_dc, ent[0])
                BitBlt(hdc, thumb[0], thumb[1], thumb[2] - thumb[0], thumb[3] - thumb[1],
                       src_dc, 0, 0, SRCCOPY)
                SelectObject(src_dc, so)
                DeleteDC(src_dc)
            else:
                fill(hdc, thumb, rgb(40, 40, 40))
                isz = p(40)
                draw_icon_or_letter(hdc, self.entry.hicon, (thumb[0] + thumb[2] - isz) // 2,
                                    (thumb[1] + thumb[3] - isz) // 2, isz, self.entry.title)
            draw_icon_or_letter(hdc, self.entry.hicon, title[0], title[1] + p(4), 16, self.entry.title)
            text_out(hdc, get_title(h) or self.entry.title, (title[0] + p(22), title[1], title[2], title[3]),
                     DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS | DT_NOPREFIX, th["text"])
            if self.hover == ("close", i):
                fill(hdc, close, rgb(232, 17, 35))
            draw_glyph(hdc, "close", close, rgb(255, 255, 255) if self.hover == ("close", i) else th["dim"],
                       size=p(12))
        SelectObject(hdc, old)

    def hit(self, x, y):
        for i in range(len(self.hwnds())):
            thumb, title, close = self.parts(i)
            if inside(close, x, y):
                return "close", i
            if inside(self.card_rect(i), x, y):
                return "card", i
        return None, None

    def on_message(self, hwnd, msg, wp, lp):
        a = self.app
        if msg == WM_PAINT:
            ps = PAINTSTRUCT()
            hdc = BeginPaint(hwnd, byref(ps))
            try:
                W, Hh = self.layout()[1:]
                mem = CreateCompatibleDC(hdc)
                bmp = CreateCompatibleBitmap(hdc, W, Hh)
                old = SelectObject(mem, bmp)
                self.draw(mem, W, Hh)
                BitBlt(hdc, 0, 0, W, Hh, mem, 0, 0, SRCCOPY)
                SelectObject(mem, old)
                DeleteObject(bmp)
                DeleteDC(mem)
            finally:
                EndPaint(hwnd, byref(ps))
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_MOUSEACTIVATE:
            return 3
        if msg == WM_TIMER:
            if not self.hwnds():
                self.hide()
                return 0
            tw, tht = self.sizes()[:2]
            for h in self.hwnds():
                a.thumb(h, tw, tht, True)
            self.invalidate()
            return 0
        if msg == WM_MOUSEMOVE:
            x, y = xy(lp)
            key = self.hit(x, y)
            key = None if key[0] is None else key
            if key != self.hover:
                self.hover = key
                self.invalidate()
            return 0
        if msg == WM_LBUTTONUP:
            x, y = xy(lp)
            kind, i = self.hit(x, y)
            hs = self.hwnds()
            if kind and i < len(hs):
                h = hs[i]
                if kind == "close":
                    PostMessageW(h, WM_CLOSE, 0, 0)
                else:
                    self.hide()
                    if IsIconic(h):
                        ShowWindow(h, 9)
                    SetForegroundWindow(h)
            return 0
        return DefWindowProcW(hwnd, msg, wp, lp)


class FloatIcon(Window):
    """Small round button shown in a screen corner while an app covers the taskbar."""
    CLASS = "WinShellFloat"

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.visible = False

    def geometry(self):
        sw, sh = screen_size()
        s, m = self.app.px(46), self.app.px(10)
        corner = self.app.cfg["float_corner"]
        x = m if "left" in corner else sw - s - m
        y = m if corner.startswith("top") else sh - s - m
        return x, y, s

    def show(self):
        x, y, s = self.geometry()
        if not self.hwnd:
            Window.register(self.CLASS)
            self.create_window(self.CLASS, "", WS_POPUP,
                               WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, x, y, s, s)
            SetWindowRgn(self.hwnd, CreateEllipticRgn(0, 0, s + 1, s + 1), True)
        SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, s, s, SWP_NOACTIVATE | 0x40)
        self.visible = True

    def hide(self):
        if self.hwnd and self.visible:
            ShowWindow(self.hwnd, 0)
            self.visible = False

    def on_message(self, hwnd, msg, wp, lp):
        a = self.app
        if msg == WM_PAINT:
            ps = PAINTSTRUCT()
            hdc = BeginPaint(hwnd, byref(ps))
            try:
                s = self.geometry()[2]
                th = a.theme()
                brush = CreateSolidBrush(th["accent"])
                pen = CreatePen(0, 2, rgb(255, 255, 255))
                ob, op = SelectObject(hdc, brush), SelectObject(hdc, pen)
                Ellipse(hdc, 1, 1, s - 1, s - 1)
                SelectObject(hdc, ob)
                SelectObject(hdc, op)
                DeleteObject(brush)
                DeleteObject(pen)
                icon = a.start_icon(int(s * 0.55))
                if icon:
                    DrawIconEx(hdc, (s - int(s * 0.55)) // 2, (s - int(s * 0.55)) // 2, icon,
                               int(s * 0.55), int(s * 0.55), 0, None, 3)
                else:
                    pane, gap = int(s * 0.17), max(1, int(s * 0.03))
                    x0 = (s - (2 * pane + gap)) // 2
                    for dx in (0, pane + gap):
                        for dy in (0, pane + gap):
                            fill(hdc, (x0 + dx, x0 + dy, x0 + dx + pane, x0 + dy + pane),
                                 rgb(255, 255, 255))
            finally:
                EndPaint(hwnd, byref(ps))
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_MOUSEACTIVATE:
            return 3
        if msg == WM_LBUTTONUP:
            a.bar.peek()
            return 0
        return DefWindowProcW(hwnd, msg, wp, lp)


THEMES_DIR = os.path.join(CONFIG_DIR, "Themes")
TB_ICON_NAMES = ("min", "max", "restore", "close", "snap", "shade")
TB_THEMES = {
    "windows10": {"bg": (255, 255, 255), "ibg": (255, 255, 255), "fg": (0, 0, 0), "ifg": (150, 150, 150),
                  "btn": "flat", "side": "right", "hover": (229, 229, 229), "close_hover": (232, 17, 35),
                  "glyph": (0, 0, 0), "align": "left"},
    "windows10_dark": {"bg": (32, 32, 32), "ibg": (43, 43, 43), "fg": (255, 255, 255), "ifg": (150, 150, 150),
                       "btn": "flat", "side": "right", "hover": (62, 62, 62), "close_hover": (232, 17, 35),
                       "glyph": (255, 255, 255), "align": "left"},
    "windows7": {"bg": (185, 209, 234), "bg2": (214, 228, 243), "ibg": (208, 220, 234), "ibg2": (228, 235, 244),
                 "fg": (0, 0, 0), "ifg": (90, 90, 90), "btn": "aero", "side": "right", "btn_bg": (222, 232, 244),
                 "close_bg": (199, 80, 80), "glyph": (40, 50, 70), "hover": (240, 246, 252), "align": "left"},
    "windows8": {"bg": (47, 129, 201), "ibg": (200, 215, 230), "fg": (255, 255, 255), "ifg": (90, 100, 110),
                 "btn": "flat", "side": "right", "hover": (70, 150, 220), "close_hover": (199, 80, 80),
                 "glyph": (255, 255, 255), "align": "left"},
    "windowsxp": {"bg": (0, 84, 227), "bg2": (61, 149, 255), "ibg": (122, 150, 223), "ibg2": (160, 185, 235),
                  "fg": (255, 255, 255), "ifg": (216, 228, 248), "btn": "box", "side": "right",
                  "btn_bg": (52, 114, 232), "close_bg": (224, 72, 38), "glyph": (255, 255, 255),
                  "hover": (90, 150, 250), "align": "left"},
    "windows95": {"bg": (0, 0, 128), "bg2": (16, 132, 208), "ibg": (128, 128, 128), "ibg2": (181, 181, 181),
                  "fg": (255, 255, 255), "ifg": (212, 208, 200), "btn": "box", "side": "right",
                  "btn_bg": (192, 192, 192), "close_bg": (192, 192, 192), "glyph": (0, 0, 0),
                  "hover": (210, 210, 210), "align": "left"},
    "xfce": {"bg": (232, 232, 232), "bg2": (206, 206, 206), "ibg": (240, 240, 240), "ibg2": (224, 224, 224),
             "fg": (50, 50, 50), "ifg": (130, 130, 130), "btn": "flat", "side": "right", "hover": (200, 200, 200),
             "close_hover": (215, 80, 70), "glyph": (60, 60, 60), "align": "left"},
    "ubuntu": {"bg": (60, 59, 55), "bg2": (51, 50, 47), "ibg": (70, 69, 65), "ibg2": (64, 63, 59),
               "fg": (223, 219, 210), "ifg": (150, 146, 140), "btn": "circle", "side": "right", "bw": 1.0,
               "btn_bg": (85, 84, 80), "close_bg": (233, 84, 32), "glyph": (223, 219, 210),
               "hover": (110, 109, 104), "align": "left"},
    "mint": {"bg": (239, 239, 239), "ibg": (245, 245, 245), "fg": (60, 60, 60), "ifg": (140, 140, 140),
             "btn": "circle", "side": "right", "bw": 1.0, "btn_bg": (222, 222, 222), "close_bg": (222, 222, 222),
             "glyph": (80, 80, 80), "hover": (135, 168, 52), "close_hover": (200, 60, 60), "align": "left"},
    "gnome": {"bg": (235, 235, 235), "bg2": (222, 222, 222), "ibg": (246, 245, 244), "ibg2": (236, 235, 233),
              "fg": (46, 52, 54), "ifg": (140, 140, 140), "btn": "circle", "side": "right", "bw": 1.0,
              "btn_bg": (205, 205, 205), "close_bg": (205, 205, 205), "glyph": (46, 52, 54),
              "hover": (190, 190, 190), "close_hover": (220, 90, 90), "align": "center"},
    "kde": {"bg": (239, 240, 241), "ibg": (247, 247, 247), "fg": (35, 38, 41), "ifg": (150, 150, 150),
            "btn": "flat", "side": "right", "hover": (61, 174, 233), "close_hover": (218, 68, 83),
            "glyph": (35, 38, 41), "align": "left"},
    "macos": {"bg": (236, 236, 236), "bg2": (222, 222, 222), "ibg": (246, 246, 246), "ibg2": (238, 238, 238),
              "fg": (60, 60, 60), "ifg": (160, 160, 160), "btn": "mac", "side": "left", "bw": 0.9,
              "glyph": (60, 60, 60), "align": "center"},
}
_TB_COLOR_KEYS = ("bg", "bg2", "ibg", "ibg2", "fg", "ifg", "glyph", "hover", "close_hover", "btn_bg", "close_bg")


def _tb_col(v):
    if isinstance(v, str):
        return split_rgb(hex_color(v, 0))
    return tuple(int(x) for x in v[:3])


def load_custom_tb_themes():
    """Custom title bar themes: Themes\\<name>\\theme.json (+ icon files next to it)."""
    try:
        for entry in os.scandir(THEMES_DIR):
            jf = os.path.join(entry.path, "theme.json") if entry.is_dir() else (
                entry.path if entry.name.lower().endswith(".json") else None)
            if not jf or not os.path.exists(jf):
                continue
            with open(jf, "r", encoding="utf-8") as f:
                data = json.load(f)
            name = entry.name if entry.is_dir() else os.path.splitext(entry.name)[0]
            th = dict(TB_THEMES.get(data.get("base", "windows10"), TB_THEMES["windows10"]))
            for k, v in data.items():
                if k in _TB_COLOR_KEYS:
                    th[k] = _tb_col(v)
                elif k == "icons" and isinstance(v, dict):
                    th["icons"] = {n: os.path.join(os.path.dirname(jf), fn) for n, fn in v.items()}
                elif k in ("btn", "side", "align", "bw"):
                    th[k] = v
            TB_THEMES[name] = th
    except OSError:
        pass


def vgrad(hdc, W, Hh, c1, c2):
    for yy in range(Hh):
        fill(hdc, (0, yy, W, yy + 1), mix(c1, c2, yy / max(1, Hh - 1)))


class TitleBar(Window):
    """Our own title bar drawn over a Wine app's caption: themes, icons, snap and shade."""
    CLASS = "WinShellTitle"

    def __init__(self, app, target):
        super().__init__()
        self.app, self.target = app, target
        self.hover = self.pressed = None
        self.tracking = False
        self.active = self.zoomed = False
        self.sig = self.last = None
        self.is_top = False
        Window.register(self.CLASS, 0x8)
        self.create_window(self.CLASS, "", WS_POPUP, WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, 0, 0, 10, 10)

    def metrics(self):
        cap = max(16, GetSystemMetrics(4) + int(self.app.cfg["tb_height_adjust"]))
        thick = GetWindowLongW(self.target, -16) & 0x40000        # WS_THICKFRAME
        inset = (GetSystemMetrics(32) + GetSystemMetrics(92)) if thick else GetSystemMetrics(7)
        return cap, inset

    def geometry(self):
        t = self.target
        rc = RECT()
        if not IsWindow(t) or not IsWindowVisible(t) or IsIconic(t) or not GetWindowRect(t, byref(rc)):
            return None
        cap, inset = self.metrics()
        x, y = rc.left + inset, rc.top + inset + int(self.app.cfg["tb_offset_y"])
        w = rc.right - rc.left - 2 * inset
        return (x, y, w, cap) if w >= 80 else None

    def update(self, active=None, force=False):
        t, a = self.target, self.app
        if active is None:
            fg = GetForegroundWindow()
            active = bool(fg) and (fg == t or GetAncestor(fg, GA_ROOTOWNER) == t)
        geo = self.geometry()
        if not geo:
            if self.last is not None:
                ShowWindow(self.hwnd, 0)
                self.last = None
            return False
        x, y, w, cap = geo
        flags = SWP_NOACTIVATE | 0x40                             # + SWP_SHOWWINDOW
        if active:
            insert = HWND_TOPMOST                                 # active window: always above it
        else:
            if self.is_top:
                SetWindowPos(self.hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                self.is_top = False
            topmost = bool(GetWindowLongW(t, GWL_EXSTYLE) & WS_EX_TOPMOST)
            prev = GetWindow(t, 3)                                # GW_HWNDPREV
            while prev and not topmost and (GetWindowLongW(prev, GWL_EXSTYLE) & WS_EX_TOPMOST):
                prev = GetWindow(prev, 3)
            insert = prev or 0
            if prev == self.hwnd:
                flags |= SWP_NOZORDER
        key = (x, y, w, cap, insert)
        if force or key != self.last:
            SetWindowPos(self.hwnd, 0 if flags & SWP_NOZORDER else insert, x, y, w, cap, flags)
            self.last = key
            bx, by, bw, bh = a.bar_rect()
            if active and y < by + bh and y + cap > by:           # touching the taskbar: bar stays on top
                a.bar.raise_bar()
        self.is_top = bool(active)
        zoomed = bool(IsZoomed(t))
        sig = (get_title(t), active, zoomed, w, cap, a.titlebar_sig(), self.target in a.shade_state)
        if sig != self.sig:
            self.sig, self.active, self.zoomed = sig, active, zoomed
            self.invalidate()
        return True

    def buttons(self, th):
        c = self.app.cfg
        extra = (["shade"] if c["tb_show_shade"] else []) + (["snap"] if c["tb_show_snap"] else [])
        if th.get("side") == "left":
            return ["close", "min", "max"] + extra[::-1]
        return extra + ["min", "max", "close"]

    def btn_rects(self, W, Hh, th):
        names = self.buttons(th)
        bw = int(Hh * th.get("bw", 1.4))
        rects = {}
        x = self.app.px(6) if th.get("side") == "left" else W - bw * len(names)
        for n in names:
            rects[n] = (x, 0, x + bw, Hh)
            x += bw
        return rects

    def hit(self, x, y):
        rc = RECT()
        GetClientRect(self.hwnd, byref(rc))
        for name, r in self.btn_rects(rc.right, rc.bottom, self.app.tb_theme()).items():
            if inside(r, x, y):
                return name
        return "title"

    def paint(self):
        ps = PAINTSTRUCT()
        hdc = BeginPaint(self.hwnd, byref(ps))
        try:
            rc = RECT()
            GetClientRect(self.hwnd, byref(rc))
            W, Hh = rc.right, rc.bottom
            if W > 0 and Hh > 0:
                mem = CreateCompatibleDC(hdc)
                bmp = CreateCompatibleBitmap(hdc, W, Hh)
                old = SelectObject(mem, bmp)
                self.draw(mem, W, Hh)
                BitBlt(hdc, 0, 0, W, Hh, mem, 0, 0, SRCCOPY)
                SelectObject(mem, old)
                DeleteObject(bmp)
                DeleteDC(mem)
        finally:
            EndPaint(self.hwnd, byref(ps))

    def draw_button(self, hdc, name, r, th, hover, fg):
        a = self.app
        Hh = r[3] - r[1]
        style = th.get("btn", "flat")
        glyph = rgb(*th.get("glyph", (0, 0, 0)))
        cx, cy = (r[0] + r[2]) // 2, (r[1] + r[3]) // 2
        icon_key = "restore" if (name == "max" and self.zoomed) else name
        if style == "flat":
            if hover:
                if name == "close":
                    fill(hdc, r, rgb(*th.get("close_hover", (232, 17, 35))))
                    glyph = rgb(255, 255, 255)
                else:
                    fill(hdc, r, rgb(*th.get("hover", (229, 229, 229))))
        elif style in ("aero", "box"):
            face = rgb(*(th.get("close_bg") if name == "close" else th.get("btn_bg", (220, 220, 220))))
            if hover:
                face = mix(face, rgb(255, 255, 255), 0.3)
            box = (r[0] + 2, r[1] + 3, r[2] - 2, r[3] - 3)
            fill(hdc, box, face)
            frame(hdc, box, rgb(90, 110, 140) if style == "aero" else rgb(255, 255, 255) if sum(split_rgb(face)) > 450 else rgb(20, 40, 120))
            if name == "close" and style == "aero":
                glyph = rgb(255, 255, 255)
        elif style in ("circle", "mac"):
            d = max(8, int(Hh * (0.5 if style == "mac" else 0.62)))
            if style == "mac":
                col = {"close": rgb(255, 95, 87), "min": rgb(255, 189, 46)}.get(name, rgb(39, 201, 63))
                if name in ("snap", "shade"):
                    col = rgb(120, 140, 220)
            else:
                col = rgb(*(th.get("close_bg") if name == "close" else th.get("btn_bg", (200, 200, 200))))
            if hover and style == "circle":
                col = rgb(*th.get("close_hover" if name == "close" else "hover", th.get("hover", (180, 180, 180))))
            with Gfx(hdc) as g:
                if g.ok:
                    g.fillc(col)
                    g.fill_ellipse(cx - d / 2.0, cy - d / 2.0, d, d)
                else:
                    fill(hdc, (cx - d // 2, cy - d // 2, cx + d // 2, cy + d // 2), col)
            if style == "mac":
                if not hover:
                    return
                glyph = rgb(70, 30, 20)
        path = th["icons"].get(icon_key)
        size = max(10, int(Hh * 0.5))
        if path and os.path.exists(path):
            ic = load_icon_file(path, size)
            if ic:
                DrawIconEx(hdc, cx - size // 2, cy - size // 2, ic, size, size, 0, None, 3)
                return
        gname = {"min": "min", "max": "restore" if self.zoomed else "max", "close": "close",
                 "snap": "snap_right" if a.snap_state.get(self.target, ("",))[0] == "left" else "snap_left",
                 "shade": "unshade" if self.target in a.shade_state else "shade"}[name]
        draw_glyph(hdc, gname, r, glyph, size=int(Hh * (0.36 if style == "mac" else 0.46)))

    def draw(self, hdc, W, Hh):
        a, c = self.app, self.app.cfg
        th = a.tb_theme()
        act = self.active
        bg = rgb(*th["bg"]) if act else rgb(*th.get("ibg", th["bg"]))
        bg2 = th.get("bg2") if act else th.get("ibg2", th.get("bg2"))
        fg = rgb(*th["fg"]) if act else rgb(*th.get("ifg", th["fg"]))
        drawn = False
        if c["glass_blur_title"]:
            rc = RECT()
            GetWindowRect(self.hwnd, byref(rc))
            if a.paint_blur(hdc, W, Hh, rc.left, rc.top):
                alpha_rect(hdc, (0, 0, W, Hh), bg, 190)
                drawn = True
        if not drawn:
            if bg2:
                vgrad(hdc, W, Hh, bg, rgb(*bg2))
            else:
                fill(hdc, (0, 0, W, Hh), bg)
        SetBkMode(hdc, 1)
        old = SelectObject(hdc, a.font)
        rects = self.btn_rects(W, Hh, th)
        left_side = th.get("side") == "left"
        pad = a.px(8)
        x0 = (max(r[2] for r in rects.values()) + pad) if left_side else pad
        x1 = W - pad if left_side else min(r[0] for r in rects.values()) - pad
        if c["tb_show_icon"]:
            exe = a.bar.win_exe.get(self.target, "")
            icon = ICONS.window_icon(self.target, exe)
            isz = min(16, Hh - 4)
            draw_icon_or_letter(hdc, icon, x0, (Hh - isz) // 2, isz, get_title(self.target) or "?")
            x0 += isz + a.px(8)
        title, exe = get_title(self.target), a.bar.win_exe.get(self.target, "")
        appname = display_name(exe) if exe else title
        mode = c["tb_text"]
        label = title if mode == "title" else appname if mode == "app" else (
            appname if appname.lower() == title.lower() or not title else "%s - %s" % (appname, title))
        align = th.get("align", "left") if c["tb_align"] == "theme" else c["tb_align"]
        flags = DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS | DT_NOPREFIX | (DT_CENTER if align == "center" else 0)
        text_out(hdc, label, (x0, 0, x1, Hh), flags, fg)
        for name, r in rects.items():
            self.draw_button(hdc, name, r, th, self.hover == name, fg)
        SelectObject(hdc, old)

    def send_move(self):
        pt = wt.POINT()
        GetCursorPos(byref(pt))
        ReleaseCapture()
        SetForegroundWindow(self.target)
        PostMessageW(self.target, WM_NCLBUTTONDOWN, 2, ((pt.y & 0xFFFF) << 16) | (pt.x & 0xFFFF))

    def command(self, name):
        t, a = self.target, self.app
        if name == "close":
            PostMessageW(t, WM_SYSCOMMAND, SC_CLOSE, 0)
        elif name == "min":
            PostMessageW(t, WM_SYSCOMMAND, SC_MIN, 0)
        elif name == "max":
            SetForegroundWindow(t)
            PostMessageW(t, WM_SYSCOMMAND, SC_RESTORE if IsZoomed(t) else SC_MAX, 0)
        elif name == "snap":
            a.snap_window(t)
        elif name == "shade":
            cap, inset = self.metrics()
            a.shade_window(t, cap, inset)
        self.update(force=True)

    def on_message(self, hwnd, msg, wp, lp):
        if msg == WM_PAINT:
            self.paint()
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_MOUSEACTIVATE:
            return 3
        if msg == WM_MOUSEMOVE:
            x, y = xy(lp)
            h = self.hit(x, y)
            h = h if h != "title" else None
            if not self.tracking:
                TrackMouseEvent(byref(TRACKMOUSEEVENT(sizeof(TRACKMOUSEEVENT), 2, hwnd, 0)))
                self.tracking = True
            if h != self.hover:
                self.hover = h
                self.invalidate()
            return 0
        if msg == WM_MOUSELEAVE:
            self.tracking, self.hover = False, None
            self.invalidate()
            return 0
        if msg == WM_LBUTTONDOWN:
            x, y = xy(lp)
            self.pressed = self.hit(x, y)
            if self.pressed == "title":
                self.send_move()
            return 0
        if msg == WM_LBUTTONUP:
            x, y = xy(lp)
            h = self.hit(x, y)
            if h == self.pressed and h != "title":
                self.command(h)
            self.pressed = None
            return 0
        if msg == WM_LBUTTONDBLCLK:
            x, y = xy(lp)
            if self.hit(x, y) == "title":
                self.command("max")
            return 0
        if msg == WM_RBUTTONUP:
            t = self.target
            cmd = self.app.popup(hwnd, [(1, "Restore"), (2, "Minimize"), (3, "Maximize"),
                                        (5, "Snap to half screen"), (6, "Roll up / down"),
                                        None, (4, "Close")], TPM_RETURNCMD | TPM_RIGHTBUTTON)
            if cmd in (1, 2, 3, 4):
                PostMessageW(t, WM_SYSCOMMAND, {1: SC_RESTORE, 2: SC_MIN, 3: SC_MAX, 4: SC_CLOSE}[cmd], 0)
            elif cmd == 5:
                self.command("snap")
            elif cmd == 6:
                self.command("shade")
            return 0
        return DefWindowProcW(hwnd, msg, wp, lp)


# ==========================================================================
# Settings window (standard Win32 controls, live apply)
# ==========================================================================
COLOR_PRESETS = [
    ("Default", ""), ("Black", "#000000"), ("Charcoal", "#202020"), ("Graphite", "#3B3B3B"),
    ("Slate", "#2D3E50"), ("Navy", "#0B2447"), ("Blue", "#0078D7"), ("Sky", "#00B4F0"),
    ("Teal", "#008272"), ("Green", "#107C10"), ("Lime", "#8CBD18"), ("Yellow", "#FFB900"),
    ("Orange", "#D83B01"), ("Red", "#C42B1C"), ("Pink", "#E3008C"), ("Purple", "#5C2D91"),
    ("Brown", "#6B4F3A"), ("Gray", "#767676"), ("Silver", "#C8C8C8"), ("White", "#FFFFFF")]

PAGE_ICONS = {
    "Personalization": "palette", "Colors": "palette", "Window look": "window", "Title bar": "window",
    "Title bar icons": "image", "Taskbar": "taskbar", "Previews": "eye", "Taskbar apps": "apps",
    "Startup apps": "play", "User": "user", "Start menu": "start", "Start tiles": "grid",
    "Start menu apps": "apps", "Hidden start apps": "eye", "Starred apps": "star",
    "Date & time": "clock", "File Explorer": "folder", "Favorites": "star_fill",
    "Open with apps": "open_with", "Desktop": "monitor", "Desktop shortcuts": "pin"}

PAGES = [
    ("Personalization", [
        ("theme", "choice", "Theme", "@ui_themes"),
        ("glass", "bool", "Glass effect (translucent bars + gloss)"),
        ("glass_blur_bar", "bool", "Glass blur: taskbar"),
        ("glass_blur_start", "bool", "Glass blur: Start menu and panels"),
        ("glass_blur_title", "bool", "Glass blur: title bars"),
        ("glass_blur_window", "bool", "Glass blur: File Explorer window"),
        ("glass_opacity", "int", "Glass opacity % (30-100)"),
        ("start_icon", "file", "Start button icon (.ico or .png)"),
        ("font", "str", "Font name"),
        ("font_size", "int", "Font size"),
        ("scale", "float", "UI scale (1.0 normal, 1.5 touch friendly)"),
    ]),
    ("Colors", [
        ("bar_color", "color", "Taskbar color"),
        ("accent", "color", "Accent color"),
    ]),
    ("Window look", [
        ("window_look", "choice", "Window style (native frame)",
         ["default", "windows10_light", "windows10_dark"]),
        ("look_title_accent", "bool", "Native title bars use the accent color"),
        ("look_caption_height", "int", "Native title bar height (px, 16-48)"),
        ("look_scrollbar_width", "int", "Scroll bar width (px, 8-40)"),
        ("theme_file", "file", "Windows-style theme (.msstyles, optional)"),
    ]),
    ("Title bar", [
        ("custom_titlebar", "bool", "Custom title bars (own buttons + icons)"),
        ("tb_theme", "choice", "Title bar theme", "@tb_themes"),
        ("tb_use_theme_colors", "bool", "Use the theme's colors"),
        ("look_title_color", "color", "Title bar color (when theme colors are off)"),
        ("tb_align", "choice", "Title text alignment", ["theme", "left", "center"]),
        ("tb_text", "choice", "Title text", ["title", "app", "app_and_title"]),
        ("tb_show_icon", "bool", "Show the app icon"),
        ("tb_show_snap", "bool", "Snap-to-half-screen button"),
        ("tb_show_shade", "bool", "Roll-up (shade) button"),
        ("tb_height_adjust", "int", "Title bar height adjust (px)"),
        ("tb_offset_y", "int", "Title bar vertical offset (px)"),
    ]),
    ("Title bar icons", [
        ("tb_icon_min", "file", "Minimize icon (.ico/.png)"),
        ("tb_icon_max", "file", "Maximize icon"),
        ("tb_icon_restore", "file", "Restore icon"),
        ("tb_icon_close", "file", "Close icon"),
        ("tb_icon_snap", "file", "Snap icon"),
        ("tb_icon_shade", "file", "Roll-up icon"),
        ("tb_new_theme_name", "str", "New theme name"),
        ("save_theme", "action", "Save current title bar as a new theme"),
    ]),
    ("Taskbar", [
        ("position", "choice", "Position", ["bottom", "top"]),
        ("alignment", "choice", "Alignment", ["left", "center", "right"]),
        ("height", "int", "Height (px)"),
        ("icon_size", "int", "Icon size (px)"),
        ("show_titles", "bool", "Show titles on running (unpinned) apps"),
        ("icon_accent", "bool", "Underline color adapted from app icon"),
        ("fs_mode", "choice", "Taskbar over full-screen apps",
         ["keep_visible", "bar_over_app", "floating_icon", "hide_bar"]),
        ("fs_trigger", "choice", "Applies to", ["fullscreen", "maximized", "both"]),
        ("float_corner", "choice", "Floating icon corner",
         ["bottom-right", "bottom-left", "top-right", "top-left"]),
        ("clock_format", "str", "Clock format (strftime, \\n = new line)"),
        ("hide_wine_taskbar", "bool", "Hide Wine's built-in taskbar"),
        ("autostart_delay", "int", "Startup apps delay (seconds)"),
    ]),
    ("Previews", [
        ("preview_on_hover", "bool", "Show a preview when hovering taskbar apps"),
        ("preview_live", "bool", "Live (refreshing) previews"),
        ("preview_width", "int", "Preview width (px, 120-480)"),
        ("preview_refresh_ms", "int", "Refresh interval (ms)"),
        ("preview_hover_delay", "int", "Hover delay (ms)"),
    ]),
    ("Taskbar apps", "list:pinned"),
    ("Startup apps", "list:autostart"),
    ("User", [
        ("user_name", "str", "User name"),
        ("user_photo", "file", "Profile picture"),
    ]),
    ("Start menu", [
        ("start_collapsed", "bool", "Collapse the app list (tiles only)"),
        ("tile_random_colors", "bool", "Different color for every tile"),
        ("tile_shuffle", "bool", "Tiles swap places randomly"),
        ("tile_shuffle_seconds", "int", "Shuffle every (seconds)"),
    ]),
    ("Start tiles", "list:start_pins"),
    ("Start menu apps", "list:start_extra"),
    ("Hidden start apps", "list:start_hidden"),
    ("Starred apps", "list:start_starred"),
    ("Date & time", "special:clock"),
    ("File Explorer", [
        ("use_winshell_explorer", "bool", "Use WinShell File Explorer for folders"),
        ("explorer_show_hidden", "bool", "Show hidden files"),
        ("explorer_view", "choice", "Default view", ["details", "grid"]),
        ("explorer_grid_size", "int", "Grid icon size (px, 64-200)"),
    ]),
    ("Favorites", "list:bookmarks"),
    ("Open with apps", "list:open_with_apps"),
    ("Desktop", [
        ("full_desktop", "bool", "Full desktop mode (wallpaper + movable icons)"),
        ("grid_size", "int", "Icon grid size (48-240 px)"),
        ("grid_snap", "bool", "Snap icons to grid"),
        ("show_desktop_icons", "bool", "Show desktop icons"),
        ("wallpaper", "file", "Wallpaper image"),
        ("wallpaper_mode", "choice", "Wallpaper fit",
         ["fill", "fit", "stretch", "center", "tile"]),
        ("desktop_color", "color", "Desktop background color"),
    ]),
    ("Desktop shortcuts", "list:desktop_extra"),
]
LIMITS = {"height": (24, 120), "icon_size": (12, 64), "font_size": (8, 32),
          "grid_size": (48, 240), "glass_opacity": (30, 100), "scale": (0.5, 3.0),
          "look_caption_height": (16, 48), "look_scrollbar_width": (8, 40),
          "tb_height_adjust": (-10, 30), "tb_offset_y": (-20, 20), "autostart_delay": (0, 120),
          "preview_width": (120, 480), "preview_refresh_ms": (200, 3000),
          "preview_hover_delay": (0, 2000), "tile_shuffle_seconds": (2, 120),
          "explorer_grid_size": (64, 200)}


def make_child(cls, text, style, x, y, w, h, cid, parent, ex=0):
    hwnd = CreateWindowExW(ex, cls, text, WS_CHILD | WS_VISIBLE | style, x, y, w, h,
                           parent, cid, GetModuleHandleW(None), None)
    if hwnd:
        SendMessageW(hwnd, WM_SETFONT, GetStockObject(17) or 0, 1)
    return hwnd


class Settings(Window):
    CLASS = "WinShellSettings"

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.children = []
        self.ctrls = {}
        self.next_id = 1000
        self.lb = None
        self.list_hwnd = None
        self.page = 0
        self.rebuilding = False
        self.swatches = {}
        self.brushes = {}

    def show(self, page=None):
        if not self.hwnd:
            self.build()
        if page is not None:
            names = [p[0] for p in PAGES]
            if page in names:
                SendMessageW(self.lb, 0x186, names.index(page), 0)
                self.select_page(names.index(page))
        ShowWindow(self.hwnd, 9)
        SetForegroundWindow(self.hwnd)

    def build(self):
        Window.register(self.CLASS, 0, 16)         # COLOR_BTNFACE + 1
        sw, sh = screen_size()
        w, h = min(820, sw - 20), min(640, sh - 40)
        self.create_window(self.CLASS, "WinShell Settings",
                           WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_VISIBLE,
                           0, max(0, (sw - w) // 2), max(0, (sh - h) // 2 - 20), w, h)
        self.lb = make_child("LISTBOX", "", 0x1 | 0x10 | 0x40 | WS_VSCROLL, 10, 10, 195, h - 60,
                             100, self.hwnd)
        for name, _spec in PAGES:
            SendMessageS(self.lb, 0x180, 0, name)
        SendMessageW(self.lb, 0x186, 0, 0)
        self.select_page(0)

    def clear(self):
        self.rebuilding = True
        for ch in self.children:
            DestroyWindow(ch)
        self.children, self.ctrls, self.list_hwnd, self.swatches = [], {}, None, {}
        self.rebuilding = False

    def add(self, cls, text, style, x, y, w, h, cid=0, ex=0):
        hwnd = make_child(cls, text, style, x, y, w, h, cid, self.hwnd, ex)
        if hwnd and self.app.font:
            SendMessageW(hwnd, WM_SETFONT, self.app.font, 1)
        self.children.append(hwnd)
        return hwnd

    def brush(self, color):
        if color not in self.brushes:
            self.brushes[color] = CreateSolidBrush(color)
        return self.brushes[color]

    @staticmethod
    def resolve_opts(opts):
        if opts == "@ui_themes":
            return list(UI_THEMES)
        if opts == "@tb_themes":
            return list(TB_THEMES)
        return opts

    def select_page(self, index):
        self.page = index
        self.clear()
        self.next_id = 1000
        name, spec = PAGES[index]
        x0, y = 225, 14
        hh = self.add("STATIC", name, 0, x0, y, 540, 30)
        SendMessageW(hh, WM_SETFONT, self.app.font_title or self.app.font or 0, 1)
        y += 44
        if isinstance(spec, str):
            kind, key = spec.split(":")
            if kind == "special":
                self.build_clock_page(x0, y)
            else:
                self.build_list_page(key, x0, y)
            return
        for key, kind, label, *extra in spec:
            cid = self.next_id
            self.next_id += 1
            val = self.app.cfg.get(key)
            if kind == "bool":
                h = self.add("BUTTON", label, 0x3 | WS_TABSTOP, x0, y, 560, 24, cid)
                SendMessageW(h, 0xF1, 1 if val else 0, 0)
            elif kind == "choice":
                self.add("STATIC", label, 0, x0, y + 4, 250, 22)
                h = self.add("COMBOBOX", "", 0x3 | WS_VSCROLL | WS_TABSTOP, x0 + 260, y,
                             200, 200, cid)
                extra = [self.resolve_opts(extra[0])]
                for opt in extra[0]:
                    SendMessageS(h, 0x143, 0, opt)
                if val in extra[0]:
                    SendMessageW(h, 0x14E, extra[0].index(val), 0)
            elif kind == "action":
                h = self.add("BUTTON", label, WS_TABSTOP, x0, y, 340, 28, cid)
            elif kind == "color":
                self.add("STATIC", label, 0, x0, y + 4, 250, 22)
                h = self.add("EDIT", str(val), 0x80 | WS_TABSTOP, x0 + 260, y, 120, 24, cid,
                             WS_EX_CLIENTEDGE)
                self.ctrls[cid + 7000] = (key, "pickcolor", h, None)
                self.add("BUTTON", "Custom...", WS_TABSTOP, x0 + 390, y, 90, 24, cid + 7000)
                for i, (nm, hx) in enumerate(COLOR_PRESETS):
                    sid = self.next_id
                    self.next_id += 1
                    self.swatches[sid] = (key, hx)
                    self.add("BUTTON", "", 0xB | WS_TABSTOP, x0 + (i % 10) * 30,
                             y + 32 + (i // 10) * 30, 26, 26, sid)
                y += 62
            else:
                self.add("STATIC", label, 0, x0, y + 4, 250, 22)
                shown = str(val).replace("\\n", "\\\\n")
                h = self.add("EDIT", shown, 0x80 | WS_TABSTOP, x0 + 260, y, 230, 24, cid,
                             WS_EX_CLIENTEDGE)
                if kind == "file":
                    self.ctrls[cid + 5000] = (key, "browse", h, None)
                    self.add("BUTTON", "Browse...", WS_TABSTOP, x0 + 498, y, 80, 24, cid + 5000)
            self.ctrls[cid] = (key, kind, h, extra[0] if extra else None)
            y += 32
        self.add("BUTTON", "Apply", WS_TABSTOP, x0 + 498, y + 6, 80, 28, 900)

    def build_clock_page(self, x, y):
        t = time.localtime(time.time() + float(self.app.cfg.get("clock_offset", 0) or 0))
        self.add("STATIC", "Date (YYYY-MM-DD)", 0, x, y + 4, 250, 22)
        self.clock_date = self.add("EDIT", time.strftime("%Y-%m-%d", t), 0x80 | WS_TABSTOP,
                                   x + 260, y, 160, 24, 950, WS_EX_CLIENTEDGE)
        self.add("STATIC", "Time (HH:MM:SS)", 0, x, y + 38, 250, 22)
        self.clock_time = self.add("EDIT", time.strftime("%H:%M:%S", t), 0x80 | WS_TABSTOP,
                                   x + 260, y + 34, 160, 24, 951, WS_EX_CLIENTEDGE)
        self.add("BUTTON", "Set date and time", WS_TABSTOP, x + 260, y + 76, 160, 28, 952)
        self.add("BUTTON", "Use real time", WS_TABSTOP, x + 430, y + 76, 140, 28, 953)
        off = int(self.app.cfg.get("clock_offset", 0) or 0)
        self.clock_status_h = self.add(
            "STATIC", ("WinShell clock is %+d s from real time" % off) if off else
            "The clock follows real time", 0, x, y + 120, 560, 22)
        self.add("STATIC", "If the system clock is read-only in this container, only the "
                           "WinShell clock is changed.", 0, x, y + 148, 560, 40)

    def build_list_page(self, key, x, y):
        self.list_key = key
        self.list_hwnd = self.add("LISTBOX", "", 0x1 | WS_BORDER | WS_VSCROLL, x, y, 520, 300, 300)
        for p in self.app.cfg[key]:
            SendMessageS(self.list_hwnd, 0x180, 0, display_name(p) + "    " + p)
        for i, (label, cid) in enumerate((("Add...", 801), ("Remove", 802),
                                          ("Move up", 803), ("Move down", 804))):
            self.add("BUTTON", label, WS_TABSTOP, x + 530, y + i * 34, 100, 28, cid)

    # ---- commits
    def commit(self, key, value):
        if self.app.cfg.get(key) != value:
            self.app.cfg[key] = value
            self.app.save()
            self.app.apply_all(key)

    def commit_edit(self, cid):
        key, kind, h, _extra = self.ctrls[cid]
        if self.rebuilding or not IsWindow(h):
            return
        buf = create_unicode_buffer(1024)
        GetWindowTextW(h, buf, 1024)
        raw = buf.value
        try:
            if kind in ("int", "float"):
                val = int(float(raw)) if kind == "int" else float(raw)
                lo, hi = LIMITS.get(key, (-10 ** 9, 10 ** 9))
                val = max(lo, min(hi, val))
            else:
                val = raw.replace("\\n", "\n")
                if kind == "color":
                    val = val.strip()
                    if val and not val.startswith("#"):
                        val = "#" + val
                    if val and hex_color(val, None) is None:
                        return
        except ValueError:
            return
        self.commit(key, val)

    def apply_all_edits(self):
        for cid, (key, kind, h, _e) in list(self.ctrls.items()):
            if kind in ("int", "float", "str", "file", "color"):
                self.commit_edit(cid)

    def list_command(self, cid):
        key, lst = self.list_key, self.app.cfg[self.list_key]
        sel = SendMessageW(self.list_hwnd, 0x188, 0, 0)
        if cid == 801:
            if key == "bookmarks":
                p = browse_folder(self.hwnd, "Add a favorite folder")
            else:
                flt = FILTER_ALL if key == "desktop_extra" else FILTER_PROGRAMS
                p = browse_file(self.hwnd, "Add", flt)
            if p and p not in lst:
                lst.append(p)
        elif 0 <= sel < len(lst):
            if cid == 802:
                lst.pop(sel)
            elif cid == 803 and sel > 0:
                lst[sel - 1], lst[sel] = lst[sel], lst[sel - 1]
            elif cid == 804 and sel < len(lst) - 1:
                lst[sel + 1], lst[sel] = lst[sel], lst[sel + 1]
        self.app.save()
        self.app.apply_all(key)
        self.select_page(self.page)

    def set_clock(self):
        def text(h):
            buf = create_unicode_buffer(64)
            GetWindowTextW(h, buf, 64)
            return buf.value.strip()

        try:
            t = time.strptime(text(self.clock_date) + " " + text(self.clock_time),
                              "%Y-%m-%d %H:%M:%S")
        except ValueError:
            SetWindowTextW(self.clock_status_h, "Invalid date or time")
            return
        target = time.mktime(t)
        st = SYSTEMTIME(t.tm_year, t.tm_mon, (t.tm_wday + 1) % 7, t.tm_mday, t.tm_hour,
                        t.tm_min, t.tm_sec, 0)
        try:
            ok = SetLocalTime(byref(st))
        except Exception:
            ok = 0
        self.app.cfg["clock_offset"] = 0 if ok else int(target - time.time())
        self.app.save()
        self.app.apply_all()
        SetWindowTextW(self.clock_status_h, "System clock set" if ok else
                       "System clock is read-only: WinShell clock changed")

    def reset_clock(self):
        self.app.cfg["clock_offset"] = 0
        self.app.save()
        self.app.apply_all()
        self.select_page(self.page)

    def draw_list_item(self, dis):
        a = self.app
        th = a.theme()
        hdc, rc = dis.hDC, dis.rcItem
        if dis.itemID >= len(PAGES):
            return
        name = PAGES[dis.itemID][0]
        sel = bool(dis.itemState & 1)
        box = (rc.left, rc.top, rc.right, rc.bottom)
        fill(hdc, box, th["sel"] if sel else th["win_bg"])
        if sel:
            fill(hdc, (box[0], box[1] + 8, box[0] + 4, box[3] - 8), th["accent"])
        draw_glyph(hdc, PAGE_ICONS.get(name, "settings"), (box[0] + 10, box[1], box[0] + 44, box[3]),
                   th["accent"] if sel else th["text"], size=20)
        old = SelectObject(hdc, a.font)
        SetBkMode(hdc, 1)
        text_out(hdc, name, (box[0] + 50, box[1], box[2] - 6, box[3]),
                 DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS | DT_NOPREFIX, th["text"])
        SelectObject(hdc, old)

    def set_color(self, key, hx):
        self.commit(key, hx)
        self.select_page(self.page)

    def on_message(self, hwnd, msg, wp, lp):
        if msg == 0x2C:                              # WM_MEASUREITEM (category list)
            mi = ctypes.cast(lp, POINTER(MEASUREITEMSTRUCT)).contents
            if mi.CtlID == 100:
                mi.itemHeight = 40
                return 1
        if msg in (0x133, 0x134, 0x135, 0x138):      # themed control colours
            th = self.app.theme()
            col = th["input"] if msg in (0x133, 0x134) else th["win_bg"]
            SetTextColor(wp, th["text"])
            SetBkColor(wp, col)
            return self.brush(col)
        if msg == WM_ERASEBKGND:
            rc = RECT()
            GetClientRect(hwnd, byref(rc))
            fill(wp, (0, 0, rc.right, rc.bottom), self.app.theme()["win_bg"])
            return 1
        if msg == 0x2B:                              # WM_DRAWITEM (category list, swatches)
            dis = ctypes.cast(lp, POINTER(DRAWITEMSTRUCT)).contents
            if dis.CtlID == 100:
                self.draw_list_item(dis)
                return 1
            info = self.swatches.get(dis.CtlID)
            if info:
                key, hx = info
                rc = dis.rcItem
                box = (rc.left, rc.top, rc.right, rc.bottom)
                th = self.app.theme()
                cur = str(self.app.cfg.get(key, "")).upper() == hx.upper()
                fill(dis.hDC, box, hex_color(hx, th["bg"]) if hx else th["bg"])
                frame(dis.hDC, box, rgb(0, 0, 0))
                if cur:
                    frame(dis.hDC, (box[0] + 1, box[1] + 1, box[2] - 1, box[3] - 1),
                          rgb(255, 255, 255), 2)
                if not hx:
                    SetBkMode(dis.hDC, 1)
                    text_out(dis.hDC, "A", box, DT_CENTER | DT_VCENTER | DT_SINGLELINE, th["text"])
                return 1
            return 0
        if msg == WM_COMMAND:
            cid, code = wp & 0xFFFF, (wp >> 16) & 0xFFFF
            if cid == 100 and code == 1:
                self.select_page(SendMessageW(self.lb, 0x188, 0, 0))
            elif cid in (801, 802, 803, 804) and self.list_hwnd:
                self.list_command(cid)
            elif cid == 900:
                self.apply_all_edits()
            elif cid == 952:
                self.set_clock()
            elif cid == 953:
                self.reset_clock()
            elif cid in self.swatches and code == 0:
                key, hx = self.swatches[cid]
                self.set_color(key, hx)
            elif cid in self.ctrls:
                key, kind, h, extra = self.ctrls[cid]
                if kind == "bool" and code == 0:
                    self.commit(key, SendMessageW(h, 0xF0, 0, 0) == 1)
                elif kind == "choice" and code == 1:
                    idx = SendMessageW(h, 0x147, 0, 0)
                    if 0 <= idx < len(extra):
                        self.commit(key, extra[idx])
                elif kind == "browse" and code == 0:
                    bkey = self.ctrls[cid - 5000][0]
                    flt = (FILTER_ICONS if (bkey == "start_icon" or bkey.startswith("tb_icon_")) else
                           FILTER_THEME if bkey == "theme_file" else FILTER_IMAGES)
                    p = browse_file(hwnd, "Choose a file", flt)
                    if p:
                        SetWindowTextW(self.ctrls[cid - 5000][2], p)
                        self.commit_edit(cid - 5000)
                elif kind == "action" and code == 0:
                    self.app.save_tb_theme()
                elif kind == "pickcolor" and code == 0:
                    cur = hex_color(self.app.cfg.get(key, ""), rgb(255, 255, 255))
                    col = pick_color(hwnd, cur)
                    if col is not None:
                        self.set_color(key, "#%02X%02X%02X" % split_rgb(col))
                elif kind in ("int", "float", "str", "file", "color") and code == 0x200:
                    self.commit_edit(cid)
            return 0
        if msg == WM_CLOSE:
            self.clear()
            WINDOWS.pop(hwnd, None)
            DestroyWindow(hwnd)
            self.hwnd = None
            return 0
        return DefWindowProcW(hwnd, msg, wp, lp)


# ==========================================================================
# Application glue
# ==========================================================================
class App:
    def __init__(self):
        self.cfg = load_config()
        self.mtime = config_mtime()
        self.menu_depth = 0
        self.font = self.font_big = self.font_title = None
        self.bar = Taskbar(self)
        self.start = StartMenu(self)
        self.desktop = Desktop(self)
        self.settings = Settings(self)
        self.avatar_key = None
        self.blur_bmp = None
        self.blur_sig = None
        self.explorers = []
        self.clip = None
        self.folder_icon = None
        self.titlebars = {}
        self.autostarted = False
        CURRENT["app"] = self
        self.thumbs = {}
        self.snap_state = {}
        self.shade_state = {}
        self.hooks = []
        self._winevent_cb = None
        self.hover_prev = HoverPreview(self)
        self.preview = PreviewPanel(self)
        self.float = FloatIcon(self)

    # ---- geometry / theme
    def px(self, value):
        try:
            return max(1, int(round(float(value) * float(self.cfg["scale"]))))
        except Exception:
            return int(value)

    def bar_rect(self):
        sw, sh = screen_size()
        h = self.px(self.cfg["height"])
        return (0, 0, sw, h) if self.cfg["position"] == "top" else (0, sh - h, sw, h)

    def work_rect(self):
        sw, sh = screen_size()
        h = self.px(self.cfg["height"])
        return (0, h, sw, sh) if self.cfg["position"] == "top" else (0, 0, sw, sh - h)

    def theme(self):
        c = self.cfg
        t = ui_palette(c["theme"], c["accent"])
        if c["bar_color"]:
            t["bg"] = hex_color(c["bar_color"], t["bg"])
        return t

    def apply_fonts(self):
        for f in (self.font, self.font_big, self.font_title):
            if f:
                DeleteObject(f)
        size = self.px(self.cfg["font_size"])
        self.font_title = make_font(self.cfg["font"], size + 8, 600)
        self.font = make_font(self.cfg["font"], size)
        self.font_big = make_font(self.cfg["font"], size + 2, 600)

    # ---- user avatar
    def draw_avatar(self, hdc, cx, cy, d):
        r = d // 2
        rgn = CreateEllipticRgn(cx - r, cy - r, cx + r + 1, cy + r + 1)
        SelectClipRgn(hdc, rgn)
        img = load_image(self.cfg["user_photo"]) if self.cfg["user_photo"] else None
        if img:
            mem = CreateCompatibleDC(hdc)
            old = SelectObject(mem, img[0])
            side = max(1, min(img[1], img[2]))
            SetStretchBltMode(hdc, 4)
            StretchBlt(hdc, cx - r, cy - r, d, d, mem, (img[1] - side) // 2,
                       (img[2] - side) // 2, side, side, SRCCOPY)
            SelectObject(mem, old)
            DeleteDC(mem)
        else:
            fill(hdc, (cx - r, cy - r, cx + r + 1, cy + r + 1), self.theme()["accent"])
            letter = (self.cfg["user_name"] or "U")[0].upper()
            old_f = SelectObject(hdc, self.font_big)
            text_out(hdc, letter, (cx - r, cy - r, cx + r + 1, cy + r + 1),
                     DT_CENTER | DT_VCENTER | DT_SINGLELINE, rgb(255, 255, 255))
            SelectObject(hdc, old_f)
        SelectClipRgn(hdc, None)
        DeleteObject(rgn)

    # ---- helpers
    def run(self, target, params=None, show=1):
        base = os.path.basename(str(target)).lower()
        if self.cfg["use_winshell_explorer"] and self.try_explorer(target, base, params):
            return
        try:
            result = ShellExecuteW(None, "open", target, params, None, show)
            if (result or 0) <= 32:
                log.warning("ShellExecute failed for %s (%s)", target, result)
        except Exception as exc:
            log.warning("run failed: %s", exc)

    def style_menu(self, menu):
        mi = MENUINFO()
        mi.cbSize, mi.fMask, mi.hbrBack = sizeof(mi), 2, MENU["brush"]
        SetMenuInfo(menu, byref(mi))

    def add_menu_item(self, menu, flags, ident, data):
        key = len(MENU["items"]) + 1
        MENU["items"][key] = data
        AppendMenuData(menu, flags | 0x100, ident, key)       # MF_OWNERDRAW

    def build_menu(self, items):
        menu = CreatePopupMenu()
        self.style_menu(menu)
        for it in items:
            if it is None:
                self.add_menu_item(menu, MF_GRAYED, 0, {"sep": True})
            elif it[0] == "sub":
                sub = self.build_menu(it[2])
                self.add_menu_item(menu, MF_POPUP, sub,
                                   {"label": it[1], "icon": it[3] if len(it) > 3 else "",
                                    "sub": True})
            else:
                flags = it[2] if len(it) > 2 else 0
                self.add_menu_item(menu, MF_STRING | flags, it[0],
                                   {"label": it[1], "icon": it[3] if len(it) > 3 else ""})
        return menu

    def popup(self, owner, items, flags, x=None, y=None):
        """Themed owner-drawn popup. Items: (id, label[, flags[, icon]]), None, or
        ("sub", label, [items][, icon])."""
        MENU["items"].clear()
        if MENU["brush"]:
            DeleteObject(MENU["brush"])
        MENU["brush"] = CreateSolidBrush(self.theme()["start_bg"])
        menu = self.build_menu(items)
        pt = wt.POINT()
        GetCursorPos(byref(pt))
        px_x = pt.x if x is None else x
        px_y = pt.y if y is None else y
        SetForegroundWindow(owner)
        self.menu_depth += 1
        try:
            cmd = TrackPopupMenu(menu, flags, px_x, px_y, 0, owner, None)
        finally:
            self.menu_depth -= 1
            DestroyMenu(menu)
        return cmd

    def pin_taskbar(self, path):
        key = app_key(exe_for(path))
        if key not in [app_key(exe_for(p)) for p in self.cfg["pinned"]]:
            self.cfg["pinned"].append(path)
            self.save()
            self.bar.rebuild_pins()
            self.bar.refresh(force=True)
            self.bar.invalidate()

    def unpin_taskbar(self, key):
        self.cfg["pinned"] = [p for p in self.cfg["pinned"] if app_key(exe_for(p)) != key]
        self.save()
        self.bar.rebuild_pins()
        self.bar.refresh(force=True)
        self.bar.invalidate()

    def toggle_list(self, name, path):
        if path in self.cfg[name]:
            self.cfg[name].remove(path)
        else:
            self.cfg[name].append(path)
        self.save()

    def open_settings(self, page=None):
        try:
            self.settings.show(page)
        except Exception:
            log.exception("settings failed")

    # ---- startup apps / title bars / preview
    def run_autostart(self):
        if self.autostarted:
            return
        self.autostarted = True
        if "--restart" in sys.argv:              # a shell restart must not relaunch apps
            return
        for p in self.cfg["autostart"]:
            try:
                self.run(p if os.path.isabs(p) else find_exe(p))
            except Exception:
                log.exception("autostart failed for %s", p)

    def title_color(self):
        c = self.cfg
        if c["look_title_accent"]:
            return hex_color(c["accent"], rgb(0, 120, 215))
        return hex_color(c["look_title_color"], rgb(255, 255, 255))

    def confirm_close_all(self, owner):
        wins = [h for e in self.bar.entries for h in e.tasks]
        if not wins:
            return
        msg = "Close all %d running window(s)?\nUnsaved work may be lost." % len(wins)
        self.menu_depth += 1
        try:
            answer = MessageBoxW(owner, msg, "WinShell", 0x4 | 0x20 | 0x40000)
        finally:
            self.menu_depth -= 1
        if answer == 6:
            for h in wins:
                PostMessageW(h, WM_CLOSE, 0, 0)

    def update_titlebars(self):
        if not self.cfg["custom_titlebar"]:
            self.clear_titlebars()
            return
        fg = GetForegroundWindow()
        live = set()
        for e in self.bar.entries:
            for h in e.tasks:
                st = GetWindowLongW(h, -16) & 0xFFFFFFFF
                ex = GetWindowLongW(h, GWL_EXSTYLE) & 0xFFFFFFFF
                if (st & 0xC00000) != 0xC00000 or (ex & WS_EX_TOOLWINDOW):
                    continue
                live.add(h)
                tb = self.titlebars.get(h)
                if tb is None:
                    tb = self.titlebars[h] = TitleBar(self, h)
                tb.update(bool(fg) and (fg == h or GetAncestor(fg, GA_ROOTOWNER) == h))
        for h in list(self.titlebars):
            if h not in live:
                tb = self.titlebars.pop(h)
                if tb.hwnd:
                    WINDOWS.pop(tb.hwnd, None)
                    DestroyWindow(tb.hwnd)
        for state in (self.snap_state, self.shade_state):
            for h in list(state):
                if not IsWindow(h):
                    del state[h]

    def clear_titlebars(self):
        for tb in list(self.titlebars.values()):
            if tb.hwnd:
                WINDOWS.pop(tb.hwnd, None)
                DestroyWindow(tb.hwnd)
        self.titlebars = {}

    # ---- title bar themes, snap / shade, thumbnails, file opening, hooks
    TB_SIG_KEYS = ("tb_theme", "tb_use_theme_colors", "look_title_color", "look_title_accent",
                   "tb_align", "tb_text", "tb_show_icon", "tb_show_snap", "tb_show_shade",
                   "tb_icon_min", "tb_icon_max", "tb_icon_restore", "tb_icon_close",
                   "tb_icon_snap", "tb_icon_shade", "glass_blur_title", "theme", "accent")

    def titlebar_sig(self):
        return tuple(str(self.cfg.get(k)) for k in self.TB_SIG_KEYS)

    def tb_theme(self):
        c = self.cfg
        th = dict(TB_THEMES.get(c["tb_theme"], TB_THEMES["windows10"]))
        if not c["tb_use_theme_colors"]:
            col = split_rgb(self.title_color())
            lum = (col[0] * 299 + col[1] * 587 + col[2] * 114) // 1000
            fgc = (0, 0, 0) if lum > 150 else (255, 255, 255)
            th.update(bg=col, ibg=split_rgb(mix(rgb(*col), rgb(128, 128, 128), 0.35)), fg=fgc,
                      glyph=fgc, ifg=split_rgb(mix(rgb(*fgc), rgb(*col), 0.5)))
            th.pop("bg2", None)
            th.pop("ibg2", None)
        icons = dict(th.get("icons", {}))
        for n in TB_ICON_NAMES:
            p = c.get("tb_icon_" + n)
            if p:
                icons[n] = p
        th["icons"] = icons
        return th

    def save_tb_theme(self):
        """Save the current title bar look (colors + icon files) as a reusable theme folder."""
        c = self.cfg
        name = "".join(ch for ch in str(c["tb_new_theme_name"]) if ch.isalnum() or ch in "-_ ").strip() or "my_theme"
        folder = os.path.join(THEMES_DIR, name)
        try:
            os.makedirs(folder, exist_ok=True)
            th = self.tb_theme()
            data = {"base": c["tb_theme"]}
            for k in _TB_COLOR_KEYS:
                if k in th:
                    data[k] = "#%02X%02X%02X" % tuple(th[k])
            for k in ("btn", "side", "align", "bw"):
                if k in th:
                    data[k] = th[k]
            icons = {}
            for n, p in th["icons"].items():
                if p and os.path.exists(p):
                    fn = "%s%s" % (n, os.path.splitext(p)[1])
                    shutil.copy2(p, os.path.join(folder, fn))
                    icons[n] = fn
            data["icons"] = icons
            with open(os.path.join(folder, "theme.json"), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            load_custom_tb_themes()
            c["tb_theme"] = name
            for n in TB_ICON_NAMES:
                c["tb_icon_" + n] = ""
            c["tb_use_theme_colors"] = True
            self.save()
            self.apply_all("tb_theme")
        except OSError as exc:
            log.warning("save theme failed: %s", exc)

    def snap_window(self, h):
        wr = self.work_rect()
        mid = (wr[0] + wr[2]) // 2
        st = self.snap_state.get(h)
        if IsZoomed(h):
            ShowWindow(h, 9)
        rc = RECT()
        GetWindowRect(h, byref(rc))
        if st is None:
            orig, mode = (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top), "left"
        elif st[0] == "left":
            orig, mode = st[1], "right"
        else:
            x, y, w, hh = st[1]
            SetWindowPos(h, None, x, y, w, hh, SWP_NOZORDER | SWP_NOACTIVATE)
            self.snap_state.pop(h, None)
            return
        x, w = (wr[0], mid - wr[0]) if mode == "left" else (mid, wr[2] - mid)
        SetWindowPos(h, None, x, wr[1], w, wr[3] - wr[1], SWP_NOZORDER | SWP_NOACTIVATE)
        self.snap_state[h] = (mode, orig)

    def shade_window(self, h, cap, inset):
        if h in self.shade_state:
            x, y, w, hh = self.shade_state.pop(h)
            SetWindowPos(h, None, x, y, w, hh, SWP_NOZORDER | SWP_NOACTIVATE)
            return
        if IsZoomed(h):
            ShowWindow(h, 9)
        rc = RECT()
        GetWindowRect(h, byref(rc))
        self.shade_state[h] = (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)
        SetWindowPos(h, None, 0, 0, rc.right - rc.left, cap + 2 * inset, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE)

    def thumb(self, hwnd, tw, tht, force=False):
        """Cached live thumbnail of a window (unobscured windows get a real screen copy)."""
        now = time.time()
        ent = self.thumbs.get(hwnd)
        ttl = max(0.2, int(self.cfg["preview_refresh_ms"]) / 1000.0)
        if ent and ent[1:3] == (tw, tht) and not force and now - ent[3] < ttl:
            return ent[0]
        new = capture_window(hwnd, tw, tht, not window_occluded(hwnd))
        if new:
            if ent and ent[0]:
                DeleteObject(ent[0])
            self.thumbs[hwnd] = (new, tw, tht, now)
            if len(self.thumbs) > 40:
                for h in [h for h in self.thumbs if not IsWindow(h)]:
                    DeleteObject(self.thumbs.pop(h)[0])
            return new
        return ent[0] if ent else None

    def open_path(self, path):
        exe = self.cfg["assoc"].get(os.path.splitext(path)[1].lower())
        if exe and os.path.exists(exe):
            self.run(exe, '"%s"' % path)
        else:
            self.run(path)

    def install_hooks(self):
        """WinEvent hooks: title bars follow windows instantly; the bar stays in front."""
        if SetWinEventHook is None or self.hooks:
            return

        def cb(hhook, event, hwnd, idobj, idchild, tid, tm):
            try:
                if event == 3:
                    self.bar.ensure_front()
                    self.update_titlebars()
                elif event in (0x0A, 0x0B):
                    self.bar.raise_bar()
                elif idobj == 0 and hwnd:
                    tb = self.titlebars.get(hwnd)
                    if tb:
                        tb.update()
                    if hwnd == GetForegroundWindow():
                        self.bar.ensure_front()
            except Exception:
                pass

        self._winevent_cb = WINEVENTPROC(cb)
        for lo, hi in ((3, 3), (0x0A, 0x0B), (0x800B, 0x800B)):
            try:
                h = SetWinEventHook(lo, hi, None, self._winevent_cb, 0, 0, 0)
                if h:
                    self.hooks.append(h)
            except Exception:
                log.exception("SetWinEventHook failed")

    def remove_hooks(self):
        for h in self.hooks:
            try:
                UnhookWinEvent(h)
            except Exception:
                pass
        self.hooks = []

    def ensure_dirs(self):
        home = os.environ.get("USERPROFILE", "")
        dirs = [CONFIG_DIR, THEMES_DIR, os.path.join(CONFIG_DIR, "Icons"),
                os.path.join(CONFIG_DIR, "Backups")]
        if home:
            dirs += [os.path.join(home, d) for d in ("Desktop", "Documents", "Downloads",
                                                     "Pictures", "Music", "Videos")]
        for d in dirs:
            try:
                os.makedirs(d, exist_ok=True)
            except OSError as exc:
                log.info("cannot create %s: %s", d, exc)

    # ---- clock / icons / explorer
    def clock_str(self):
        off = float(self.cfg.get("clock_offset", 0) or 0)
        return time.strftime(str(self.cfg["clock_format"]), time.localtime(time.time() + off))

    def start_icon(self, size):
        p = self.cfg.get("start_icon", "")
        return load_icon_file(p, size) if p else 0

    def explorer_icon(self):
        if self.folder_icon is None:
            self.folder_icon = make_folder_icon(32)
        return self.folder_icon

    def open_explorer(self, path=None, select=None):
        try:
            Explorer(self).create(path, select)
        except Exception:
            log.exception("explorer failed")

    def try_explorer(self, target, base, params):
        t = str(target)
        if base == "explorer.exe" and not params:
            self.open_explorer()
            return True
        if base == "explorer.exe" and params and params.startswith("/select,"):
            pth = params[8:].strip('"')
            self.open_explorer(os.path.dirname(pth), pth)
            return True
        if not params and t != "::thispc" and os.path.isdir(t):
            self.open_explorer(t)
            return True
        return False

    # ---- fake blur
    def blur_bg(self):
        c = self.cfg
        if not any(c[k] for k in BLUR_KEYS):
            return None
        sw, sh = screen_size()
        sig = (c["wallpaper"], c["wallpaper_mode"], c["desktop_color"], sw, sh)
        if sig != self.blur_sig:
            if self.blur_bmp:
                DeleteObject(self.blur_bmp)
            wall = render_wallpaper(c, sw, sh)
            self.blur_bmp = blur_bitmap(wall, sw, sh)
            DeleteObject(wall)
            self.blur_sig = sig
        return self.blur_bmp

    def paint_blur(self, hdc, W, Hh, sx, sy):
        bmp = self.blur_bg()
        if not bmp:
            return False
        src = CreateCompatibleDC(hdc)
        old = SelectObject(src, bmp)
        BitBlt(hdc, 0, 0, W, Hh, src, sx, sy, SRCCOPY)
        SelectObject(src, old)
        DeleteDC(src)
        return True

    # ---- window look (title bars / scroll bars of Wine apps)
    def get_metrics(self):
        ncm = NONCLIENTMETRICSW()
        ncm.cbSize = sizeof(ncm)
        if not SystemParametersInfoW(0x29, sizeof(ncm), byref(ncm), 0):
            return None
        return ncm

    def set_metrics(self, values, font=False):
        ncm = self.get_metrics()
        if ncm is None:
            return
        for k, v in values.items():
            setattr(ncm, k, int(v))
        if font:
            for f in ("lfCaptionFont", "lfSmCaptionFont", "lfMenuFont", "lfStatusFont",
                      "lfMessageFont"):
                getattr(ncm, f).lfFaceName = str(self.cfg["font"])[:31]
        SystemParametersInfoW(0x2A, sizeof(ncm), byref(ncm), 3)

    def set_colors(self, mapping):
        n = len(mapping)
        if not n:
            return
        idx = (c_int * n)(*mapping.keys())
        vals = (wt.DWORD * n)(*mapping.values())
        SetSysColors(n, idx, vals)

    def apply_window_look(self):
        c = self.cfg
        try:
            if c["theme_file"] and os.path.exists(c["theme_file"]):
                for k, v in (("ThemeActive", "1"), ("DllName", c["theme_file"]),
                             ("ColorName", "NormalColor"), ("SizeName", "NormalSize")):
                    reg_set(THEME_KEY, k, v)
            style = c["window_look"]
            if style == "default":
                bk = c.get("look_backup") or {}
                if bk:
                    self.set_colors({int(k): v for k, v in bk.get("colors", {}).items()})
                    if bk.get("metrics"):
                        self.set_metrics(bk["metrics"])
                    c["look_backup"] = {}
                    self.save()
            else:
                if not c.get("look_backup"):
                    ncm = self.get_metrics()
                    names = ("iBorderWidth", "iScrollWidth", "iScrollHeight", "iCaptionWidth",
                             "iCaptionHeight", "iSmCaptionWidth", "iSmCaptionHeight",
                             "iMenuWidth", "iMenuHeight", "iPaddedBorderWidth")
                    c["look_backup"] = {
                        "colors": {str(i): GetSysColor(i) for i in look_palette(True, 0, False)},
                        "metrics": {n: getattr(ncm, n) for n in names} if ncm else {}}
                    self.save()
                pal = look_palette(style == "windows10_dark",
                                   hex_color(c["accent"], rgb(0, 120, 215)),
                                   bool(c["look_title_accent"]))
                tc = split_rgb(self.title_color())          # chosen title bar colour
                lum = (tc[0] * 299 + tc[1] * 587 + tc[2] * 114) // 1000
                pal[2] = pal[27] = pal[10] = tc
                pal[9] = (0, 0, 0) if lum > 150 else (255, 255, 255)
                self.set_colors({i: rgb(*v) for i, v in pal.items()})
                cap = int(c["look_caption_height"])
                sb = int(c["look_scrollbar_width"])
                self.set_metrics({"iBorderWidth": 1, "iScrollWidth": sb, "iScrollHeight": sb,
                                  "iCaptionWidth": cap, "iCaptionHeight": cap,
                                  "iSmCaptionWidth": cap, "iSmCaptionHeight": cap,
                                  "iMenuWidth": 20, "iMenuHeight": 20,
                                  "iPaddedBorderWidth": 4}, font=True)
            self.refresh_frames()
        except Exception:
            log.exception("window look failed")

    def refresh_frames(self):
        res = c_size_t(0)
        for m in (0x15, 0x1A, 0x31A):           # SYSCOLORCHANGE, SETTINGCHANGE, THEMECHANGED
            SendMessageTimeoutW(0xFFFF, m, 0, 0, 0x2, 200, byref(res))

        def cb(hwnd, _lp):
            if hwnd and IsWindowVisible(hwnd):
                SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x37)   # frame changed
                RedrawWindow(hwnd, None, None, 0x581)
            return True

        callback = WNDENUMPROC(cb)
        EnumWindows(callback, 0)

    # ---- config
    def save(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=2)
            self.mtime = config_mtime()
        except OSError as exc:
            log.warning("save failed: %s", exc)

    def check_config(self):
        if config_mtime() != self.mtime:
            self.reload()

    def reload(self):
        self.cfg = load_config()
        self.mtime = config_mtime()
        self.apply_all()

    def apply_all(self, changed=None):
        self.apply_fonts()
        if changed in LOOK_KEYS:
            self.apply_window_look()
        self.bar.apply()
        self.start.apply()
        self.desktop.apply(changed)
        self.start.invalidate()
        for ex in self.explorers:
            ex.invalidate()
        if self.settings.hwnd:
            self.settings.brushes.clear()
            RedrawWindow(self.settings.hwnd, None, None, 0x185)
        if self.bar.hwnd:                       # keep the taskbar above everything
            SetWindowPos(self.bar.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    # ---- lifecycle
    def start_all(self):
        self.ensure_dirs()
        load_custom_tb_themes()
        self.apply_fonts()
        if self.cfg["window_look"] != "default" or self.cfg["theme_file"]:
            self.apply_window_look()
        self.desktop.apply()                    # desktop first, taskbar on top of it
        self.bar.create()
        SetWindowPos(self.bar.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        self.install_hooks()

    def restart(self):
        try:
            subprocess.Popen([sys.executable, os.path.abspath(__file__), "--restart"])
        except Exception:
            log.exception("restart failed")
            return
        PostMessageW(self.bar.hwnd, WM_CLOSE, 0, 0)

    def shutdown(self):
        try:
            KillTimer(self.bar.hwnd, 1)
            DeregisterShellHookWindow(self.bar.hwnd)
            self.bar.restore_work_area()
            wine_bar = FindWindowW("Shell_TrayWnd", None)
            if wine_bar:
                ShowWindow(wine_bar, 5)
            self.remove_hooks()
            self.clear_titlebars()
            for ent in self.thumbs.values():
                DeleteObject(ent[0])
            for w in (self.desktop, self.start, self.preview, self.float, self.hover_prev):
                if w.hwnd:
                    DestroyWindow(w.hwnd)
            for f in (self.font, self.font_big, self.font_title):
                if f:
                    DeleteObject(f)
            ICONS.close()
        except Exception:
            log.exception("shutdown error")
        PostQuitMessage(0)


def arg_after(flag):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def send_to_running(path, select):
    """If WinShell already runs, hand the folder to it (used by the Folder open verb)."""
    hwnd = FindWindowW("WinShellBar", None)
    if not hwnd:
        return False
    text = (select or path) + "\0"
    buf = ctypes.create_unicode_buffer(text, len(text))
    cds = COPYDATASTRUCT(2 if select else 1, len(text) * 2, ctypes.cast(buf, c_void_p))
    SendMessageW(hwnd, 0x4A, 0, ctypes.addressof(cds))
    return True


def main():
    open_path, select_path = arg_after("--open"), arg_after("--select")
    if (open_path or select_path) and send_to_running(open_path, select_path):
        return
    if "--restart" in sys.argv:
        time.sleep(2)
    mutex = CreateMutexW(None, False, "WinShell.Taskbar.Mutex")
    if ctypes.get_last_error() == 183:
        return
    app = App()
    atexit.register(app.bar.restore_work_area)
    app.start_all()
    log.info("WinShell started")
    if open_path or select_path:
        app.open_explorer(os.path.dirname(select_path) if select_path else open_path, select_path)
    msg = wt.MSG()
    while GetMessageW(byref(msg), None, 0, 0) > 0:
        TranslateMessage(byref(msg))
        DispatchMessageW(byref(msg))
    CloseHandle(mutex)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("fatal error")
        raise

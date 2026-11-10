"""
WinShell Setup (installer / uninstaller) for Wine / Winlator.

Run inside the container:
    python winshell_setup.py                 (graphical installer)
    python winshell_setup.py --silent        (install with defaults)
    python winshell_setup.py --uninstall     (remove WinShell, restore registry)
    options: --dir "C:\\Program Files\\WinShell"

What it does (every step can be switched off in the window):
  * copies winshell.py / winshell.exe to the install folder and writes a launcher
  * creates the folders WinShell needs (ProgramData\\WinShell\\{Themes,Icons,Backups},
    user folders Desktop/Documents/Downloads/Pictures/Music/Videos)
  * registry: autostart, "open folders with WinShell Explorer", font smoothing, font
    substitutes for Segoe UI, no Wine crash dialog, uninstall entry
    (the previous registry values are saved and restored on uninstall)
  * Start Menu and Desktop shortcuts, default config
"""
import ctypes
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from ctypes import wintypes as wt

try:
    import winreg
except ImportError:          # only for testing on non-Windows systems
    winreg = None

VERSION = "2.0"
FROZEN = getattr(sys, "frozen", False)
HERE = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(sys.argv[0]))
PROGRAM_FILES = os.environ.get("ProgramFiles", r"C:\Program Files")
DEFAULT_DIR = os.path.join(PROGRAM_FILES, "WinShell")
DATA_DIR = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "WinShell")
HOME = os.environ.get("USERPROFILE", r"C:\users\Public")
BACKUP_FILE = os.path.join(DATA_DIR, "Backups", "registry_backup.json")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\WinShell"
CLASS_VERBS = ("Folder", "Directory", "Drive")

OPTIONS = [
    ("files", "Install WinShell files and launcher", True),
    ("folders", "Create the folders WinShell needs (data, themes, user folders)", True),
    ("autostart", "Start WinShell automatically when the container starts", True),
    ("folders_verb", "Open folders with WinShell File Explorer (registry)", True),
    ("fonts", "Smooth fonts (ClearType) for Wine apps", True),
    ("subst", "Font substitutes for Segoe UI / Segoe UI Symbol", True),
    ("crash", "Hide the Wine crash dialog (fewer popups)", True),
    ("shortcuts", "Create Start Menu and Desktop shortcuts", True),
    ("uninstall", "Register in Programs and Features (uninstall entry)", True),
    ("config", "Write the default settings file", True),
    ("launch", "Start WinShell when setup finishes", True),
]


# ==========================================================================
# registry with backup
# ==========================================================================
BACKUP = []


def reg_read(path, name):
    if winreg is None:
        return None, None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)
    except OSError:
        return None, None


def reg_write(path, name, value, kind=None):
    """Write HKCU\\path[name] and remember the old value so uninstall can restore it."""
    if winreg is None:
        return
    kind = kind if kind is not None else winreg.REG_SZ
    old, old_kind = reg_read(path, name)
    BACKUP.append({"path": path, "name": name, "old": old, "kind": old_kind})
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
        winreg.SetValueEx(k, name, 0, kind, value)


def save_backup():
    os.makedirs(os.path.dirname(BACKUP_FILE), exist_ok=True)
    existing = []
    if os.path.exists(BACKUP_FILE):               # keep the FIRST (original) values
        with open(BACKUP_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
    seen = {(e["path"], e["name"]) for e in existing}
    existing += [b for b in BACKUP if (b["path"], b["name"]) not in seen]
    with open(BACKUP_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=1)


def restore_backup(log):
    if winreg is None or not os.path.exists(BACKUP_FILE):
        return
    with open(BACKUP_FILE, "r", encoding="utf-8") as f:
        entries = json.load(f)
    for e in reversed(entries):
        try:
            if e["old"] is None:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, e["path"], 0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, e["name"])
            else:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, e["path"]) as k:
                    winreg.SetValueEx(k, e["name"], 0, e["kind"], e["old"])
            log("restored %s\\%s" % (e["path"], e["name"] or "(default)"))
        except OSError:
            pass


# ==========================================================================
# .lnk writer (Windows shell link, unicode string data)
# ==========================================================================
def write_lnk(path, target, args="", workdir="", icon="", icon_index=0):
    flags = 0x02 | 0x10 | 0x20 | 0x40 | 0x80      # LinkInfo, WorkingDir, Arguments, Icon, Unicode
    header = struct.pack("<I", 0x4C) + struct.pack("<IHH8B", 0x00021401, 0, 0,
                                                    0xC0, 0, 0, 0, 0, 0, 0, 0x46)
    header += struct.pack("<II", flags, 0x20) + b"\0" * 24
    header += struct.pack("<IiI", 0, icon_index, 1) + b"\0" * 12      # + hotkey/reserved
    try:
        base = target.encode("mbcs", "replace") + b"\0"
    except LookupError:                      # non-Windows Python (testing only)
        base = target.encode("latin-1", "replace") + b"\0"
    vol = struct.pack("<IIII", 20, 3, 0, 16) + b"\0\0\0\0"      # VolumeID (fixed drive)
    off_vol = 28
    off_base = off_vol + len(vol)
    off_suffix = off_base + len(base)
    link_info = struct.pack("<IIIIIII", 0, 28, 1, off_vol, off_base, 0, off_suffix) + vol + base + b"\0"
    link_info = struct.pack("<I", len(link_info)) + link_info[4:]

    def ustr(s):
        return struct.pack("<H", len(s)) + s.encode("utf-16le")

    data = header + link_info + ustr(workdir) + ustr(args) + ustr(icon or target) + b"\0\0\0\0"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


# ==========================================================================
# install / uninstall
# ==========================================================================
def find_python():
    cands = [os.path.join(os.path.dirname(sys.executable), "pythonw.exe"), sys.executable]
    for name in ("pythonw.exe", "python.exe"):
        try:
            cands.append(shutil.which(name) or "")
        except Exception:
            pass
    for cand in cands:
        if cand and os.path.exists(cand):
            return cand
    return "pythonw.exe"


def payload(name):
    for d in (HERE, os.path.dirname(os.path.abspath(sys.argv[0])), os.getcwd()):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def command_for(install_dir):
    exe = os.path.join(install_dir, "winshell.exe")
    if os.path.exists(exe):
        return '"%s"' % exe
    return '"%s" "%s"' % (find_python(), os.path.join(install_dir, "winshell.py"))


def install(opts, install_dir, log):
    errors = 0

    def step(label, fn):
        nonlocal errors
        try:
            fn()
            log("OK    " + label)
        except Exception as exc:           # never abort the whole setup for one step
            errors += 1
            log("FAIL  %s (%s)" % (label, exc))

    def do_files():
        os.makedirs(install_dir, exist_ok=True)
        copied = False
        for name in ("winshell.exe", "winshell.py"):
            src = payload(name)
            if src:
                shutil.copy2(src, os.path.join(install_dir, name))
                copied = True
        if not copied:
            raise RuntimeError("winshell.py / winshell.exe not found next to the setup")
        me = os.path.abspath(sys.argv[0])
        if os.path.exists(me):
            shutil.copy2(me, os.path.join(install_dir, os.path.basename(me)))
        with open(os.path.join(install_dir, "winshell.bat"), "w") as f:
            f.write("@echo off\r\nstart \"\" %s %%*\r\n" % command_for(install_dir))

    def do_folders():
        for d in (DATA_DIR, os.path.join(DATA_DIR, "Themes"), os.path.join(DATA_DIR, "Icons"),
                  os.path.join(DATA_DIR, "Backups")):
            os.makedirs(d, exist_ok=True)
        for d in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"):
            os.makedirs(os.path.join(HOME, d), exist_ok=True)

    def do_autostart():
        reg_write(RUN_KEY, "WinShell", command_for(install_dir))

    def do_verbs():
        cmd = command_for(install_dir) + ' --open "%1"'
        for cls in CLASS_VERBS:
            base = r"Software\Classes\%s\shell\open\command" % cls
            reg_write(base, "", cmd)

    def do_fonts():
        reg_write(r"Control Panel\Desktop", "FontSmoothing", "2")
        reg_write(r"Control Panel\Desktop", "FontSmoothingType", 2, winreg.REG_DWORD if winreg else None)
        reg_write(r"Control Panel\Desktop", "FontSmoothingGamma", 1400, winreg.REG_DWORD if winreg else None)

    def do_subst():
        key = r"Software\Wine\Fonts\Replacements"
        reg_write(key, "Segoe UI", "Tahoma")
        reg_write(key, "Segoe UI Symbol", "Arial")
        reg_write(key, "Segoe UI Light", "Tahoma")

    def do_crash():
        reg_write(r"Software\Wine\WineDbg", "ShowCrashDialog", 0, winreg.REG_DWORD if winreg else None)

    def do_shortcuts():
        cmd = command_for(install_dir)
        exe_or_py = os.path.join(install_dir, "winshell.exe")
        if os.path.exists(exe_or_py):
            target, args = exe_or_py, ""
        else:
            target, args = find_python(), '"%s"' % os.path.join(install_dir, "winshell.py")
        menu = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Microsoft", "Windows",
                            "Start Menu", "Programs", "WinShell")
        write_lnk(os.path.join(menu, "WinShell.lnk"), target, args, install_dir)
        write_lnk(os.path.join(HOME, "Desktop", "WinShell.lnk"), target, args, install_dir)
        write_lnk(os.path.join(menu, "WinShell File Explorer.lnk"), target, args + ' --open ""', install_dir)
        del cmd

    def do_uninstall():
        key = UNINSTALL_KEY
        me = os.path.join(install_dir, os.path.basename(sys.argv[0]))
        unins = '"%s" --uninstall' % me if FROZEN else '"%s" "%s" --uninstall' % (find_python(), me)
        for name, value in (("DisplayName", "WinShell"), ("DisplayVersion", VERSION),
                            ("Publisher", "WinShell"), ("InstallLocation", install_dir),
                            ("UninstallString", unins)):
            reg_write(key, name, value)
        reg_write(r"Software\WinShell", "InstallPath", install_dir)

    def do_config():
        path = os.path.join(DATA_DIR, "config.json")
        if not os.path.exists(path):         # never overwrite the user's settings
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"autostart": [], "theme": "dark"}, f, indent=2)

    log("Installing WinShell %s to %s" % (VERSION, install_dir))
    plan = [("files", "Copy files", do_files), ("folders", "Create folders", do_folders),
            ("autostart", "Autostart entry", do_autostart), ("folders_verb", "Folder open verbs", do_verbs),
            ("fonts", "Font smoothing", do_fonts), ("subst", "Font substitutes", do_subst),
            ("crash", "Crash dialog off", do_crash), ("shortcuts", "Shortcuts", do_shortcuts),
            ("uninstall", "Uninstall entry", do_uninstall), ("config", "Default config", do_config)]
    for key, label, fn in plan:
        if opts.get(key):
            step(label, fn)
    try:
        save_backup()
    except OSError as exc:
        log("WARN  could not save the registry backup: %s" % exc)
    if opts.get("launch"):
        try:
            subprocess.Popen(command_for(install_dir), shell=True)
            log("OK    started WinShell")
        except OSError as exc:
            log("FAIL  start: %s" % exc)
    log("Done with %d problem(s). Log out / restart the container to apply everything." % errors)
    return errors


def uninstall(install_dir, log, remove_settings=False):
    restore_backup(log)
    menu = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Microsoft", "Windows",
                        "Start Menu", "Programs", "WinShell")
    for p in (menu, os.path.join(HOME, "Desktop", "WinShell.lnk")):
        try:
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
            log("removed " + p)
        except OSError:
            pass
    if winreg is not None:
        for key in (UNINSTALL_KEY, r"Software\WinShell"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
            except OSError:
                pass
    # the running setup may live in the install folder: remove everything else first
    try:
        for name in os.listdir(install_dir):
            if name.lower().startswith("winshell_setup"):
                continue
            p = os.path.join(install_dir, name)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        log("removed program files")
    except OSError:
        pass
    if remove_settings:
        shutil.rmtree(DATA_DIR, ignore_errors=True)
        log("removed settings")
    log("WinShell was uninstalled. Restart the container.")


# ==========================================================================
# graphical setup window
# ==========================================================================
def run_gui():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32")
    kernel32 = ctypes.WinDLL("kernel32")
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                    ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                    ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]

    def api(dll, name, restype, *argtypes):
        fn = dll[name]
        fn.restype, fn.argtypes = restype, list(argtypes)
        return fn

    H, U = wt.HWND, wt.UINT
    RegisterClassW = api(user32, "RegisterClassW", wt.ATOM, ctypes.POINTER(WNDCLASSW))
    CreateWindowExW = api(user32, "CreateWindowExW", wt.HWND, wt.DWORD, wt.LPCWSTR, wt.LPCWSTR,
                          wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, H,
                          wt.HMENU, wt.HINSTANCE, ctypes.c_void_p)
    DefWindowProcW = api(user32, "DefWindowProcW", LRESULT, H, U, wt.WPARAM, wt.LPARAM)
    GetMessageW = api(user32, "GetMessageW", ctypes.c_int, ctypes.POINTER(wt.MSG), H, U, U)
    PeekMessageW = api(user32, "PeekMessageW", wt.BOOL, ctypes.POINTER(wt.MSG), H, U, U, U)
    TranslateMessage = api(user32, "TranslateMessage", wt.BOOL, ctypes.POINTER(wt.MSG))
    DispatchMessageW = api(user32, "DispatchMessageW", LRESULT, ctypes.POINTER(wt.MSG))
    SendMessageW = api(user32, "SendMessageW", LRESULT, H, U, ctypes.c_size_t, ctypes.c_ssize_t)
    SendMessageS = api(user32, "SendMessageW", LRESULT, H, U, ctypes.c_size_t, ctypes.c_wchar_p)
    GetWindowTextW = api(user32, "GetWindowTextW", ctypes.c_int, H, wt.LPWSTR, ctypes.c_int)
    MessageBoxW = api(user32, "MessageBoxW", ctypes.c_int, H, wt.LPCWSTR, wt.LPCWSTR, U)
    DestroyWindow = api(user32, "DestroyWindow", wt.BOOL, H)
    PostQuitMessage = api(user32, "PostQuitMessage", None, ctypes.c_int)
    LoadCursorW = api(user32, "LoadCursorW", wt.HANDLE, wt.HINSTANCE, ctypes.c_void_p)
    GetStockObject = api(gdi32, "GetStockObject", ctypes.c_void_p, ctypes.c_int)
    GetModuleHandleW = api(kernel32, "GetModuleHandleW", wt.HMODULE, wt.LPCWSTR)

    state = {"boxes": {}, "dir": None, "log": None}
    font = GetStockObject(17)

    def child(cls, text, style, x, y, w, h, cid, parent, ex=0):
        hw = CreateWindowExW(ex, cls, text, 0x50000000 | style, x, y, w, h, parent, cid,
                             GetModuleHandleW(None), None)
        SendMessageW(hw, 0x30, font or 0, 1)
        return hw

    def pump():
        msg = wt.MSG()
        while PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            TranslateMessage(ctypes.byref(msg))
            DispatchMessageW(ctypes.byref(msg))

    def log(text):
        hw = state["log"]
        SendMessageW(hw, 0xB1, 1 << 30, 1 << 30)              # EM_SETSEL (end)
        SendMessageS(hw, 0xC2, 0, text + "\r\n")               # EM_REPLACESEL
        pump()

    def get_dir():
        buf = ctypes.create_unicode_buffer(520)
        GetWindowTextW(state["dir"], buf, 520)
        return buf.value.strip() or DEFAULT_DIR

    def chosen():
        return {k: SendMessageW(h, 0xF0, 0, 0) == 1 for k, h in state["boxes"].items()}

    def wndproc(hwnd, msg, wp, lp):
        if msg == 0x111:                                       # WM_COMMAND
            cid = wp & 0xFFFF
            if cid == 101:
                install(chosen(), get_dir(), log)
            elif cid == 102:
                ans = MessageBoxW(hwnd, "Also remove your WinShell settings and themes?", "Uninstall", 0x23)
                if ans != 2:
                    uninstall(get_dir(), log, remove_settings=(ans == 6))
            elif cid == 103:
                DestroyWindow(hwnd)
            return 0
        if msg == 0x2:                                         # WM_DESTROY
            PostQuitMessage(0)
            return 0
        return DefWindowProcW(hwnd, msg, wp, lp)

    proc = WNDPROC(wndproc)
    wc = WNDCLASSW()
    wc.lpfnWndProc, wc.hInstance = proc, GetModuleHandleW(None)
    wc.hCursor, wc.hbrBackground = LoadCursorW(None, 32512), 16
    wc.lpszClassName = "WinShellSetup"
    RegisterClassW(ctypes.byref(wc))
    w, h = 640, 130 + 24 * len(OPTIONS) + 190
    hwnd = CreateWindowExW(0, "WinShellSetup", "WinShell Setup %s" % VERSION,
                           0x00C80000 | 0x10000000, 80, 30, w, h, None, None, GetModuleHandleW(None), None)
    child("STATIC", "Install folder:", 0, 16, 16, 120, 20, 0, hwnd)
    state["dir"] = child("EDIT", DEFAULT_DIR, 0x80, 130, 12, 480, 24, 100, hwnd, 0x200)
    y = 52
    for key, label, default in OPTIONS:
        box = child("BUTTON", label, 0x3 | 0x10000, 16, y, 600, 22, 110, hwnd)
        SendMessageW(box, 0xF1, 1 if default else 0, 0)
        state["boxes"][key] = box
        y += 24
    state["log"] = child("EDIT", "", 0x4 | 0x40 | 0x800 | 0x200000, 16, y + 8, 600, 130, 120, hwnd, 0x200)
    child("BUTTON", "Install", 0x10000, 16, y + 148, 110, 30, 101, hwnd)
    child("BUTTON", "Uninstall", 0x10000, 136, y + 148, 110, 30, 102, hwnd)
    child("BUTTON", "Close", 0x10000, 506, y + 148, 110, 30, 103, hwnd)
    msg = wt.MSG()
    while GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        TranslateMessage(ctypes.byref(msg))
        DispatchMessageW(ctypes.byref(msg))


def main():
    args = sys.argv[1:]
    install_dir = DEFAULT_DIR
    if "--dir" in args and args.index("--dir") + 1 < len(args):
        install_dir = args[args.index("--dir") + 1]
    if "--uninstall" in args:
        uninstall(install_dir, print, remove_settings="--purge" in args)
        return
    if "--silent" in args:
        opts = {k: d for k, _l, d in OPTIONS}
        install(opts, install_dir, print)
        return
    run_gui()


if __name__ == "__main__":
    main()

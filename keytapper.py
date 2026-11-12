# -*- coding: utf-8 -*-
"""KeyTapper 键盘连点器

按设定的间隔自动连点键盘按键 / 组合键（也支持鼠标键），支持多步循环序列、
延迟开始、限定时长或轮数、全局启停热键、方案保存与导入导出。按键通过系统级
SendInput 发送到当前前台窗口，所以在游戏、浏览器等其他程序里同样生效。
"""
import ctypes
import json
import os
import random
import sys
import threading
import time
import tkinter as tk
import winsound
from ctypes import wintypes
from tkinter import filedialog, ttk

from PIL import Image, ImageDraw, ImageTk

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ASSET_DIR = os.path.join(APP_DIR, "assets")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
TITLE = "KeyTapper 键盘连点器"

# ───────────────────────── 系统按键发送 ─────────────────────────

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
winmm = ctypes.WinDLL("winmm")
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]

VK_SHIFT, VK_CTRL, VK_ALT, VK_WIN = 16, 17, 18, 91
MODS = [VK_CTRL, VK_SHIFT, VK_ALT, VK_WIN]            # 显示与按下的顺序
MOUSE_FLAGS = {1: (0x0002, 0x0004), 2: (0x0008, 0x0010), 4: (0x0020, 0x0040)}
EXTENDED = {33, 34, 35, 36, 37, 38, 39, 40, 44, 45, 46, 91, 92, 111, 144}

KEY_NAMES = {
    1: "鼠标左键", 2: "鼠标右键", 4: "鼠标中键",
    8: "Backspace", 9: "Tab", 13: "Enter", 16: "Shift", 17: "Ctrl", 18: "Alt",
    19: "Pause", 20: "CapsLock", 27: "Esc", 32: "空格", 33: "PageUp",
    34: "PageDown", 35: "End", 36: "Home", 37: "←", 38: "↑", 39: "→", 40: "↓",
    44: "PrtSc", 45: "Insert", 46: "Delete", 91: "Win", 93: "Menu",
    106: "Num *", 107: "Num +", 109: "Num -", 110: "Num .", 111: "Num /",
    144: "NumLock", 145: "ScrollLock", 186: ";", 187: "=", 188: ",", 189: "-",
    190: ".", 191: "/", 192: "`", 219: "[", 220: "\\", 221: "]", 222: "'",
}
for _c in range(48, 58):
    KEY_NAMES[_c] = chr(_c)
for _c in range(65, 91):
    KEY_NAMES[_c] = chr(_c)
for _c in range(96, 106):
    KEY_NAMES[_c] = "Num %d" % (_c - 96)
for _c in range(112, 136):
    KEY_NAMES[_c] = "F%d" % (_c - 111)


def key_name(vk):
    return KEY_NAMES.get(vk, "键码 %d" % vk)


def combo_text(combo):
    if not combo:
        return "未设置"
    return " + ".join([key_name(m) for m in combo.get("mods", [])] + [key_name(combo["key"])])


def is_down(vk):
    if vk == VK_WIN:
        return bool((user32.GetAsyncKeyState(91) | user32.GetAsyncKeyState(92)) & 0x8000)
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


SEND_SCANCODE = True      # True：游戏兼容（扫描码）；False：普通（虚拟键码）


def send_key(vk, up=False):
    """按下或松开一个键。"""
    inp = INPUT()
    if vk in MOUSE_FLAGS:
        inp.type = 0
        inp.mi.dwFlags = MOUSE_FLAGS[vk][1 if up else 0]
    else:
        inp.type = 1
        scan = user32.MapVirtualKeyW(vk, 0)
        flags = (0x0001 if vk in EXTENDED else 0) | (0x0002 if up else 0)
        if SEND_SCANCODE and scan:
            # 纯扫描码方式：读取硬件扫描码的游戏（DirectInput / RawInput）也能识别
            inp.ki.wScan = scan
            flags |= 0x0008
        else:
            inp.ki.wVk = vk
            inp.ki.wScan = scan
        inp.ki.dwFlags = flags
    return user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


# ───────────────────────── 连点引擎 ─────────────────────────

class Tapper:
    """后台线程：按配置循环发送按键。"""

    def __init__(self):
        self.stop_evt = threading.Event()
        self.thread = None
        self.state = "idle"          # idle / countdown / running
        self.count = 0               # 已按次数
        self.rounds = 0              # 已完成轮数
        self.start_at = 0.0          # 倒计时结束时刻
        self.t_begin = 0.0           # 真正开始连点的时刻
        self.t_end = 0.0
        self.deadline = None

    def alive(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, job):
        if self.alive():
            return
        self.stop_evt.clear()
        self.count = self.rounds = 0
        self.deadline = None
        self.t_begin = self.t_end = 0.0
        self.start_at = time.perf_counter() + job["delay_s"]
        self.state = "countdown"
        self.thread = threading.Thread(target=self._run, args=(job,), daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_evt.set()

    def _wait_until(self, t):
        """精确等待到时刻 t；期间被停止则返回 True。"""
        while True:
            rem = t - time.perf_counter()
            if rem <= 0:
                return self.stop_evt.is_set()
            if rem > 0.003:
                if self.stop_evt.wait(min(rem - 0.002, 0.05)):
                    return True
            elif self.stop_evt.is_set():
                return True

    def _press(self, step, hold_s):
        held = []
        try:
            for vk in list(step.get("mods", [])) + [step["key"]]:
                send_key(vk)
                held.append(vk)
            self._wait_until(time.perf_counter() + hold_s)
        finally:
            for vk in reversed(held):
                send_key(vk, up=True)

    def _run(self, job):
        winmm.timeBeginPeriod(1)
        try:
            if self._wait_until(self.start_at):
                return
            self.t_begin = time.perf_counter()
            self.state = "running"
            if job["duration_s"]:
                self.deadline = self.t_begin + job["duration_s"]
            hold_s = job["hold_ms"] / 1000.0
            jitter = job["jitter_ms"]
            n = len(job["steps"])
            sched = self.t_begin
            while True:
                for i, step in enumerate(job["steps"]):
                    if self.deadline and time.perf_counter() >= self.deadline:
                        return
                    self._press(step, hold_s)
                    self.count += 1
                    if i == n - 1:
                        self.rounds += 1
                        if job["max_rounds"] and self.rounds >= job["max_rounds"]:
                            return
                    gap = step["gap_ms"]
                    if jitter:
                        gap = max(1.0, gap + random.uniform(-jitter, jitter))
                    sched = max(sched + gap / 1000.0, time.perf_counter())
                    target = min(sched, self.deadline) if self.deadline else sched
                    if self._wait_until(target):
                        return
        finally:
            self.t_end = time.perf_counter()
            self.state = "idle"
            winmm.timeEndPeriod(1)


# ───────────────────────── 配置 ─────────────────────────

GAP_UNITS = {"毫秒": 1, "秒": 1000, "分钟": 60000}
DUR_UNITS = {"秒": 1, "分钟": 60, "小时": 3600}
SEND_MODES = {"游戏兼容": "scan", "普通": "vk"}

DEFAULT_CFG = {
    # 每一步：{"mods": [...], "key": vk, "times": 连按次数, "interval": 数值或 None, "unit": "毫秒"}
    "steps": [],
    "interval": 100, "interval_unit": "毫秒",
    "jitter_ms": 0, "hold_ms": 50, "delay_s": 0,
    "stop_mode": "forever",           # forever / duration / rounds
    "duration": 60, "duration_unit": "秒", "rounds": 10,
    "hotkey": {"mods": [], "key": 117},   # F6
    "topmost": False,
    "sound": True,
    "send_mode": "scan",              # scan：游戏兼容；vk：普通
    "presets": {},                    # 方案名 -> 方案内容
    "preset": "",                     # 当前选中的方案名
    "window": "",                     # 上次的窗口位置
}

PRESET_KEYS = ["steps", "interval", "interval_unit", "jitter_ms", "hold_ms", "delay_s",
               "stop_mode", "duration", "duration_unit", "rounds"]


def sanitize_preset(d):
    """校验并规整一个方案（来自导入的文件或已保存的配置）；不合法时抛 ValueError。"""
    try:
        out = json.loads(json.dumps({k: DEFAULT_CFG[k] for k in PRESET_KEYS}))
        steps = []
        for s in d["steps"]:
            key = int(s["key"])
            if not 1 <= key <= 254:
                raise ValueError
            iv = s.get("interval")
            unit = s.get("unit") if s.get("unit") in GAP_UNITS else "毫秒"
            if iv is not None:
                iv = float(iv)
                if iv * GAP_UNITS[unit] < 1:
                    iv = None
            steps.append({"mods": [m for m in MODS if m in (s.get("mods") or [])], "key": key,
                          "times": min(999, max(1, int(s.get("times") or 1))),
                          "interval": iv, "unit": unit})
        out["steps"] = steps
        for k in ("interval", "jitter_ms", "hold_ms", "delay_s", "duration"):
            if k in d and float(d[k]) >= 0:
                out[k] = float(d[k])
        if "rounds" in d and int(d["rounds"]) >= 1:
            out["rounds"] = int(d["rounds"])
        if d.get("interval_unit") in GAP_UNITS:
            out["interval_unit"] = d["interval_unit"]
        if d.get("duration_unit") in DUR_UNITS:
            out["duration_unit"] = d["duration_unit"]
        if d.get("stop_mode") in ("forever", "duration", "rounds"):
            out["stop_mode"] = d["stop_mode"]
        return out
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError("方案文件格式不正确，无法读取。")


def load_cfg(path):
    cfg = json.loads(json.dumps(DEFAULT_CFG))
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in cfg})
        cfg.update(sanitize_preset(cfg))
        cfg["presets"] = {str(k): sanitize_preset(v) for k, v in dict(cfg["presets"]).items()}
    except (OSError, ValueError, TypeError):
        pass
    return cfg


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def ensure_admin():
    """不是管理员时请求提权并重新启动自己；用户拒绝则以普通权限继续。"""
    if is_admin():
        return True
    if "--elevated" in sys.argv or "--no-elevate" in sys.argv:
        return False
    params = '"%s" --elevated' % os.path.abspath(__file__)
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, APP_DIR, 1)
    if ret > 32:
        sys.exit(0)
    return False


def fmt_num(x):
    x = float(x)
    return str(int(x)) if x == int(x) else ("%g" % x)


def fmt_time(sec):
    sec = max(0, int(sec))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return "%d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)


def beep(freq, ms):
    threading.Thread(target=lambda: winsound.Beep(freq, ms), daemon=True).start()


# ───────────────────────── 界面：配色与绘图 ─────────────────────────

BG, CARD, INSET = "#0E1016", "#171A23", "#11131A"
FIELD, FIELD_HI, FIELD_OFF, BORDER = "#222634", "#2B3041", "#1B1E29", "#2A2F3D"
TEXT, SUB, MUTED = "#E9EBF2", "#9097AA", "#5D6478"
ACCENT, ACCENT_HI, ACCENT_LO, ACCENT_OFF = "#6D6BFF", "#8381FF", "#5856DB", "#2C2E55"
OK, WARN, DANGER = "#34D399", "#FBBF24", "#F4567A"
GRAD_START, GRAD_STOP = ("#6D5BFF", "#22C8EE"), ("#F0476A", "#FF9A4C")
FONT = "Microsoft YaHei UI"


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def dark_titlebar(win, color=BG):
    """让标题栏跟窗口同色（Windows 11），旧系统上至少切到深色标题栏。"""
    try:
        win.update_idletasks()
        hwnd = user32.GetParent(win.winfo_id())
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), 20, ctypes.byref(on), 4)
        r, g, b = hex_rgb(color)
        ref = ctypes.c_int(r | (g << 8) | (b << 16))
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), 35, ctypes.byref(ref), 4)
    except Exception:
        pass


class Gfx:
    """用 PIL 画抗锯齿的圆角控件贴图。尺寸参数都是 100% 缩放下的逻辑像素。"""
    SS = 4

    def __init__(self, scale):
        self.k = scale
        self.keep = []

    def px(self, n):
        return max(1, int(round(n * self.k)))

    def tk(self, im):
        photo = ImageTk.PhotoImage(im)
        self.keep.append(photo)
        return photo

    def canvas(self, w, h, bg):
        im = Image.new("RGB", (self.px(w) * self.SS, self.px(h) * self.SS), bg)
        return im, ImageDraw.Draw(im), self.px(1) * self.SS

    def done(self, im):
        return im.resize((im.width // self.SS, im.height // self.SS), Image.LANCZOS)

    def rr(self, w, h, r, fill, bg, outline=None):
        im, d, u = self.canvas(w, h, bg)
        W, H, R = im.width - 1, im.height - 1, self.px(r) * self.SS
        d.rounded_rectangle((0, 0, W, H), R, fill=outline or fill)
        if outline:
            d.rounded_rectangle((u, u, W - u, H - u), max(0, R - u), fill=fill)
        return self.done(im)

    def radio(self, on, enabled=True):
        im, d, u = self.canvas(26, 18, CARD)
        ring = (ACCENT if on else MUTED) if enabled else BORDER
        d.ellipse((u, u, 17 * u, 17 * u), fill=ring)
        d.ellipse((2.6 * u, 2.6 * u, 15.4 * u, 15.4 * u), fill=FIELD if enabled else FIELD_OFF)
        if on:
            d.ellipse((5.4 * u, 5.4 * u, 12.6 * u, 12.6 * u), fill=ACCENT if enabled else MUTED)
        return self.done(im)

    def switch(self, on):
        im, d, u = self.canvas(44, 20, CARD)
        d.rounded_rectangle((0, 0, 36 * u, 20 * u), 10 * u, fill=ACCENT if on else FIELD_HI)
        x = 18 * u if on else 2 * u
        d.ellipse((x, 2 * u, x + 16 * u, 18 * u), fill="#FFFFFF" if on else SUB)
        return self.done(im)

    def chevron(self, color, bg):
        im, d, u = self.canvas(24, 10, bg)
        d.line((5 * u, 2.5 * u, 10 * u, 7.5 * u, 15 * u, 2.5 * u), fill=color, width=int(1.7 * u), joint="curve")
        return self.done(im)

    def gradient_button(self, w, h, colors, gain):
        """实际像素尺寸的渐变圆角按钮底图。"""
        c1, c2 = (tuple(min(255, int(v * gain)) for v in hex_rgb(c)) for c in colors)
        strip = Image.new("RGB", (256, 1))
        strip.putdata([tuple(int(a + (b - a) * i / 255) for a, b in zip(c1, c2)) for i in range(256)])
        mask = Image.new("L", (w * self.SS, h * self.SS), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w * self.SS - 1, h * self.SS - 1),
                                               self.px(13) * self.SS, fill=255)
        base = Image.new("RGB", (w, h), BG)
        base.paste(strip.resize((w, h)), (0, 0), mask.resize((w, h), Image.LANCZOS))
        return base


class BigButton(tk.Canvas):
    """渐变主按钮。"""

    def __init__(self, parent, app, command):
        super().__init__(parent, height=app.S(52), bg=BG, highlightthickness=0, cursor="hand2", takefocus=0)
        self.app, self.command = app, command
        self.mode, self.text, self.hot = "start", "", ""
        self.hover = self.down = False
        self.cache = {}
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False, down=False))
        self.bind("<ButtonPress-1>", lambda e: self._set(down=True))
        self.bind("<ButtonRelease-1>", self._release)

    def _set(self, **kw):
        self.__dict__.update(kw)
        self.redraw()

    def _release(self, _):
        fire = self.down and self.hover
        self._set(down=False)
        if fire:
            self.command()

    def set(self, mode, text, hot):
        self.mode, self.text, self.hot = mode, text, hot
        self.redraw()

    def redraw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20:
            return
        gain = 0.88 if self.down else 1.1 if self.hover else 1.0
        key = (w, h, self.mode, gain)
        if key not in self.cache:
            colors = GRAD_START if self.mode == "start" else GRAD_STOP
            self.cache[key] = ImageTk.PhotoImage(self.app.gfx.gradient_button(w, h, colors, gain))
        self.delete("all")
        self.create_image(0, 0, anchor="nw", image=self.cache[key])
        self.create_text(w // 2, h // 2, text=self.text, fill="#FFFFFF", font=(FONT, 13, "bold"))
        self.create_text(w - self.app.S(22), h // 2, anchor="e", text=self.hot, fill="#EEF1FF",
                         font=(FONT, 10, "bold"))


# ───────────────────────── 界面：对话框 ─────────────────────────

class Dialog(tk.Toplevel):
    def __init__(self, app, title):
        super().__init__(app.root)
        self.app, self.S = app, app.S
        self.result = None
        self.withdraw()
        self.title(title)
        self.configure(bg=CARD, padx=self.S(22), pady=self.S(20))
        self.resizable(False, False)
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def present(self):
        self.update_idletasks()
        root = self.app.root
        x = root.winfo_rootx() + (root.winfo_width() - self.winfo_reqwidth()) // 2
        y = root.winfo_rooty() + self.S(110)
        self.geometry("+%d+%d" % (max(0, x), max(0, y)))
        dark_titlebar(self, CARD)
        self.deiconify()

    def show(self):
        self.app.dialog_open = True
        try:
            self.present()
            self.grab_set()
            self.on_shown()
            self.wait_window()
        finally:
            self.app.dialog_open = False
        return self.result

    def on_shown(self):
        pass

    def buttons(self, row, ok_text="确定", cancel=True):
        f = tk.Frame(self, bg=CARD)
        f.grid(row=row, column=0, columnspan=3, sticky="e", pady=(self.S(20), 0))
        if cancel:
            ttk.Button(f, text="取消", style="Ghost.TButton", takefocus=0,
                       command=self.destroy).pack(side="left", padx=(0, self.S(8)))
        ttk.Button(f, text=ok_text, style="Accent.TButton", takefocus=0, command=self.ok).pack(side="left")

    def ok(self):
        self.result = True
        self.destroy()


class MsgDialog(Dialog):
    """提示 / 确认 / 输入一行文字。"""

    def __init__(self, app, title, text, kind="info", initial="", ok_text="确定"):
        super().__init__(app, title)
        self.kind = kind
        tk.Label(self, text=text, bg=CARD, fg=TEXT, justify="left", anchor="w",
                 wraplength=self.S(340)).grid(row=0, column=0, columnspan=3, sticky="w")
        self.var = tk.StringVar(value=initial)
        self.entry = None
        if kind == "input":
            self.entry = ttk.Entry(self, textvariable=self.var, width=30)
            self.entry.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(self.S(12), 0))
        self.columnconfigure(0, minsize=self.S(300))
        self.buttons(2, ok_text=ok_text, cancel=kind != "info")
        self.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.destroy())

    def on_shown(self):
        if self.entry:
            self.entry.focus_set()
            self.entry.select_range(0, "end")
        else:
            self.focus_set()

    def ok(self):
        self.result = self.var.get() if self.kind == "input" else True
        self.destroy()


class StepDialog(Dialog):
    """录制一个按键 / 组合键；可选地设置连按次数和该步之后的间隔。"""

    def __init__(self, app, title, step=None, for_hotkey=False):
        super().__init__(app, title)
        S = self.S
        self.for_hotkey = for_hotkey
        self.combo = {"mods": list(step.get("mods", [])), "key": step["key"]} if step else None
        self.capturing = False
        interval = step.get("interval") if step else None

        tk.Label(self, text="快捷键" if for_hotkey else "按键 / 组合键", bg=CARD, fg=SUB,
                 font=(FONT, 9)).grid(row=0, column=0, columnspan=3, sticky="w")
        box = ttk.Frame(self, style="Inset.TFrame", padding=S(3))
        box.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(S(6), S(10)))
        self.key_lbl = tk.Label(box, text=combo_text(self.combo), bg=INSET, fg=TEXT,
                                font=(FONT, 16, "bold"), width=20, height=2)
        self.key_lbl.pack(fill="both")

        self.rec_btn = ttk.Button(self, text="录制按键", style="Accent.TButton", takefocus=0,
                                  command=self.start_capture)
        self.rec_btn.grid(row=2, column=0, sticky="w")
        self.mouse_var = tk.StringVar(value="或选择鼠标键")
        if not for_hotkey:
            cb = ttk.Combobox(self, textvariable=self.mouse_var, state="readonly", width=12,
                              takefocus=0, values=["鼠标左键", "鼠标右键", "鼠标中键"])
            cb.grid(row=2, column=1, columnspan=2, sticky="e")
            cb.bind("<<ComboboxSelected>>", self._pick_mouse)
        tk.Label(self, text="点「录制按键」后直接按下想要的键；组合键请同时按住，例如 Shift + A。",
                 bg=CARD, fg=SUB, font=(FONT, 9), wraplength=S(330), justify="left"
                 ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(S(10), 0))

        self.times_var = tk.StringVar(value=str(step.get("times", 1)) if step else "1")
        self.mode_var = tk.StringVar(value="default" if interval is None else "custom")
        self.gap_var = tk.StringVar(value=fmt_num(interval) if interval is not None else "5")
        self.unit_var = tk.StringVar(value=step.get("unit", "毫秒") if interval is not None else "秒")
        if not for_hotkey:
            tk.Frame(self, bg=BORDER, height=1).grid(row=4, column=0, columnspan=3, sticky="ew", pady=S(16))
            row = tk.Frame(self, bg=CARD)
            row.grid(row=5, column=0, columnspan=3, sticky="w")
            tk.Label(row, text="连按", bg=CARD, fg=TEXT).pack(side="left")
            ttk.Entry(row, textvariable=self.times_var, width=5, justify="center").pack(side="left", padx=S(8))
            tk.Label(row, text="次，再进入下一步", bg=CARD, fg=TEXT).pack(side="left")
            tk.Label(self, text="每按一次之后的等待时间", bg=CARD, fg=SUB, font=(FONT, 9)
                     ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(S(14), 0))
            ttk.Radiobutton(self, text="使用默认间隔", variable=self.mode_var, value="default",
                            takefocus=0, command=self._sync).grid(row=7, column=0, columnspan=3,
                                                                  sticky="w", pady=(S(8), 0))
            row = tk.Frame(self, bg=CARD)
            row.grid(row=8, column=0, columnspan=3, sticky="w", pady=(S(6), 0))
            ttk.Radiobutton(row, text="自定义", variable=self.mode_var, value="custom",
                            takefocus=0, command=self._sync).pack(side="left")
            self.gap_entry = ttk.Entry(row, textvariable=self.gap_var, width=8, justify="center")
            self.gap_entry.pack(side="left", padx=S(8))
            self.unit_cb = ttk.Combobox(row, textvariable=self.unit_var, state="readonly",
                                        width=5, values=list(GAP_UNITS), takefocus=0)
            self.unit_cb.pack(side="left")
            self._sync()
        self.buttons(9)

    def on_shown(self):
        if self.combo is None:
            self.after(150, self.start_capture)

    def _sync(self):
        on = self.mode_var.get() == "custom"
        self.gap_entry.configure(state="normal" if on else "disabled")
        self.unit_cb.configure(state="readonly" if on else "disabled")

    def _pick_mouse(self, _=None):
        self.capturing = False
        vk = {"鼠标左键": 1, "鼠标右键": 2, "鼠标中键": 4}[self.mouse_var.get()]
        self.combo = {"mods": [], "key": vk}
        self.key_lbl.configure(text=combo_text(self.combo), fg=TEXT)
        self.rec_btn.configure(text="录制按键")

    # 用轮询键盘物理状态的方式录制，不受输入法影响
    def start_capture(self):
        if self.capturing:
            return
        self.capturing, self._ready, self._mods = True, False, []
        self.key_lbl.configure(text="请按下按键…", fg=ACCENT_HI)
        self.rec_btn.configure(text="录制中…")
        self.key_lbl.focus_set()
        self._poll()

    def _poll(self):
        if not self.capturing or not self.winfo_exists():
            return
        mods = [m for m in MODS if is_down(m)]
        keys = [vk for vk in range(8, 255)
                if vk not in (16, 17, 18, 91, 92, 160, 161, 162, 163, 164, 165, 229)
                and user32.GetAsyncKeyState(vk) & 0x8000]
        if not self._ready:
            self._ready = not mods and not keys      # 等之前的按键全部松开
        elif keys:
            return self._finish({"mods": mods, "key": keys[0]})
        elif mods:
            if len(mods) >= len(self._mods):
                self._mods = mods
            self.key_lbl.configure(text=" + ".join(key_name(m) for m in mods) + " + …")
        elif self._mods:                              # 只按了修饰键就松开
            return self._finish({"mods": self._mods[:-1], "key": self._mods[-1]})
        self.after(15, self._poll)

    def _finish(self, combo):
        self.capturing = False
        self.combo = combo
        self.mouse_var.set("或选择鼠标键")
        self.key_lbl.configure(text=combo_text(combo), fg=TEXT)
        self.rec_btn.configure(text="重新录制")

    def _error(self, text):
        self.key_lbl.configure(text=text, fg=DANGER, font=(FONT, 11, "bold"))
        self.after(1600, lambda: self.winfo_exists() and self.key_lbl.configure(
            text=combo_text(self.combo), fg=TEXT, font=(FONT, 16, "bold")))

    def ok(self):
        if self.capturing:
            return
        if not self.combo:
            return self._error("请先录制一个按键")
        res = {"mods": list(self.combo["mods"]), "key": self.combo["key"], "times": 1,
               "interval": None, "unit": "毫秒"}
        if not self.for_hotkey:
            try:
                res["times"] = int(self.times_var.get().strip())
                if not 1 <= res["times"] <= 999:
                    raise ValueError
            except ValueError:
                return self._error("连按次数需要是 1–999 的整数")
            if self.mode_var.get() == "custom":
                try:
                    v = float(self.gap_var.get().strip())
                    if v * GAP_UNITS[self.unit_var.get()] < 1:
                        raise ValueError
                except ValueError:
                    return self._error("自定义间隔不能小于 1 毫秒")
                res["interval"], res["unit"] = v, self.unit_var.get()
        self.result = res
        self.destroy()


# ───────────────────────── 界面：主窗口 ─────────────────────────

class App:
    def __init__(self, cfg_path=CONFIG_PATH, admin=None):
        self.admin = is_admin() if admin is None else admin
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("KeyTapper.App")
        except Exception:
            pass
        self.cfg_path = cfg_path
        self.cfg = load_cfg(cfg_path)
        self.tapper = Tapper()
        self.job = None
        self.dialog_open = False
        self.hk_prev = True
        self.ui_running = False
        self.prev_state = "idle"
        self.flash = ("", 0.0)
        self.inputs = []

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(TITLE)
        self.root.configure(bg=BG)
        ico = os.path.join(ASSET_DIR, "keytapper.ico")
        if os.path.exists(ico):
            try:
                self.root.iconbitmap(default=ico)
            except tk.TclError:
                pass
        scale = self.root.winfo_fpixels("1i") / 96.0
        self.S = lambda n: int(round(n * scale))
        self.gfx = Gfx(scale)
        self._style()
        self._build()
        self._refresh_steps()
        self._sync_stop_mode()
        self._apply_topmost()
        self.root.update_idletasks()
        self.root.minsize(self.root.winfo_reqwidth(), self.root.winfo_reqheight())
        self._restore_position()
        dark_titlebar(self.root, BG)
        self.root.deiconify()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._tick()

    # ── 样式 ──
    def _style(self):
        S, g = self.S, self.gfx
        font = (FONT, 10)
        self.root.option_add("*Font", font)
        for k, v in (("font", font), ("background", FIELD), ("foreground", TEXT), ("selectBackground", ACCENT),
                     ("selectForeground", "#FFFFFF"), ("borderWidth", 0), ("relief", "flat")):
            self.root.option_add("*TCombobox*Listbox." + k, v)
        st = ttk.Style(self.root)
        st.theme_use("clam")
        st.configure(".", font=font, background=CARD, foreground=TEXT, borderwidth=0, focuscolor=CARD)

        def nine(name, r, bg, default, *states):
            """九宫格圆角贴图元素。default 与每个状态都是 (填充色, 描边色)。"""
            def mk(fill, outline):
                return g.tk(g.rr(2 * r + 8, 2 * r + 8, r, fill, bg, outline))
            args = [mk(*default)] + [tuple(s[0]) + (mk(s[1], s[2]),) for s in states]
            st.element_create(name, "image", *args, border=g.px(r) + 2, padding=0, sticky="nsew")

        def wrap(bg_element, kind):
            return [(bg_element, {"sticky": "nsew", "children": [
                (kind + ".padding", {"sticky": "nsew", "children": [(kind + ".label", {"sticky": "nsew"})]})]})]

        # 卡片 / 内嵌区域
        nine("Card.bg", 12, BG, (CARD, None))
        st.layout("Card.TFrame", [("Card.bg", {"sticky": "nsew"})])
        st.configure("Card.TFrame", background=BG)
        nine("Inset.bg", 9, CARD, (INSET, BORDER))
        st.layout("Inset.TFrame", [("Inset.bg", {"sticky": "nsew"})])

        # 按钮
        def button(prefix, normal, hover, press, disabled, fg, fg_dis):
            nine(prefix + ".bg", 8, CARD, (normal, None), (("disabled",), disabled, None),
                 (("pressed",), press, None), (("active",), hover, None))
            st.layout(prefix + ".TButton", wrap(prefix + ".bg", "Button"))
            st.configure(prefix + ".TButton", foreground=fg, background=CARD, padding=(S(13), S(6)),
                         anchor="center", width=0)
            st.map(prefix + ".TButton", foreground=[("disabled", fg_dis)])
        button("Ghost", FIELD, FIELD_HI, FIELD_OFF, FIELD_OFF, TEXT, MUTED)
        button("Accent", ACCENT, ACCENT_HI, ACCENT_LO, ACCENT_OFF, "#FFFFFF", "#7C80A6")

        # 输入框 / 下拉框
        field_states = ((("disabled",), FIELD_OFF, None), (("focus",), FIELD, ACCENT))
        nine("Field.bg", 8, CARD, (FIELD, None), *field_states)
        st.layout("TEntry", [("Field.bg", {"sticky": "nsew", "children": [
            ("Entry.padding", {"sticky": "nsew", "children": [("Entry.textarea", {"sticky": "nsew"})]})]})])
        st.configure("TEntry", foreground=TEXT, insertcolor=TEXT, fieldbackground=FIELD, padding=(S(8), S(6)),
                     selectbackground=ACCENT, selectforeground="#FFFFFF")
        st.map("TEntry", foreground=[("disabled", MUTED)], fieldbackground=[("disabled", FIELD_OFF)])
        nine("Combo.bg", 8, CARD, (FIELD, None), (("disabled",), FIELD_OFF, None))
        st.element_create("Combo.arrow", "image", g.tk(g.chevron(SUB, FIELD)),
                          ("disabled", g.tk(g.chevron(MUTED, FIELD_OFF))), sticky="")
        st.layout("TCombobox", [("Combo.bg", {"sticky": "nsew", "children": [
            ("Combo.arrow", {"side": "right", "sticky": ""}),
            ("Combobox.padding", {"sticky": "nsew", "children": [("Combobox.textarea", {"sticky": "nsew"})]})]})])
        st.configure("TCombobox", foreground=TEXT, fieldbackground=FIELD, padding=(S(8), S(6), 0, S(6)),
                     selectbackground=FIELD, selectforeground=TEXT)
        st.map("TCombobox", foreground=[("disabled", MUTED)],
               fieldbackground=[("disabled", FIELD_OFF), ("readonly", FIELD)],
               selectbackground=[("disabled", FIELD_OFF), ("readonly", FIELD)],
               selectforeground=[("disabled", MUTED), ("readonly", TEXT)])

        # 单选 / 开关
        st.element_create("Radio.ind", "image", g.tk(g.radio(False)),
                          ("disabled", "selected", g.tk(g.radio(True, False))),
                          ("disabled", g.tk(g.radio(False, False))),
                          ("selected", g.tk(g.radio(True))), sticky="")
        st.layout("TRadiobutton", [("Radiobutton.padding", {"sticky": "nsew", "children": [
            ("Radio.ind", {"side": "left", "sticky": ""}), ("Radiobutton.label", {"side": "left", "sticky": "nsew"})]})])
        st.configure("TRadiobutton", background=CARD, foreground=TEXT, padding=(0, S(2)))
        st.map("TRadiobutton", foreground=[("disabled", MUTED)], background=[("active", CARD)])
        st.element_create("Switch.ind", "image", g.tk(g.switch(False)), ("selected", g.tk(g.switch(True))), sticky="")
        st.layout("Switch.TCheckbutton", [("Checkbutton.padding", {"sticky": "nsew", "children": [
            ("Switch.ind", {"side": "right", "sticky": ""}), ("Checkbutton.label", {"side": "left", "sticky": "nsew"})]})])
        st.configure("Switch.TCheckbutton", background=CARD, foreground=TEXT, padding=(0, S(2)))
        st.map("Switch.TCheckbutton", background=[("active", CARD)])

        # 状态胶囊 / 按键标签
        for name, fill, fg, bg in (("Idle", "#1D202B", SUB, BG), ("Run", "#12332A", OK, BG),
                                   ("Wait", "#3A2F12", WARN, BG), ("Chip", FIELD, ACCENT_HI, CARD)):
            nine(name + ".bg", 11, bg, (fill, None))
            st.layout(name + ".TLabel", wrap(name + ".bg", "Label"))
            st.configure(name + ".TLabel", foreground=fg, background=bg, padding=(S(11), S(3)),
                         font=(FONT, 9, "bold"), anchor="center")

        # 列表
        st.layout("Treeview", [("Treeview.treearea", {"sticky": "nsew"})])
        st.configure("Treeview", background=INSET, fieldbackground=INSET, foreground=TEXT, rowheight=S(30))
        st.map("Treeview", background=[("selected", "#2B2D5E")], foreground=[("selected", "#FFFFFF")])
        st.configure("Treeview.Heading", background=INSET, foreground=MUTED, relief="flat", font=(FONT, 9),
                     padding=(S(6), S(5)), bordercolor=INSET, lightcolor=INSET, darkcolor=INSET)
        st.map("Treeview.Heading", background=[("active", INSET)])
        st.layout("Slim.Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nsew"})]})])
        st.configure("Slim.Vertical.TScrollbar", troughcolor=INSET, background="#343A4D", bordercolor=INSET,
                     lightcolor="#343A4D", darkcolor="#343A4D", gripcount=0, arrowsize=S(8))
        st.map("Slim.Vertical.TScrollbar", background=[("active", "#454C63")])

    # ── 小部件工厂 ──
    def _card(self, parent, title=None, desc=None, expand=False):
        S = self.S
        card = ttk.Frame(parent, style="Card.TFrame", padding=(S(16), S(13)))
        card.pack(fill="both" if expand else "x", expand=expand, pady=(0, S(10)))
        if title:
            head = tk.Frame(card, bg=CARD)
            head.pack(fill="x", pady=(0, S(9)))
            tk.Label(head, text=title, bg=CARD, fg=TEXT, font=(FONT, 10, "bold")).pack(side="left")
            if desc:
                tk.Label(head, text=desc, bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left", padx=S(10))
        return card

    def _label(self, parent, text, fg=TEXT, **kw):
        return tk.Label(parent, text=text, bg=CARD, fg=fg, **kw)

    def _entry(self, parent, var, width=7):
        e = ttk.Entry(parent, textvariable=var, width=width, justify="center")
        self.inputs.append(e)
        return e

    def _combo(self, parent, var, values, width=5):
        cb = ttk.Combobox(parent, textvariable=var, state="readonly", width=width, values=values, takefocus=0)
        self.inputs.append(cb)
        return cb

    def _field(self, parent, label, var, suffix=None):
        f = tk.Frame(parent, bg=CARD)
        self._label(f, label, fg=SUB, width=8, anchor="w").pack(side="left")
        self._entry(f, var).pack(side="left")
        if suffix:
            self._label(f, suffix, fg=MUTED).pack(side="left", padx=(self.S(8), 0))
        return f

    # ── 布局 ──
    def _build(self):
        S, c = self.S, self.cfg
        main = tk.Frame(self.root, bg=BG, padx=S(18), pady=S(14))
        main.pack(fill="both", expand=True)
        tk.Frame(main, bg=BG, width=S(612), height=0).pack()      # 撑出最小宽度

        # 顶部：标志、标题、状态
        head = tk.Frame(main, bg=BG)
        head.pack(fill="x", pady=(0, S(12)))
        logo = os.path.join(ASSET_DIR, "icon.png")
        if os.path.exists(logo):
            im = Image.open(logo).convert("RGBA").resize((S(42), S(42)), Image.LANCZOS)
            base = Image.new("RGBA", im.size, BG)
            base.alpha_composite(im)
            tk.Label(head, image=self.gfx.tk(base.convert("RGB")), bg=BG).pack(side="left", padx=(0, S(12)))
        titles = tk.Frame(head, bg=BG)
        titles.pack(side="left")
        tk.Label(titles, text="键盘连点器", bg=BG, fg=TEXT, font=(FONT, 15, "bold")).pack(anchor="w")
        tk.Label(titles, text="管理员模式 · 可作用于游戏" if self.admin else "普通权限 · 管理员运行的游戏里会失效",
                 bg=BG, fg=MUTED if self.admin else DANGER, font=(FONT, 9)).pack(anchor="w")
        self.pill = ttk.Label(head, text="待机", style="Idle.TLabel")
        self.pill.pack(side="right")

        # 方案
        card = self._card(main)
        self._label(card, "方案", fg=SUB).pack(side="left")
        self.v_preset = tk.StringVar(value=c["preset"] if c["preset"] in c["presets"] else "")
        self.preset_cb = ttk.Combobox(card, textvariable=self.v_preset, state="readonly", width=15,
                                      takefocus=0, values=list(c["presets"]))
        self.preset_cb.pack(side="left", padx=S(10))
        self.preset_cb.bind("<<ComboboxSelected>>", lambda e: self.select_preset())
        self.preset_btns = []
        for text, cmd, side in (("保存", self.save_preset, "left"), ("另存为", self.save_preset_as, "left"),
                                ("删除", self.delete_preset, "left"), ("导出", self.export_preset, "right"),
                                ("导入", self.import_preset, "right")):
            b = ttk.Button(card, text=text, command=cmd, style="Ghost.TButton", takefocus=0)
            b.pack(side=side, padx=(0, S(6)) if side == "left" else (S(6), 0))
            self.preset_btns.append(b)

        # 按键序列
        card = self._card(main, "按键序列", "按顺序循环执行，只放一个按键就是普通连点", expand=True)
        box = ttk.Frame(card, style="Inset.TFrame", padding=S(3))
        box.pack(fill="both", expand=True)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(box, columns=("i", "key", "gap"), show="headings", height=4,
                                 selectmode="browse", takefocus=0)
        for col, text, w, anchor in (("i", "#", 44, "center"), ("key", "按键 / 组合键", 270, "w"),
                                     ("gap", "之后等待", 200, "w")):
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=S(w), minwidth=S(40), anchor=anchor, stretch=col != "i")
        self.tree_sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview,
                                     style="Slim.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=self._on_tree_scroll)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", lambda e: self.edit_step())
        self.tree.bind("<Delete>", lambda e: self.del_step())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._sync_step_buttons())

        bar = tk.Frame(card, bg=CARD)
        bar.pack(fill="x", pady=(S(10), 0))
        self.step_btns = {}
        for key, text, cmd, style in (("add", "＋ 添加按键", self.add_step, "Accent.TButton"),
                                      ("edit", "编辑", self.edit_step, "Ghost.TButton"),
                                      ("copy", "复制", self.copy_step, "Ghost.TButton"),
                                      ("del", "删除", self.del_step, "Ghost.TButton"),
                                      ("up", "上移", lambda: self.move_step(-1), "Ghost.TButton"),
                                      ("down", "下移", lambda: self.move_step(1), "Ghost.TButton")):
            b = ttk.Button(bar, text=text, command=cmd, style=style, takefocus=0)
            b.pack(side="left", padx=(0, S(6)))
            self.step_btns[key] = b
        b = ttk.Button(bar, text="清空", command=self.clear_steps, style="Ghost.TButton", takefocus=0)
        b.pack(side="right")
        self.step_btns["clear"] = b
        self.flow_lbl = self._label(card, "", fg=MUTED, font=(FONT, 9), anchor="w", justify="left",
                                    wraplength=S(560))
        self.flow_lbl.pack(fill="x", pady=(S(9), 0))

        # 时间
        card = self._card(main, "时间")
        grid = tk.Frame(card, bg=CARD)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1, uniform="t")
        grid.columnconfigure(1, weight=1, uniform="t")
        self.v_interval = tk.StringVar(value=fmt_num(c["interval"]))
        self.v_interval_unit = tk.StringVar(value=c["interval_unit"])
        self.v_jitter = tk.StringVar(value=fmt_num(c["jitter_ms"]))
        self.v_hold = tk.StringVar(value=fmt_num(c["hold_ms"]))
        self.v_delay = tk.StringVar(value=fmt_num(c["delay_s"]))
        f = self._field(grid, "默认间隔", self.v_interval)
        cb = self._combo(f, self.v_interval_unit, list(GAP_UNITS))
        cb.pack(side="left", padx=(S(8), 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self._refresh_steps())
        self.v_interval.trace_add("write", lambda *a: self._refresh_steps())
        f.grid(row=0, column=0, sticky="w")
        self._field(grid, "开始延迟", self.v_delay, "秒后开始").grid(row=0, column=1, sticky="w")
        self._field(grid, "按住时长", self.v_hold, "毫秒").grid(row=1, column=0, sticky="w", pady=(S(8), 0))
        self._field(grid, "随机浮动", self.v_jitter, "毫秒  ± 0 为关闭").grid(row=1, column=1, sticky="w",
                                                                         pady=(S(8), 0))

        # 停止条件
        card = self._card(main)
        self.v_stop = tk.StringVar(value=c["stop_mode"])
        self.v_duration = tk.StringVar(value=fmt_num(c["duration"]))
        self.v_duration_unit = tk.StringVar(value=c["duration_unit"])
        self.v_rounds = tk.StringVar(value=fmt_num(c["rounds"]))
        self._label(card, "停止", font=(FONT, 10, "bold")).pack(side="left", padx=(0, S(16)))

        def radio(text, value):
            r = ttk.Radiobutton(card, text=text, variable=self.v_stop, value=value, takefocus=0,
                                command=self._sync_stop_mode)
            self.inputs.append(r)
            return r
        radio("手动停止", "forever").pack(side="left")
        radio("持续", "duration").pack(side="left", padx=(S(18), 0))
        self.e_duration = ttk.Entry(card, textvariable=self.v_duration, width=6, justify="center")
        self.e_duration.pack(side="left", padx=(S(6), S(6)))
        self.cb_duration = ttk.Combobox(card, textvariable=self.v_duration_unit, state="readonly", width=4,
                                        values=list(DUR_UNITS), takefocus=0)
        self.cb_duration.pack(side="left")
        radio("循环", "rounds").pack(side="left", padx=(S(18), 0))
        self.e_rounds = ttk.Entry(card, textvariable=self.v_rounds, width=6, justify="center")
        self.e_rounds.pack(side="left", padx=(S(6), S(6)))
        self._label(card, "轮", fg=SUB).pack(side="left")

        # 选项
        card = self._card(main)
        self._label(card, "启停热键", fg=SUB).pack(side="left")
        self.hk_lbl = ttk.Label(card, text=combo_text(c["hotkey"]), style="Chip.TLabel")
        self.hk_lbl.pack(side="left", padx=S(8))
        self.hk_btn = ttk.Button(card, text="修改", style="Ghost.TButton", takefocus=0, command=self.change_hotkey)
        self.hk_btn.pack(side="left")
        self._label(card, "发送方式", fg=SUB).pack(side="left", padx=(S(18), S(8)))
        self.v_send = tk.StringVar(value="普通" if c["send_mode"] == "vk" else "游戏兼容")
        self._combo(card, self.v_send, list(SEND_MODES), width=8).pack(side="left")
        self.v_topmost = tk.BooleanVar(value=bool(c["topmost"]))
        self.v_sound = tk.BooleanVar(value=bool(c["sound"]))
        ttk.Checkbutton(card, text="置顶 ", variable=self.v_topmost, style="Switch.TCheckbutton", takefocus=0,
                        command=self._apply_topmost).pack(side="right")
        ttk.Checkbutton(card, text="提示音 ", variable=self.v_sound, style="Switch.TCheckbutton",
                        takefocus=0).pack(side="right", padx=(0, S(14)))

        # 数据面板
        tiles = tk.Frame(main, bg=BG)
        tiles.pack(fill="x", pady=(0, S(10)))
        self.tile_vals = []
        for i, caption in enumerate(("按键次数", "完成轮数", "运行时间")):
            tiles.columnconfigure(i, weight=1, uniform="tile")
            t = ttk.Frame(tiles, style="Card.TFrame", padding=(S(16), S(9)))
            t.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else S(5), 0 if i == 2 else S(5)))
            v = self._label(t, "0", font=(FONT, 17, "bold"), anchor="w")
            v.pack(fill="x")
            self._label(t, caption, fg=MUTED, font=(FONT, 9), anchor="w").pack(fill="x")
            self.tile_vals.append(v)

        # 主按钮、进度、状态
        self.main_btn = BigButton(main, self, self.toggle)
        self.main_btn.pack(fill="x")
        self.progress = tk.Canvas(main, height=S(3), bg=BG, highlightthickness=0)
        self.progress.pack(fill="x", pady=(S(7), 0))
        self.progress_bar = self.progress.create_rectangle(0, 0, 0, S(3), fill=ACCENT, width=0)
        self.status_lbl = tk.Label(main, bg=BG, fg=SUB, font=(FONT, 9), pady=S(6))
        self.status_lbl.pack(fill="x")
        self._paint_main_btn()

    def _on_tree_scroll(self, first, last):
        if float(first) <= 0 and float(last) >= 1:
            self.tree_sb.grid_remove()
        else:
            self.tree_sb.grid(row=0, column=1, sticky="ns")
        self.tree_sb.set(first, last)

    def _restore_position(self):
        pos = self.cfg.get("window") or ""
        try:
            x, y = (int(v) for v in pos.replace("+", " ").split())
            if 0 <= x < self.root.winfo_screenwidth() - 200 and 0 <= y < self.root.winfo_screenheight() - 200:
                self.root.geometry("+%d+%d" % (x, y))
        except ValueError:
            pass

    # ── 自绘弹窗 ──
    def alert(self, title, text):
        MsgDialog(self, title, text, "info").show()

    def confirm(self, title, text, ok_text="确定"):
        return bool(MsgDialog(self, title, text, "confirm", ok_text=ok_text).show())

    def ask_text(self, title, text, initial=""):
        return MsgDialog(self, title, text, "input", initial=initial).show()

    def _modal(self, fn, *args, **kw):
        """弹出系统对话框期间暂停全局热键。"""
        self.dialog_open = True
        try:
            return fn(*args, **kw)
        finally:
            self.dialog_open = False

    def _say(self, text):
        self.flash = (text, time.perf_counter() + 3)

    # ── 序列编辑 ──
    def _gap_text(self, step):
        if step.get("interval") is None:
            return "默认 · %s %s" % (self.v_interval.get().strip() or "?", self.v_interval_unit.get())
        return "%s %s" % (fmt_num(step["interval"]), step.get("unit", "毫秒"))

    def _step_text(self, step):
        n = step.get("times", 1)
        return combo_text(step) + ("  × %d" % n if n > 1 else "")

    def _refresh_steps(self, select=None):
        if not hasattr(self, "tree"):
            return
        if select is None:
            sel = self.tree.selection()
            select = self.tree.index(sel[0]) if sel else None
        self.tree.delete(*self.tree.get_children())
        steps = self.cfg["steps"]
        for i, s in enumerate(steps):
            self.tree.insert("", "end", values=(i + 1, self._step_text(s), self._gap_text(s)))
        if select is not None and steps:
            item = self.tree.get_children()[min(select, len(steps) - 1)]
            self.tree.selection_set(item)
            self.tree.see(item)
        if not steps:
            text = "还没有按键，点「＋ 添加按键」开始设置"
        elif len(steps) == 1 and steps[0].get("times", 1) == 1:
            text = "连点 %s，每 %s 一次" % (combo_text(steps[0]), self._gap_text(steps[0]).replace("默认 · ", ""))
        else:
            names = [self._step_text(s).replace("  ", " ") for s in steps]
            if len(names) > 7:
                names = names[:6] + ["… 共 %d 步" % len(names)]
            text = "  →  ".join(names) + "  ↻"
        self.flow_lbl.configure(text=text)
        self._sync_step_buttons()

    def _selected(self):
        sel = self.tree.selection()
        return self.tree.index(sel[0]) if sel else None

    def _sync_step_buttons(self):
        idx, n, run = self._selected(), len(self.cfg["steps"]), self.ui_running
        has = idx is not None and not run
        states = {"add": not run, "edit": has, "copy": has, "del": has, "up": has and idx > 0,
                  "down": has and idx < n - 1, "clear": n > 0 and not run}
        for k, on in states.items():
            self.step_btns[k].configure(state="normal" if on else "disabled")

    def add_step(self):
        if self.ui_running:
            return
        res = StepDialog(self, "添加按键").show()
        if res:
            self.cfg["steps"].append(res)
            self._refresh_steps(select=len(self.cfg["steps"]) - 1)

    def edit_step(self):
        idx = self._selected()
        if idx is None or self.ui_running:
            return
        res = StepDialog(self, "编辑按键", step=self.cfg["steps"][idx]).show()
        if res:
            self.cfg["steps"][idx] = res
            self._refresh_steps(select=idx)

    def copy_step(self):
        idx = self._selected()
        if idx is None or self.ui_running:
            return
        self.cfg["steps"].insert(idx + 1, json.loads(json.dumps(self.cfg["steps"][idx])))
        self._refresh_steps(select=idx + 1)

    def del_step(self):
        idx = self._selected()
        if idx is None or self.ui_running:
            return
        del self.cfg["steps"][idx]
        self._refresh_steps(select=idx)

    def move_step(self, d):
        idx = self._selected()
        steps = self.cfg["steps"]
        if idx is None or self.ui_running or not 0 <= idx + d < len(steps):
            return
        steps[idx], steps[idx + d] = steps[idx + d], steps[idx]
        self._refresh_steps(select=idx + d)

    def clear_steps(self):
        if self.ui_running or not self.cfg["steps"]:
            return
        if self.confirm("清空序列", "确定清空所有按键吗？已保存的方案不受影响。", ok_text="清空"):
            self.cfg["steps"] = []
            self._refresh_steps()

    def change_hotkey(self):
        if self.ui_running:
            return
        res = StepDialog(self, "修改启停热键", step=self.cfg["hotkey"], for_hotkey=True).show()
        if res and res["key"] not in MOUSE_FLAGS:
            self.cfg["hotkey"] = {"mods": res["mods"], "key": res["key"]}
            self.hk_lbl.configure(text=combo_text(self.cfg["hotkey"]))
            self._paint_main_btn()

    # ── 方案：保存 / 切换 / 导入 / 导出 ──
    def _snapshot(self):
        """当前界面上的设置（不合法时弹窗提示并返回 None）。"""
        try:
            self._collect()
        except ValueError as e:
            self.alert("设置有误", str(e))
            return None
        return json.loads(json.dumps({k: self.cfg[k] for k in PRESET_KEYS}))

    def _apply_preset(self, data):
        c = self.cfg
        c.update(sanitize_preset(data))
        self.v_interval_unit.set(c["interval_unit"])
        self.v_interval.set(fmt_num(c["interval"]))
        self.v_jitter.set(fmt_num(c["jitter_ms"]))
        self.v_hold.set(fmt_num(c["hold_ms"]))
        self.v_delay.set(fmt_num(c["delay_s"]))
        self.v_stop.set(c["stop_mode"])
        self.v_duration.set(fmt_num(c["duration"]))
        self.v_duration_unit.set(c["duration_unit"])
        self.v_rounds.set(fmt_num(c["rounds"]))
        self.tree.selection_set(())
        self._refresh_steps()
        self._sync_stop_mode()

    def _set_current_preset(self, name):
        self.cfg["preset"] = name
        self.preset_cb.configure(values=list(self.cfg["presets"]))
        self.v_preset.set(name)
        self._save()

    def select_preset(self):
        name = self.v_preset.get()
        self.preset_cb.selection_clear()
        if self.ui_running or name not in self.cfg["presets"]:
            return
        self._apply_preset(self.cfg["presets"][name])
        self._set_current_preset(name)
        self._say("已切换到方案「%s」" % name)

    def save_preset(self):
        name = self.v_preset.get()
        if name not in self.cfg["presets"]:
            return self.save_preset_as()
        snap = self._snapshot()
        if snap is not None:
            self.cfg["presets"][name] = snap
            self._set_current_preset(name)
            self._say("已保存方案「%s」" % name)

    def save_preset_as(self):
        if self.ui_running:
            return
        snap = self._snapshot()
        if snap is None:
            return
        name = (self.ask_text("保存方案", "给这个方案起个名字：", self.v_preset.get()) or "").strip()
        if not name:
            return
        if name in self.cfg["presets"] and not self.confirm("覆盖方案", "方案「%s」已存在，要覆盖吗？" % name,
                                                            ok_text="覆盖"):
            return
        self.cfg["presets"][name] = snap
        self._set_current_preset(name)
        self._say("已保存方案「%s」" % name)

    def delete_preset(self):
        name = self.v_preset.get()
        if self.ui_running or name not in self.cfg["presets"]:
            return
        if self.confirm("删除方案", "确定删除方案「%s」吗？\n当前界面上的设置不会被清掉。" % name, ok_text="删除"):
            del self.cfg["presets"][name]
            self._set_current_preset("")
            self._say("已删除方案「%s」" % name)

    def export_to(self, path, name, snap):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"app": "KeyTapper", "version": 1, "name": name, "preset": snap},
                      f, ensure_ascii=False, indent=2)

    def import_from(self, path):
        """读入方案文件，存进方案列表并切换过去；返回方案名。"""
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("方案文件格式不正确，无法读取。")
        preset = sanitize_preset(data.get("preset", data))
        base = str(data.get("name") or "").strip() or os.path.splitext(os.path.basename(path))[0]
        name, i = base, 2
        while name in self.cfg["presets"]:
            name, i = "%s (%d)" % (base, i), i + 1
        self.cfg["presets"][name] = preset
        self._apply_preset(preset)
        self._set_current_preset(name)
        return name

    def export_preset(self):
        if self.ui_running:
            return
        snap = self._snapshot()
        if snap is None:
            return
        if not snap["steps"]:
            return self.alert("无法导出", "还没有设置按键，没有可导出的内容。")
        name = self.v_preset.get() or "我的连点方案"
        path = self._modal(filedialog.asksaveasfilename, parent=self.root, title="导出方案",
                           defaultextension=".json", initialfile=name + ".json",
                           filetypes=[("KeyTapper 方案", "*.json")])
        if not path:
            return
        try:
            self.export_to(path, name, snap)
        except OSError as e:
            return self.alert("导出失败", str(e))
        self._say("已导出到 %s" % os.path.basename(path))

    def import_preset(self):
        if self.ui_running:
            return
        path = self._modal(filedialog.askopenfilename, parent=self.root, title="导入方案",
                           filetypes=[("KeyTapper 方案", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            name = self.import_from(path)
        except (OSError, ValueError):
            return self.alert("导入失败", "方案文件格式不正确，无法读取。")
        self._say("已导入方案「%s」" % name)

    # ── 状态同步 ──
    def _sync_stop_mode(self):
        mode, run = self.v_stop.get(), self.ui_running
        self.e_duration.configure(state="normal" if mode == "duration" and not run else "disabled")
        self.cb_duration.configure(state="readonly" if mode == "duration" and not run else "disabled")
        self.e_rounds.configure(state="normal" if mode == "rounds" and not run else "disabled")

    def _apply_topmost(self):
        self.root.attributes("-topmost", bool(self.v_topmost.get()))

    def _set_inputs(self, enabled):
        for w in self.inputs:
            if isinstance(w, ttk.Combobox):
                w.configure(state="readonly" if enabled else "disabled")
            else:
                w.configure(state="normal" if enabled else "disabled")
        self.hk_btn.configure(state="normal" if enabled else "disabled")
        self.preset_cb.configure(state="readonly" if enabled else "disabled")
        for b in self.preset_btns:
            b.configure(state="normal" if enabled else "disabled")
        self._sync_stop_mode()
        self._sync_step_buttons()

    def _paint_main_btn(self):
        hk = combo_text(self.cfg["hotkey"])
        if self.ui_running:
            self.main_btn.set("stop", "■   停止", hk)
        else:
            self.main_btn.set("start", "▶   开始连点", hk)

    # ── 读取界面上的设置 ──
    def _num(self, var, name, minimum=0.0):
        try:
            v = float(var.get().strip())
        except ValueError:
            raise ValueError("「%s」需要填写数字。" % name)
        if v < minimum:
            raise ValueError("「%s」不能小于 %s。" % (name, fmt_num(minimum)))
        return v

    def _collect(self):
        """把界面上的值写回 self.cfg；有不合法的输入时抛 ValueError。"""
        c = self.cfg
        c["interval_unit"] = self.v_interval_unit.get()
        c["duration_unit"] = self.v_duration_unit.get()
        c["stop_mode"] = self.v_stop.get()
        c["topmost"] = bool(self.v_topmost.get())
        c["sound"] = bool(self.v_sound.get())
        c["send_mode"] = SEND_MODES.get(self.v_send.get(), "scan")
        c["interval"] = self._num(self.v_interval, "默认间隔", 0.0)
        if c["interval"] * GAP_UNITS[c["interval_unit"]] < 1:
            raise ValueError("「默认间隔」不能小于 1 毫秒。")
        c["delay_s"] = self._num(self.v_delay, "开始延迟")
        c["hold_ms"] = self._num(self.v_hold, "按住时长")
        c["jitter_ms"] = self._num(self.v_jitter, "随机浮动")
        if c["stop_mode"] == "duration":
            c["duration"] = self._num(self.v_duration, "持续时间")
            if c["duration"] <= 0:
                raise ValueError("「持续时间」需要大于 0。")
        if c["stop_mode"] == "rounds":
            c["rounds"] = int(self._num(self.v_rounds, "循环轮数", 1))

    def _save(self):
        try:
            self.cfg["window"] = "+%d+%d" % (self.root.winfo_x(), self.root.winfo_y())
            with open(self.cfg_path, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        except (OSError, tk.TclError):
            pass

    def build_job(self):
        c = self.cfg
        default_ms = c["interval"] * GAP_UNITS[c["interval_unit"]]
        steps = []
        for s in c["steps"]:
            gap = default_ms if s.get("interval") is None else s["interval"] * GAP_UNITS[s.get("unit", "毫秒")]
            steps += [{"mods": list(s.get("mods", [])), "key": s["key"], "gap_ms": gap}] * s.get("times", 1)
        return {
            "steps": steps, "hold_ms": c["hold_ms"], "jitter_ms": c["jitter_ms"],
            "delay_s": c["delay_s"],
            "duration_s": c["duration"] * DUR_UNITS[c["duration_unit"]] if c["stop_mode"] == "duration" else 0,
            "max_rounds": c["rounds"] if c["stop_mode"] == "rounds" else 0,
        }

    # ── 启停 ──
    def toggle(self):
        if self.tapper.alive():
            self.tapper.stop()
        else:
            self.start()

    def start(self):
        if self.dialog_open or self.tapper.alive():
            return
        try:
            if not self.cfg["steps"]:
                raise ValueError("还没有设置按键，请先点「＋ 添加按键」。")
            self._collect()
            if any(s["key"] == self.cfg["hotkey"]["key"] for s in self.cfg["steps"]):
                raise ValueError("启停热键（%s）和要连点的按键相同，会导致自己把自己停掉。\n请修改热键或按键。"
                                 % key_name(self.cfg["hotkey"]["key"]))
        except ValueError as e:
            return self.alert("无法开始", str(e))
        self._save()
        globals()["SEND_SCANCODE"] = self.cfg["send_mode"] != "vk"
        self.job = self.build_job()
        self.ui_running = True
        self._set_inputs(False)
        self._paint_main_btn()
        self.root.focus_set()
        self.tapper.start(self.job)

    def _set_progress(self, frac, color=ACCENT):
        w = self.progress.winfo_width()
        self.progress.coords(self.progress_bar, 0, 0, int(w * max(0.0, min(1.0, frac))), self.S(3))
        self.progress.itemconfigure(self.progress_bar, fill=color)

    def _tick(self):
        # 全局热键：轮询物理按键状态，在任何窗口都有效
        hk = self.cfg["hotkey"]
        pressed = is_down(hk["key"]) and all(is_down(m) for m in hk.get("mods", []))
        if pressed and not self.hk_prev and not self.dialog_open:
            self.toggle()
        self.hk_prev = pressed or self.dialog_open

        t, now = self.tapper, time.perf_counter()
        state = t.state if t.alive() else "idle"
        if self.ui_running and state == "idle":
            self.ui_running = False
            self._set_inputs(True)
            self._paint_main_btn()
        if state != self.prev_state and self.v_sound.get():
            if state == "running":
                beep(1047, 70)
            elif state == "idle":
                beep(523, 110)
        self.prev_state = state

        hk_text = combo_text(hk)
        if state == "countdown":
            left = max(0.0, t.start_at - now)
            self.pill.configure(text="%.1f 秒后开始" % left, style="Wait.TLabel")
            self.status_lbl.configure(text="倒计时中，现在可以切换到目标窗口")
            delay = self.job["delay_s"] or 1
            self._set_progress(1 - left / delay, WARN)
            elapsed = 0
        elif state == "running":
            self.pill.configure(text="运行中", style="Run.TLabel")
            elapsed = now - t.t_begin
            if t.deadline:
                self.status_lbl.configure(text="正在连点 · 剩余 %s" % fmt_time(t.deadline - now + 0.999))
                self._set_progress(elapsed / self.job["duration_s"])
            elif self.job["max_rounds"]:
                self.status_lbl.configure(text="正在连点 · 第 %d / %d 轮"
                                          % (min(t.rounds + 1, self.job["max_rounds"]), self.job["max_rounds"]))
                self._set_progress(t.rounds / self.job["max_rounds"])
            else:
                self.status_lbl.configure(text="正在连点 · 按 %s 停止" % hk_text)
                self._set_progress(1.0)
        else:
            self.pill.configure(text="待机", style="Idle.TLabel")
            elapsed = t.t_end - t.t_begin if t.t_begin else 0
            self._set_progress(0)
            if now < self.flash[1]:
                self.status_lbl.configure(text=self.flash[0])
            elif t.count:
                self.status_lbl.configure(text="已停止 · 按 %s 再次开始" % hk_text)
            else:
                self.status_lbl.configure(text="准备就绪 · 按 %s 开始，在任何窗口都有效" % hk_text)
        for lbl, text in zip(self.tile_vals, ("{:,}".format(t.count), "{:,}".format(t.rounds), fmt_time(elapsed))):
            if lbl.cget("text") != text:
                lbl.configure(text=text)
        self.root.after(25, self._tick)

    def on_close(self):
        try:
            self.tapper.stop()
            try:
                self._collect()
            except ValueError:
                pass
            self._save()
        finally:
            self.root.destroy()

    def run(self):
        self.root.mainloop()


_instance_mutex = None


def already_running():
    """已有一个连点器在运行时，把它的窗口调到最前面。"""
    global _instance_mutex
    _instance_mutex = kernel32.CreateMutexW(None, False, "KeyTapper.SingleInstance")
    if ctypes.get_last_error() != 183:
        return False
    hwnd = user32.FindWindowW(None, TITLE)
    if hwnd:
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
    return True


def main():
    admin = ensure_admin()
    if already_running():
        return
    try:
        App(admin=admin).run()
    except Exception:
        import traceback
        with open(os.path.join(APP_DIR, "error.log"), "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        user32.MessageBoxW(None, "程序出错了，详细信息已写入 error.log。", "KeyTapper", 0x10)


if __name__ == "__main__":
    main()

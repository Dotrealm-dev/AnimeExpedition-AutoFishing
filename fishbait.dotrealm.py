import time, ctypes, threading, math, random, sys, os
import numpy as np, cv2, mss
import tkinter as tk
from tkinter import messagebox

APP_TITLE = "fishbait.dotrealm"

def resource_path(filename):
    """Find a bundled file whether running as a plain .py or a PyInstaller .exe."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, filename)
    return os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), filename)

# ---------------- fixed internal settings (no need to touch) ----------------
ROI      = {"top": 904, "left": 505, "width": 911, "height": 48}
FISH_TH  = 0.62
BAR_TH   = 0.45

KP, KD, KV = 0.055, 0.020, 0.35
PWM_HZ, BIAS, MEMORY = 40, 0.45, 12

RIGHT_ZONE   = 0.88
IDLE_CLICK_S = 1.2
IDLE_AFTER   = 25
IDLE_NEEDS_BAR_ONLY = True

SHOW_DEBUG_WINDOW = True
# -----------------------------------------------------------------------------

VK_F8, VK_F10 = 0x77, 0x79

user32 = ctypes.windll.user32

class MI(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("d", ctypes.c_ulong), ("f", ctypes.c_ulong),
                ("t", ctypes.c_ulong), ("x", ctypes.POINTER(ctypes.c_ulong))]

class INP(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("mi", MI)]

def _send(flag):
    inp = INP(0, MI(0, 0, 0, flag, 0, None))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

_down = False
def hold(s):
    global _down
    if s == _down:
        return
    _down = s
    _send(0x0002 if s else 0x0004)

def click():
    hold(False)
    _send(0x0002)
    time.sleep(0.03)
    _send(0x0004)


class FishBotEngine:
    """Background loop: captures the ROI, drives the fishing minigame,
    and listens for the F8 (start) / F10 (stop) hotkeys."""

    def __init__(self, on_state_change, on_status):
        self.on_state_change = on_state_change   # callback(running: bool)
        self.on_status = on_status                # callback(mode, fish_score, bar_score)
        self.run = False
        self.alive = True
        self.thread = None

        self._tf = cv2.imread(resource_path("fish.png"), cv2.IMREAD_GRAYSCALE)
        self._tb = cv2.imread(resource_path("bar.png"), cv2.IMREAD_GRAYSCALE)
        if self._tf is None:
            raise FileNotFoundError("fish.png not found")
        if self._tb is None:
            raise FileNotFoundError("bar.png not found")
        self._fish_tpls = [self._tf, cv2.flip(self._tf, 1)]

    def find_fish(self, gray):
        bs, bx = -1.0, None
        for t in self._fish_tpls:
            _, mx, _, loc = cv2.minMaxLoc(cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED))
            if mx > bs:
                bs, bx = mx, loc[0] + t.shape[1] / 2
        return (bx, bs) if bs >= FISH_TH else (None, bs)

    def find_bar(self, gray):
        _, mx, _, loc = cv2.minMaxLoc(cv2.matchTemplate(gray, self._tb, cv2.TM_CCOEFF_NORMED))
        return (loc[0] + self._tb.shape[1] / 2, mx) if mx >= BAR_TH else (None, mx)

    def launch(self):
        if self.thread and self.thread.is_alive():
            return
        self.alive = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def set_running(self, state: bool):
        self.run = state
        if not state:
            hold(False)
        self.on_state_change(self.run)

    def shutdown(self):
        self.alive = False
        self.run = False
        hold(False)

    def _loop(self):
        fx_s = vx = prev_e = 0.0
        miss = 99
        dead = 99
        t_click = 0.0
        t0 = time.perf_counter()
        f8_latch = f10_latch = False

        with mss.mss() as sct:
            while self.alive:
                # ---- global hotkeys ----
                f8 = user32.GetAsyncKeyState(VK_F8) & 0x8000
                f10 = user32.GetAsyncKeyState(VK_F10) & 0x8000
                if f8 and not f8_latch:
                    self.set_running(True)
                if f10 and not f10_latch:
                    self.set_running(False)
                f8_latch, f10_latch = bool(f8), bool(f10)

                now = time.perf_counter()
                dt = max(now - t0, 1e-4)
                t0 = now

                bgr = np.array(sct.grab(ROI))[:, :, :3]
                gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

                bx, bs = self.find_bar(gray)
                fx, score = self.find_fish(gray)

                has_game = bx is not None if IDLE_NEEDS_BAR_ONLY else (bx is not None or fx is not None)
                dead = 0 if has_game else dead + 1

                if fx is not None:
                    if miss > MEMORY:
                        fx_s, vx = fx, 0.0
                    else:
                        vx = 0.7 * vx + 0.3 * ((fx - fx_s) / dt)
                        fx_s = 0.5 * fx_s + 0.5 * fx
                    miss = 0
                else:
                    miss += 1
                    if miss <= MEMORY:
                        fx_s += vx * dt
                fx_s = float(np.clip(fx_s, 0, ROI["width"]))

                duty, mode = 0.0, "-"
                if self.run:
                    if dead >= IDLE_AFTER:
                        mode = "IDLE"
                        if now - t_click >= IDLE_CLICK_S:
                            click()
                            t_click = now
                        else:
                            hold(False)
                    elif bx is not None and miss <= MEMORY:
                        if fx_s >= ROI["width"] * RIGHT_ZONE:
                            duty, mode = 1.0, "RIGHT"
                            hold(True)
                        else:
                            err = fx_s - bx
                            de = (err - prev_e) / dt
                            prev_e = err
                            duty = float(np.clip(
                                BIAS + KP * err + KD * de * 0.01 + KV * (vx / 100), 0, 1))
                            mode = "PID"
                            hold((now * PWM_HZ) % 1.0 < duty)
                    else:
                        hold(False)
                else:
                    hold(False)
                    mode = "PAUSED"

                self.on_status(mode, score, bs)

                if SHOW_DEBUG_WINDOW:
                    v = cv2.resize(bgr, None, fx=1, fy=3)
                    h = v.shape[0]
                    rz = int(ROI["width"] * RIGHT_ZONE)
                    cv2.line(v, (rz, 0), (rz, h), (0, 255, 255), 1)
                    cv2.line(v, (int(fx_s), 0), (int(fx_s), h), (0, 0, 255), 2)
                    if bx is not None:
                        cv2.line(v, (int(bx), 0), (int(bx), h), (0, 255, 0), 2)
                    cv2.putText(v, f"f {score:.2f} b {bs:.2f} duty {duty:.2f} [{mode}]",
                                (5, 20), 0, 0.6, (255, 255, 255), 2)
                    cv2.imshow(APP_TITLE, v)
                    if cv2.waitKey(1) == 27:
                        self.alive = False

        hold(False)
        if SHOW_DEBUG_WINDOW:
            cv2.destroyAllWindows()


# ============================= cute UI =============================

BG        = "#ffe9f2"
CARD      = "#fff5fa"
PINK      = "#ff8fb4"
PINK_DARK = "#ff5f95"
BLUE      = "#8fd3ff"
BLUE_DARK = "#4fb3ff"
GRAY      = "#c9c9d2"
GRAY_DARK = "#9b9ba6"
TEXT      = "#5a3d52"


class RoundButton(tk.Canvas):
    def __init__(self, parent, text, color, color_dark, command, width=220, height=64, font_size=16):
        super().__init__(parent, width=width, height=height, bg=CARD, highlightthickness=0)
        self.command = command
        self.color, self.color_dark = color, color_dark
        self.w, self.h = width, height
        self.text = text
        self.font_size = font_size
        self.enabled = True
        self._draw(color)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", lambda e: self._draw(color_dark) if self.enabled else None)
        self.bind("<Leave>", lambda e: self._draw(color) if self.enabled else None)

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1+r,y1, x2-r,y1, x2,y1, x2,y1+r, x2,y2-r, x2,y2, x2-r,y2,
               x1+r,y2, x1,y2, x1,y2-r, x1,y1+r, x1,y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _draw(self, color):
        self.delete("all")
        fill = color if self.enabled else GRAY
        self._round_rect(3, 3, self.w-3, self.h-3, 18, fill=fill, outline="")
        self.create_text(self.w/2, self.h/2, text=self.text,
                          fill="white", font=("Comic Sans MS", self.font_size, "bold"))

    def set_enabled(self, enabled):
        self.enabled = enabled
        self._draw(self.color)

    def _on_click(self, e):
        if self.enabled and self.command:
            self.command()


class FishCanvas(tk.Canvas):
    """A small animated cartoon fish swimming back and forth, for cuteness."""
    def __init__(self, parent, width=340, height=140):
        super().__init__(parent, width=width, height=height, bg=BLUE, highlightthickness=0)
        self.w, self.h = width, height
        self.t = 0.0
        self.state = "idle"  # idle / running / paused
        self._bubbles = [[random.uniform(0, width), random.uniform(0, height)] for _ in range(6)]
        self._tick()

    def set_state(self, state):
        self.state = state

    def _tick(self):
        self.t += 0.08
        self.delete("all")

        # water shading
        self.create_rectangle(0, 0, self.w, self.h, fill=BLUE, outline="")
        for i in range(4):
            y = 20 + i * 30
            self.create_line(0, y, self.w, y, fill="#a9e0ff", width=2)

        # bubbles
        for b in self._bubbles:
            b[1] -= 1.2
            if b[1] < -5:
                b[1] = self.h + 5
                b[0] = random.uniform(0, self.w)
            r = 3
            self.create_oval(b[0]-r, b[1]-r, b[0]+r, b[1]+r, outline="white", width=1)

        speed = {"idle": 0.6, "running": 2.2, "paused": 0.0}[self.state]
        cx = (self.t * speed * 40) % (self.w + 80) - 40
        cy = self.h / 2 + math.sin(self.t * 2) * 14

        wig = math.sin(self.t * 8) * 8
        body_color = "#ffb84d" if self.state != "paused" else "#d9a86b"

        # tail
        self.create_polygon(cx-30, cy, cx-48, cy-14+wig, cx-48, cy+14+wig,
                             fill=body_color, outline="#c9781a")
        # body
        self.create_oval(cx-30, cy-18, cx+26, cy+18, fill=body_color, outline="#c9781a", width=2)
        # eye
        self.create_oval(cx+10, cy-6, cx+17, cy+1, fill="white", outline="")
        self.create_oval(cx+12, cy-4, cx+16, cy, fill="black", outline="")
        # cute cheek blush
        self.create_oval(cx-2, cy+4, cx+8, cy+10, fill="#ffd1e8", outline="")
        # fin
        self.create_polygon(cx-4, cy-14, cx+6, cy-30+wig/2, cx+14, cy-12,
                             fill="#ff8fb4", outline="#c9781a")

        label = {"idle": "waiting... (づ๑•ᴗ•๑)づ",
                  "running": "fishing!! ✨🎣",
                  "paused": "taking a break... zzz"}[self.state]
        self.create_text(self.w/2, self.h-12, text=label,
                          fill="white", font=("Comic Sans MS", 11, "bold"))

        self.after(40, self._tick)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.configure(bg=BG)
        self.resizable(False, False)
        self.engine = None

        self._build_ui()
        self._init_engine()

    def _build_ui(self):
        header = tk.Frame(self, bg=BG)
        header.pack(pady=(16, 6))
        tk.Label(header, text="🐟 fishbait.dotrealm 🎣", bg=BG, fg=PINK_DARK,
                  font=("Comic Sans MS", 22, "bold")).pack()
        tk.Label(header, text="auto-fishing helper ✨", bg=BG, fg=TEXT,
                  font=("Comic Sans MS", 11)).pack()

        card = tk.Frame(self, bg=CARD, bd=0)
        card.pack(padx=18, pady=10, ipadx=14, ipady=14)

        self.fish_canvas = FishCanvas(card)
        self.fish_canvas.pack(pady=(4, 12))

        self.status_var = tk.StringVar(value="ready to go~")
        tk.Label(card, textvariable=self.status_var, bg=CARD, fg=TEXT,
                  font=("Comic Sans MS", 12, "bold")).pack(pady=(0, 12))

        btn_row = tk.Frame(card, bg=CARD)
        btn_row.pack()

        self.start_btn = RoundButton(btn_row, "▶  START (F8)", PINK, PINK_DARK, self.start_bot, width=210)
        self.start_btn.grid(row=0, column=0, padx=6, pady=4)

        self.stop_btn = RoundButton(btn_row, "⏸  STOP (F10)", BLUE, BLUE_DARK, self.stop_bot, width=210)
        self.stop_btn.grid(row=0, column=1, padx=6, pady=4)

        self.exit_btn = RoundButton(card, "✖  EXIT", GRAY_DARK, "#7d7d87", self.on_exit,
                                     width=430, height=48, font_size=14)
        self.exit_btn.pack(pady=(10, 0))

        tk.Label(self, text="hint: fish.png and bar.png must be next to this app",
                  bg=BG, fg=GRAY_DARK, font=("Comic Sans MS", 9)).pack(pady=(6, 12))

    def _init_engine(self):
        try:
            self.engine = FishBotEngine(self.on_state_change, self.on_status)
        except FileNotFoundError as e:
            messagebox.showerror(APP_TITLE, f"{e}\n\nวางไฟล์ fish.png และ bar.png ไว้โฟลเดอร์เดียวกับโปรแกรมนี้ก่อนนะ~")
            self.destroy()
            return
        self.engine.launch()

    def start_bot(self):
        if self.engine:
            self.engine.set_running(True)

    def stop_bot(self):
        if self.engine:
            self.engine.set_running(False)

    def on_state_change(self, running):
        self.after(0, lambda: self._apply_state(running))

    def _apply_state(self, running):
        if running:
            self.status_var.set("fishing in progress... good luck! (＾▽＾)")
            self.fish_canvas.set_state("running")
        else:
            self.status_var.set("paused — press START or F8 to resume")
            self.fish_canvas.set_state("paused")

    def on_status(self, mode, fish_score, bar_score):
        pass  # kept minimal on purpose for a clean, non-technical UI

    def on_exit(self):
        if self.engine:
            self.engine.shutdown()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_exit)
    app.mainloop()
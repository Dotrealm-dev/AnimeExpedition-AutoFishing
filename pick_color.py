import time, ctypes
import numpy as np, cv2, mss

# ---------------- config ----------------
ROI      = {"top": 904, "left": 505, "width": 911, "height": 48}
FISH_TH  = 0.62          # เพิ่มขึ้นจาก 0.50 กันของสีฟ้าแมตช์ผิด
BAR_TH   = 0.45

KP, KD, KV = 0.055, 0.020, 0.35
PWM_HZ, BIAS, MEMORY = 40, 0.45, 12

RIGHT_ZONE   = 0.88      # ปลาเลย 88% ของ ROI = ชิดขวา -> กดค้าง
IDLE_CLICK_S = 1.2       # ไม่เจอ bar -> คลิกทุกกี่วินาที
IDLE_AFTER   = 25        # ต้องไม่เจอ bar ติดกันกี่เฟรมก่อนเริ่มคลิก

IDLE_NEEDS_BAR_ONLY = True   # True = ดูแค่ bar (แนะนำ), False = ต้องไม่เจอทั้งคู่

DEBUG, LOG = True, False
# ----------------------------------------

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
    if s == _down: return
    _down = s
    _send(0x0002 if s else 0x0004)

def click():
    hold(False)
    _send(0x0002); time.sleep(0.03); _send(0x0004)

# ---------------- templates ----------------
_tf = cv2.imread("fish.png", cv2.IMREAD_GRAYSCALE)
_tb = cv2.imread("bar.png",  cv2.IMREAD_GRAYSCALE)
assert _tf is not None, "ไม่เจอ fish.png"
assert _tb is not None, "ไม่เจอ bar.png"
FISH_TPLS = [_tf, cv2.flip(_tf, 1)]

def find_fish(gray):
    bs, bx = -1.0, None
    for t in FISH_TPLS:
        _, mx, _, loc = cv2.minMaxLoc(cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED))
        if mx > bs: bs, bx = mx, loc[0] + t.shape[1] / 2
    return (bx, bs) if bs >= FISH_TH else (None, bs)

def find_bar(gray):
    _, mx, _, loc = cv2.minMaxLoc(cv2.matchTemplate(gray, _tb, cv2.TM_CCOEFF_NORMED))
    return (loc[0] + _tb.shape[1] / 2, mx) if mx >= BAR_TH else (None, mx)

# ---------------- main ----------------
def main():
    print("F8 = เปิด/ปิด | F9 = ออก")
    run = False
    fx_s = vx = prev_e = 0.0
    miss = 99
    dead = 99
    t_click = 0.0
    t0 = time.perf_counter()

    with mss.mss() as sct:
        while True:
            if user32.GetAsyncKeyState(0x79) & 1: break
            if user32.GetAsyncKeyState(0x77) & 1:
                run = not run
                if not run: hold(False)
                print("▶ ON" if run else "⏸ OFF")

            now = time.perf_counter()
            dt  = max(now - t0, 1e-4); t0 = now

            bgr  = np.array(sct.grab(ROI))[:, :, :3]
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

            bx, bs    = find_bar(gray)
            fx, score = find_fish(gray)

            # --- ตัดสินว่าอยู่ในมินิเกมหรือไม่ ---
            # ไม่มี bar = ไม่ได้ตกปลาอยู่ (ไม่สนปลา เพราะของสีฟ้าอาจแมตช์ผิด)
            if IDLE_NEEDS_BAR_ONLY:
                has_game = bx is not None
            else:
                has_game = (bx is not None) or (fx is not None)
            dead = 0 if has_game else dead + 1

            # --- ติดตามปลา ---
            if fx is not None:
                if miss > MEMORY:
                    fx_s, vx = fx, 0.0
                else:
                    vx   = 0.7 * vx + 0.3 * ((fx - fx_s) / dt)
                    fx_s = 0.5 * fx_s + 0.5 * fx
                miss = 0
            else:
                miss += 1
                if miss <= MEMORY: fx_s += vx * dt
            fx_s = float(np.clip(fx_s, 0, ROI["width"]))

            # --- ควบคุม ---
            duty, mode = 0.0, "-"
            if run:
                if dead >= IDLE_AFTER:
                    mode = "IDLE"
                    if now - t_click >= IDLE_CLICK_S:
                        click(); t_click = now
                    else:
                        hold(False)

                elif bx is not None and miss <= MEMORY:
                    if fx_s >= ROI["width"] * RIGHT_ZONE:
                        duty, mode = 1.0, "RIGHT"
                        hold(True)
                    else:
                        err    = fx_s - bx
                        de     = (err - prev_e) / dt
                        prev_e = err
                        duty = float(np.clip(
                            BIAS + KP * err + KD * de * 0.01 + KV * (vx / 100), 0, 1))
                        mode = "PID"
                        hold((now * PWM_HZ) % 1.0 < duty)
                else:
                    hold(False)

            if LOG and run:
                print(f"[{mode:5}] fish {fx_s:6.1f} | bar {bx if bx else -1:6.1f} | "
                      f"duty {duty:.2f} | dead {dead}")

            if DEBUG:
                v = cv2.resize(bgr, None, fx=1, fy=3)
                h = v.shape[0]
                rz = int(ROI["width"] * RIGHT_ZONE)
                cv2.line(v, (rz, 0), (rz, h), (0, 255, 255), 1)
                cv2.line(v, (int(fx_s), 0), (int(fx_s), h), (0, 0, 255), 2)
                if bx is not None:
                    cv2.line(v, (int(bx), 0), (int(bx), h), (0, 255, 0), 2)
                cv2.putText(v, f"f {score:.2f} b {bs:.2f} duty {duty:.2f} [{mode}]",
                            (5, 20), 0, 0.6, (255, 255, 255), 2)
                cv2.imshow("bot", v)
                if cv2.waitKey(1) == 27: break

    hold(False)
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
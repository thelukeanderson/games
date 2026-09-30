"""
Bouncing Ball — grab it, stop it, throw it.
 
Controls
  • Click and hold on the ball  → it stops and sticks to your mouse
  • Drag and let go             → throws the ball in the direction you flicked
  • Space                       → toggle gravity on/off
  • R                           → reset the ball to the center
  • Esc                         → quit
 
Runs with the Python that ships with macOS / python.org (uses tkinter, no installs).
Start it with:  python3 bouncing_ball.py
"""
import math
import time
import tkinter as tk
 
WIDTH, HEIGHT = 900, 600
RADIUS = 32
FPS = 120
GRAVITY = 1400.0        # px/s² (when gravity is on)
BOUNCE = 0.85           # energy kept on each wall hit
AIR_DRAG = 0.15         # fraction of speed lost per second
MAX_THROW = 4000.0      # px/s cap on throw speed
BG = "#12161c"
BALL = "#ff8a3d"
BALL_HELD = "#ffc23d"
 
 
class BallApp:
    def __init__(self, root):
        self.root = root
        root.title("Bouncing Ball — grab & throw")
        self.canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
 
        self.x, self.y = WIDTH / 2, HEIGHT / 3
        self.vx, self.vy = 420.0, -260.0
        self.gravity = True
        self.held = False
        self.grab_dx = self.grab_dy = 0.0
        self.mouse_hist = []  # recent (t, x, y) samples while dragging
 
        self.shadow = self.canvas.create_oval(0, 0, 0, 0, fill="#0b0e12", outline="")
        self.ball = self.canvas.create_oval(0, 0, 0, 0, fill=BALL, outline="#ffd9b8", width=2)
        self.shine = self.canvas.create_oval(0, 0, 0, 0, fill="#ffe7d3", outline="")
        self.hud = self.canvas.create_text(14, 12, anchor="nw", fill="#8b96a3", font=("Helvetica", 13))
 
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        root.bind("<space>", lambda e: self.toggle_gravity())
        root.bind("<r>", lambda e: self.reset())
        root.bind("<Escape>", lambda e: root.destroy())
 
        self.last = time.perf_counter()
        self.tick()
 
    # ---------- input ----------
    def over_ball(self, mx, my):
        return math.hypot(mx - self.x, my - self.y) <= RADIUS + 6
 
    def on_press(self, e):
        if self.over_ball(e.x, e.y):
            self.held = True
            self.vx = self.vy = 0.0
            self.grab_dx, self.grab_dy = self.x - e.x, self.y - e.y
            self.mouse_hist = [(time.perf_counter(), e.x, e.y)]
            self.canvas.config(cursor="fleur")
 
    def on_drag(self, e):
        if not self.held:
            return
        w, h = self.size()
        self.x = min(max(e.x + self.grab_dx, RADIUS), w - RADIUS)
        self.y = min(max(e.y + self.grab_dy, RADIUS), h - RADIUS)
        now = time.perf_counter()
        self.mouse_hist.append((now, e.x, e.y))
        self.mouse_hist = [s for s in self.mouse_hist if now - s[0] < 0.1]  # keep last 100 ms
 
    def on_release(self, e):
        if not self.held:
            return
        self.held = False
        self.canvas.config(cursor="")
        now = time.perf_counter()
        samples = [s for s in self.mouse_hist if now - s[0] < 0.1]
        if len(samples) >= 2:
            (t0, x0, y0), (t1, x1, y1) = samples[0], samples[-1]
            dt = max(t1 - t0, 1e-3)
            vx, vy = (x1 - x0) / dt, (y1 - y0) / dt
            speed = math.hypot(vx, vy)
            if speed > MAX_THROW:
                vx, vy = vx / speed * MAX_THROW, vy / speed * MAX_THROW
            self.vx, self.vy = vx, vy
        else:
            self.vx = self.vy = 0.0  # released without moving: just drop it
 
    def toggle_gravity(self):
        self.gravity = not self.gravity
 
    def reset(self):
        w, h = self.size()
        self.x, self.y, self.vx, self.vy, self.held = w / 2, h / 3, 420.0, -260.0, False
 
    def size(self):
        return max(self.canvas.winfo_width(), 2 * RADIUS + 1), max(self.canvas.winfo_height(), 2 * RADIUS + 1)
 
    # ---------- simulation ----------
    def tick(self):
        now = time.perf_counter()
        dt = min(now - self.last, 1 / 30)
        self.last = now
        w, h = self.size()
 
        if not self.held:
            if self.gravity:
                self.vy += GRAVITY * dt
            drag = max(0.0, 1 - AIR_DRAG * dt)
            self.vx *= drag
            self.vy *= drag
            self.x += self.vx * dt
            self.y += self.vy * dt
 
            if self.x < RADIUS:
                self.x, self.vx = RADIUS, abs(self.vx) * BOUNCE
            elif self.x > w - RADIUS:
                self.x, self.vx = w - RADIUS, -abs(self.vx) * BOUNCE
            if self.y < RADIUS:
                self.y, self.vy = RADIUS, abs(self.vy) * BOUNCE
            elif self.y > h - RADIUS:
                self.y, self.vy = h - RADIUS, -abs(self.vy) * BOUNCE
                self.vx *= 0.99  # floor friction
                if abs(self.vy) < 40 and self.gravity:
                    self.vy = 0.0
            # keep it lively when gravity is off
            if not self.gravity and math.hypot(self.vx, self.vy) < 1:
                self.vx, self.vy = 300.0, 200.0
 
        self.draw(w, h)
        self.root.after(int(1000 / FPS), self.tick)
 
    def draw(self, w, h):
        r, x, y = RADIUS, self.x, self.y
        c = self.canvas
        c.coords(self.ball, x - r, y - r, x + r, y + r)
        c.itemconfig(self.ball, fill=BALL_HELD if self.held else BALL)
        c.coords(self.shine, x - r * 0.55, y - r * 0.6, x - r * 0.1, y - r * 0.2)
        # shadow on the floor, smaller the higher the ball is
        k = 1 - min((h - y) / h, 1) * 0.7
        c.coords(self.shadow, x - r * k, h - 8, x + r * k, h - 2)
        speed = math.hypot(self.vx, self.vy)
        c.itemconfig(self.hud, text=(
            f"{'HOLDING' if self.held else f'speed {speed:5.0f} px/s'}   ·   gravity {'on' if self.gravity else 'off'} (Space)"
            "   ·   drag the ball to throw it   ·   R reset   ·   Esc quit"))
 
 
if __name__ == "__main__":
    root = tk.Tk()
    BallApp(root)
    root.mainloop()
 

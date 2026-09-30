"""
PEARL DIVER — an undersea maze-chase game.

Steer your little submarine through the reef, collect every pearl, and avoid
the jellyfish. Grab a glowing starfish to turn the tables: for a few seconds
the jellyfish go pale and you can sting them back for bonus points.

Controls
  Arrow keys / WASD   steer (you can pre-press a turn before a corner)
  P                   pause
  Enter               start / continue
  Esc                 quit

Run:  python3 pearl_diver.py      (uses tkinter, which ships with Python)
"""
import json
import math
import os
import random
import time
import tkinter as tk

# ------------------------------------------------------------------ maze
# '#' reef wall   '.' pearl   'o' starfish (power-up)   'P' player start
# 'J' jellyfish home   '-' home gate   'T' side tunnel (wraps around)
MAZE = [
    "#####################",
    "#o........#........o#",
    "#.###.###.#.###.###.#",
    "#...................#",
    "#.###.#.#####.#.###.#",
    "#.....#...#...#.....#",
    "#####.###.#.###.#####",
    "#####.#.......#.#####",
    "#####.#.##-##.#.#####",
    "T.......#JJJ#.......T",
    "#####.#.#####.#.#####",
    "#####.#.......#.#####",
    "#####.#.#####.#.#####",
    "#.........#.........#",
    "#.###.###.#.###.###.#",
    "#o..#.....P.....#..o#",
    "###.#.#.#####.#.#.###",
    "#.....#...#...#.....#",
    "#.#######.#.#######.#",
    "#...................#",
    "#####################",
]
COLS, ROWS = len(MAZE[0]), len(MAZE)
TILE = 30
HUD_H = 56
W, H = COLS * TILE, ROWS * TILE + HUD_H

DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
OPP = {"up": "down", "down": "up", "left": "right", "right": "left"}
KEYMAP = {"Up": "up", "Down": "down", "Left": "left", "Right": "right",
          "w": "up", "s": "down", "a": "left", "d": "right",
          "W": "up", "S": "down", "A": "left", "D": "right"}

SEA = "#06131f"
REEF_FILL = "#0f3a4a"
REEF_EDGE = "#2fb3a8"
PEARL = "#f3efe6"
SUB = "#ff9f1c"
JELLY_COLORS = ["#ff4f9a", "#b57bff", "#8ee04a", "#3fd0ff"]
FRIGHT = "#cfe3ff"

HOME = next((c, r) for r, row in enumerate(MAZE) for c, ch in enumerate(row) if ch == "-")
GATE = HOME                                       # tile of the gate
HOME_IN = (GATE[0], GATE[1] + 1)                  # center tile inside the home
HOME_OUT = (GATE[0], GATE[1] - 1)                 # tile just outside the gate
SAVE = os.path.join(os.path.expanduser("~"), ".pearl_diver_highscore.json")


def load_high():
    try:
        with open(SAVE) as f:
            return int(json.load(f).get("high", 0))
    except Exception:
        return 0


def save_high(v):
    try:
        with open(SAVE, "w") as f:
            json.dump({"high": v}, f)
    except Exception:
        pass


def wall(c, r, jelly=False, leaving=False):
    """True if tile blocks movement. The gate only lets jellyfish through."""
    if r < 0 or r >= ROWS:
        return True
    c %= COLS
    ch = MAZE[r][c]
    if ch == "#":
        return True
    if ch == "-":
        return not (jelly and leaving)
    if ch == "J" and not jelly:
        return True
    return False


def bfs_step(start, goal):
    """First direction on the shortest jellyfish path from start to goal (gate passable)."""
    from collections import deque
    if start == goal:
        return None
    q, first = deque([start]), {start: None}
    while q:
        c, r = q.popleft()
        for d, (dx, dy) in DIRS.items():
            n = ((c + dx) % COLS, r + dy)
            if n in first or wall(*n, jelly=True, leaving=True):
                continue
            first[n] = first[(c, r)] or d
            if n == goal:
                return first[n]
            q.append(n)
    return None


# ------------------------------------------------------------------ actors
class Mover:
    """Tile-to-tile movement with a fractional progress value, so motion is smooth."""

    def __init__(self, c, r, speed):
        self.c, self.r = c, r          # tile we are leaving
        self.dir = None
        self.p = 0.0                   # 0..1 progress toward next tile
        self.speed = speed             # tiles per second

    def pos(self):
        if not self.dir:
            return self.c, self.r
        dx, dy = DIRS[self.dir]
        x, y = self.c + dx * self.p, self.r + dy * self.p
        # smooth wrap through the tunnel
        if x < -0.5:
            x += COLS
        if x > COLS - 0.5:
            x -= COLS
        return x, y

    def next_tile(self, d):
        dx, dy = DIRS[d]
        return (self.c + dx) % COLS, self.r + dy


class Sub(Mover):
    def __init__(self, c, r):
        super().__init__(c, r, 7.0)
        self.want = "left"
        self.face = "left"
        self.anim = 0.0

    def update(self, dt, on_arrive):
        self.anim += dt
        # instant reverse mid-corridor
        if self.dir and self.want == OPP[self.dir]:
            self.c, self.r = self.next_tile(self.dir)
            self.dir, self.p = self.want, 1 - self.p
        if not self.dir:
            if not wall(*self.next_tile(self.want)):
                self.dir = self.want
            else:
                return
        self.face = self.dir
        self.p += self.speed * dt
        while self.p >= 1:
            self.p -= 1
            self.c, self.r = self.next_tile(self.dir)
            on_arrive(self.c, self.r)
            if not wall(*self.next_tile(self.want)):
                self.dir = self.want
            elif wall(*self.next_tile(self.dir)):
                self.dir, self.p = None, 0.0
                break
            self.face = self.dir


class Jelly(Mover):
    def __init__(self, idx, c, r, release):
        super().__init__(c, r, 6.0)
        self.idx = idx
        self.color = JELLY_COLORS[idx]
        self.home_corner = [(COLS - 2, 0), (1, 0), (COLS - 2, ROWS), (1, ROWS)][idx]
        self.state = "home"            # home, leaving, roam, eaten
        self.release = release         # seconds before leaving home
        self.bob = random.random() * 6

    def targets(self, game):
        s = game.sub
        if self.state == "eaten":
            return HOME_IN
        if self.state == "leaving":
            return HOME_OUT
        if game.mode == "scatter":
            return self.home_corner
        sx, sy = s.c, s.r
        fx, fy = DIRS[s.face]
        if self.idx == 0:                           # direct hunter
            return sx, sy
        if self.idx == 1:                           # cuts you off ahead
            return sx + fx * 4, sy + fy * 4
        if self.idx == 2:                           # pincer with the first jelly
            ax, ay = sx + fx * 2, sy + fy * 2
            j0 = game.jellies[0]
            return ax * 2 - j0.c, ay * 2 - j0.r
        if math.hypot(sx - self.c, sy - self.r) > 7:   # shy one: chases, then backs off
            return sx, sy
        return self.home_corner

    def choose(self, game):
        leaving = self.state in ("leaving", "eaten")
        options = []
        for d in ("up", "left", "down", "right"):
            if self.dir and d == OPP[self.dir] and self.state not in ("leaving", "eaten"):
                continue
            nc, nr = self.next_tile(d)
            if not wall(nc, nr, jelly=True, leaving=leaving):
                options.append(d)
        if not options:
            return OPP[self.dir] if self.dir else None
        if self.state in ("leaving", "eaten"):          # shortest route home / out of home
            step = bfs_step((self.c, self.r), self.targets(game))
            if step in options:
                return step
        if game.fright > 0 and self.state == "roam":
            return random.choice(options)
        tx, ty = self.targets(game)
        return min(options, key=lambda d: math.hypot(self.next_tile(d)[0] - tx, self.next_tile(d)[1] - ty))

    def update(self, dt, game):
        self.bob += dt * 5
        if self.state == "home":
            self.release -= dt
            if self.release <= 0:
                self.state = "leaving"
                self.c, self.r, self.dir, self.p = HOME_IN[0], HOME_IN[1], None, 0
            return
        spd = self.speed
        if self.state == "eaten":
            spd = 14
        elif game.fright > 0 and self.state == "roam":
            spd *= 0.55
        elif self.r == 9 and (self.c <= 4 or self.c >= COLS - 5):
            spd *= 0.6                                 # slow in the tunnel
        if not self.dir:
            self.dir = self.choose(game)
            if not self.dir:
                return
        self.p += spd * dt
        while self.p >= 1:
            self.p -= 1
            self.c, self.r = self.next_tile(self.dir)
            if self.state == "leaving" and (self.c, self.r) == HOME_OUT:
                self.state = "roam"
            elif self.state == "eaten" and (self.c, self.r) == HOME_IN:
                self.state = "leaving"
            self.dir = self.choose(game)
            if not self.dir:
                self.p = 0
                break

    def reverse(self):
        if self.state == "roam" and self.dir:
            self.c, self.r = self.next_tile(self.dir)
            self.dir, self.p = OPP[self.dir], 1 - self.p


# ------------------------------------------------------------------ game
class Game:
    def __init__(self, root):
        self.root = root
        root.title("Pearl Diver")
        root.resizable(False, False)
        self.cv = tk.Canvas(root, width=W, height=H, bg=SEA, highlightthickness=0)
        self.cv.pack()
        root.bind("<KeyPress>", self.on_key)
        self.high = load_high()
        self.state = "title"          # title, ready, play, dying, cleared, over, paused
        self.draw_reef()
        self.new_game()
        self.last = time.perf_counter()
        self.loop()

    # ---------------- setup
    def new_game(self):
        self.score, self.lives, self.level = 0, 3, 1
        self.extra_given = False
        self.new_level()

    def new_level(self):
        self.pearls = {}
        self.cv.delete("pearl")
        for r, row in enumerate(MAZE):
            for c, ch in enumerate(row):
                if ch in ".o":
                    x, y = c * TILE + TILE / 2, r * TILE + TILE / 2 + HUD_H
                    if ch == ".":
                        item = self.cv.create_oval(x - 3, y - 3, x + 3, y + 3, fill=PEARL, outline="", tags="pearl")
                    else:
                        item = self.cv.create_text(x, y, text="✶", fill="#ffd166", font=("Helvetica", 20, "bold"), tags=("pearl", "star"))
                    self.pearls[(c, r)] = (ch, item)
        self.total = len(self.pearls)
        self.bonus = None
        self.bonus_spawned = 0
        self.reset_actors()

    def reset_actors(self):
        pc, pr = next((c, r) for r, row in enumerate(MAZE) for c, ch in enumerate(row) if ch == "P")
        self.sub = Sub(pc, pr)
        self.sub.speed = 7.0 + min(self.level, 8) * 0.2
        jspeed = 5.6 + min(self.level, 8) * 0.35
        self.jellies = []
        for i in range(4):
            j = Jelly(i, HOME_IN[0] + (i - 2) if i else HOME_OUT[0], HOME_IN[1] if i else HOME_OUT[1], [0, 2.5, 6, 10][i] / (1 + (self.level - 1) * 0.25))
            if i == 0:
                j.state = "roam"
            j.speed = jspeed
            self.jellies.append(j)
        self.mode, self.mode_t, self.mode_i = "scatter", 0.0, 0
        self.fright, self.combo = 0.0, 0
        self.ready_t = 2.0
        self.popups = []
        if self.state != "title":
            self.state = "ready"

    # ---------------- input
    def on_key(self, e):
        k = e.keysym
        if k == "Escape":
            self.root.destroy()
            return
        if k in KEYMAP:
            self.sub.want = KEYMAP[k]
        if k in ("Return", "KP_Enter", "space"):
            if self.state == "title":
                self.state = "ready"
            elif self.state == "over":
                self.state = "ready"
                self.new_game()
            elif self.state == "paused":
                self.state = "play"
        if k in ("p", "P"):
            self.state = {"play": "paused", "paused": "play"}.get(self.state, self.state)

    # ---------------- rules
    MODE_TIMES = [("scatter", 7), ("chase", 20), ("scatter", 7), ("chase", 20), ("scatter", 5), ("chase", 9999)]

    def add_score(self, pts, x=None, y=None):
        self.score += pts
        if not self.extra_given and self.score >= 10000:
            self.extra_given = True
            self.lives += 1
        if self.score > self.high:
            self.high = self.score
        if x is not None:
            self.popups.append([x, y, str(pts), 1.0])

    def eat(self, c, r):
        item = self.pearls.pop((c, r), None)
        if not item:
            if self.bonus and (c, r) == self.bonus[0]:
                self.add_score(self.bonus[1], c, r)
                self.bonus = None
            return
        ch, cid = item
        self.cv.delete(cid)
        if ch == ".":
            self.add_score(10)
        else:
            self.add_score(50)
            self.fright = max(1.5, 7.0 - (self.level - 1) * 0.8)
            self.combo = 0
            for j in self.jellies:
                j.reverse()
        eaten = self.total - len(self.pearls)
        if self.bonus_spawned < 2 and eaten in (60, 140):
            self.bonus_spawned += 1
            self.bonus = ((10, 13), 300 + 200 * min(self.level, 10), 9.0)
        if not self.pearls:
            self.state, self.clear_t = "cleared", 2.5

    def update(self, dt):
        if self.state == "ready":
            self.ready_t -= dt
            if self.ready_t <= 0:
                self.state = "play"
            return
        if self.state == "dying":
            self.die_t -= dt
            if self.die_t <= 0:
                if self.lives <= 0:
                    self.state = "over"
                    save_high(self.high)
                else:
                    self.reset_actors()
            return
        if self.state == "cleared":
            self.clear_t -= dt
            if self.clear_t <= 0:
                self.level += 1
                self.new_level()
                self.state = "ready"
            return
        if self.state != "play":
            return

        # scatter/chase schedule pauses while jellies are frightened
        if self.fright > 0:
            self.fright -= dt
        else:
            self.mode_t += dt
            name, dur = self.MODE_TIMES[self.mode_i]
            if self.mode_t >= dur and self.mode_i < len(self.MODE_TIMES) - 1:
                self.mode_i += 1
                self.mode_t = 0
                self.mode = self.MODE_TIMES[self.mode_i][0]
                for j in self.jellies:
                    j.reverse()
        if self.bonus:
            t = self.bonus[2] - dt
            self.bonus = (self.bonus[0], self.bonus[1], t) if t > 0 else None

        self.sub.update(dt, self.eat)
        for j in self.jellies:
            j.update(dt, self)

        sx, sy = self.sub.pos()
        for j in self.jellies:
            if j.state in ("home", "leaving", "eaten") and not (j.state == "leaving" and j.r < 9):
                continue
            jx, jy = j.pos()
            d = min(abs(sx - jx), COLS - abs(sx - jx))
            if d < 0.6 and abs(sy - jy) < 0.6:
                if self.fright > 0 and j.state == "roam":
                    self.combo += 1
                    self.add_score(200 * 2 ** (self.combo - 1), jx, jy)
                    j.state = "eaten"
                else:
                    self.lives -= 1
                    self.state, self.die_t = "dying", 1.6
                    return
        for p in self.popups:
            p[3] -= dt
        self.popups = [p for p in self.popups if p[3] > 0]

    # ---------------- drawing
    def px(self, x, y):
        return x * TILE + TILE / 2, y * TILE + TILE / 2 + HUD_H

    def draw_reef(self):
        for r, row in enumerate(MAZE):
            for c, ch in enumerate(row):
                x0, y0 = c * TILE, r * TILE + HUD_H
                if ch == "#":
                    # connect to wall neighbours so the reef reads as solid shapes
                    pad = 4
                    l = 0 if c > 0 and MAZE[r][c - 1] == "#" else pad
                    rt = 0 if c < COLS - 1 and MAZE[r][c + 1] == "#" else pad
                    t = 0 if r > 0 and MAZE[r - 1][c] == "#" else pad
                    b = 0 if r < ROWS - 1 and MAZE[r + 1][c] == "#" else pad
                    self.cv.create_rectangle(x0 + l, y0 + t, x0 + TILE - rt, y0 + TILE - b, fill=REEF_FILL, outline="")
                    if l:
                        self.cv.create_line(x0 + l, y0 + t, x0 + l, y0 + TILE - b, fill=REEF_EDGE, width=2)
                    if rt:
                        self.cv.create_line(x0 + TILE - rt, y0 + t, x0 + TILE - rt, y0 + TILE - b, fill=REEF_EDGE, width=2)
                    if t:
                        self.cv.create_line(x0 + l, y0 + t, x0 + TILE - rt, y0 + t, fill=REEF_EDGE, width=2)
                    if b:
                        self.cv.create_line(x0 + l, y0 + TILE - b, x0 + TILE - rt, y0 + TILE - b, fill=REEF_EDGE, width=2)
                elif ch == "-":
                    self.cv.create_line(x0 + 2, y0 + TILE / 2, x0 + TILE - 2, y0 + TILE / 2, fill="#ff9ec7", width=3)
        # a few bubbles for atmosphere
        for _ in range(25):
            x, y, s = random.uniform(0, W), random.uniform(HUD_H, H), random.uniform(1, 3)
            self.cv.create_oval(x - s, y - s, x + s, y + s, outline="#1d4a5e")

    def draw_sub(self):
        s = self.sub
        x, y = self.px(*s.pos())
        ang = {"right": 0, "left": math.pi, "up": -math.pi / 2, "down": math.pi / 2}[s.face]
        ca, sa = math.cos(ang), math.sin(ang)

        def rot(px, py):
            return x + px * ca - py * sa, y + px * sa + py * ca

        if self.state == "dying":
            k = max(self.die_t / 1.6, 0)
            r = 11 * k + 1
            self.cv.create_oval(x - r, y - r, x + r, y + r, fill=SUB, outline="", tags="dyn")
            for i in range(8):
                a = i / 8 * math.tau
                d = 16 * (1 - k) + 6
                self.cv.create_oval(x + math.cos(a) * d - 2, y + math.sin(a) * d - 2, x + math.cos(a) * d + 2, y + math.sin(a) * d + 2, outline="#9fe8ff", tags="dyn")
            return
        body = [rot(px, py) for px, py in [(-11, -7), (5, -8), (12, -3), (12, 3), (5, 8), (-11, 7)]]
        self.cv.create_polygon(*[v for p in body for v in p], fill=SUB, outline="#ffd29a", width=1, smooth=True, tags="dyn")
        tower = [rot(px, py) for px, py in [(-4, -8), (3, -8), (2, -12), (-3, -12)]]
        self.cv.create_polygon(*[v for p in tower for v in p], fill="#e07f00", outline="", tags="dyn")
        wx, wy = rot(4, 0)
        self.cv.create_oval(wx - 3.5, wy - 3.5, wx + 3.5, wy + 3.5, fill="#bff4ff", outline="#083042", tags="dyn")
        prop = math.sin(s.anim * 40) * 6
        a1, a2 = rot(-13, -prop), rot(-13, prop)
        self.cv.create_line(*a1, *a2, fill="#ffd29a", width=3, tags="dyn")

    def draw_jelly(self, j):
        x, y = self.px(*j.pos())
        if j.state == "eaten":
            self.cv.create_oval(x - 5, y - 5, x + 5, y + 5, outline=j.color, width=2, tags="dyn")
            return
        fr = self.fright > 0 and j.state == "roam"
        col = j.color
        if fr:
            col = FRIGHT if (self.fright > 2 or int(self.fright * 6) % 2 == 0) else "#ffffff"
        bob = math.sin(j.bob) * 1.5
        top = y - 11 + bob
        self.cv.create_arc(x - 11, top, x + 11, top + 22, start=0, extent=180, fill=col, outline="", tags="dyn")
        # tentacles
        for i in range(4):
            tx = x - 8 + i * 5.3
            pts = []
            for k in range(5):
                pts += [tx + math.sin(j.bob + i + k) * 2, y + bob + k * 3]
            self.cv.create_line(*pts, fill=col, width=2, smooth=True, tags="dyn")
        eye = "#1b1b3a" if not fr else "#6a7fb0"
        self.cv.create_oval(x - 5, y - 5 + bob, x - 2, y - 2 + bob, fill=eye, outline="", tags="dyn")
        self.cv.create_oval(x + 2, y - 5 + bob, x + 5, y - 2 + bob, fill=eye, outline="", tags="dyn")

    def draw(self):
        cv = self.cv
        cv.delete("dyn")
        # starfish pulse
        pulse = "#ffd166" if int(time.perf_counter() * 4) % 2 == 0 else "#fff1c4"
        cv.itemconfig("star", fill=pulse)
        # bonus treasure
        if self.bonus:
            bx, by = self.px(*self.bonus[0])
            cv.create_rectangle(bx - 9, by - 6, bx + 9, by + 7, fill="#8a5a2b", outline="#ffcf5a", width=2, tags="dyn")
            cv.create_line(bx - 9, by - 1, bx + 9, by - 1, fill="#ffcf5a", width=2, tags="dyn")
        for j in self.jellies:
            self.draw_jelly(j)
        if self.state != "over":
            self.draw_sub()
        for x, y, txt, t in self.popups:
            px, py = self.px(x, y)
            cv.create_text(px, py - (1 - t) * 14, text=txt, fill="#9fe8ff", font=("Helvetica", 12, "bold"), tags="dyn")
        # HUD
        cv.create_rectangle(0, 0, W, HUD_H, fill="#041019", outline="", tags="dyn")
        cv.create_text(14, 18, anchor="w", text=f"SCORE {self.score}", fill="#e9f4f7", font=("Helvetica", 16, "bold"), tags="dyn")
        cv.create_text(W / 2, 18, text=f"HIGH {self.high}", fill="#ffd166", font=("Helvetica", 14, "bold"), tags="dyn")
        cv.create_text(W - 14, 18, anchor="e", text=f"DEPTH {self.level}", fill="#9fe8ff", font=("Helvetica", 14, "bold"), tags="dyn")
        for i in range(self.lives):
            lx = 20 + i * 26
            cv.create_oval(lx - 9, 36, lx + 9, 48, fill=SUB, outline="", tags="dyn")
        # overlays
        msg, sub = None, None
        if self.state == "title":
            msg, sub = "PEARL DIVER", "Arrows / WASD to steer  ·  Enter to dive"
        elif self.state == "ready":
            msg = "READY"
        elif self.state == "paused":
            msg, sub = "PAUSED", "P or Enter to resume"
        elif self.state == "cleared":
            msg = "REEF CLEARED!"
        elif self.state == "over":
            msg, sub = "GAME OVER", "Enter to dive again"
        if msg:
            cy = HUD_H + 11 * TILE - TILE / 2
            if sub:
                cv.create_rectangle(W / 2 - 170, cy - 34, W / 2 + 170, cy + 40, fill="#041019", outline=REEF_EDGE, width=2, tags="dyn")
            cv.create_text(W / 2, cy - 6, text=msg, fill="#ffd166", font=("Helvetica", 26 if sub else 18, "bold"), tags="dyn")
            if sub:
                cv.create_text(W / 2, cy + 22, text=sub, fill="#cfe3ff", font=("Helvetica", 12), tags="dyn")

    def loop(self):
        now = time.perf_counter()
        dt = min(now - self.last, 1 / 20)
        self.last = now
        self.update(dt)
        self.draw()
        self.root.after(16, self.loop)


if __name__ == "__main__":
    root = tk.Tk()
    Game(root)
    root.mainloop()
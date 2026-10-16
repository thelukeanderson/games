#!/usr/bin/env python3
"""
STARWAKE — a neon side-scrolling shoot-'em-up that runs in your terminal.

Pilot the Wake through wave after wave of drones, darts, mine fields and
looping swarms, then take on the dreadnought that waits every fourth wave.
Everything is drawn with half-block characters, so every terminal cell holds
two square "pixels" in 256 colours — smooth movement, particles, parallax
mountains, a ringed planet and screen shake, all in plain text.

Controls
  Arrows / WASD     fly (the ship has momentum: it drifts, banks and glides)
  Space / Z         dash: a burst of speed with invulnerability — dash
                    straight through bullets
  X / B             smart bomb: a shockwave that wipes out enemy fire
  P / Esc           pause          Q   quit to title / quit the game
  (your guns fire automatically)

Pickups
  P  weapon power (wider spread shot, then homing missiles)
  S  shield (absorbs one hit)
  B  extra bomb

Run:  python3 starwake.py                  Linux or macOS, nothing to install
      python3 starwake.py --classic-keys   skip keyboard-protocol detection

Best in a terminal that speaks the kitty keyboard protocol (kitty, WezTerm,
foot, Ghostty, Alacritty, recent iTerm2): the game then sees real key
presses and releases. Any other terminal works too (GNOME Terminal,
macOS Terminal, ...); movement then rides on key-repeat and is a touch
floatier. Needs at least 64x22 characters; bigger is better.
"""
import json
import math
import os
import random
import re
import select
import signal
import sys
import termios
import time
import tty

FPS = 30
MIN_COLS, MIN_ROWS = 64, 22
MAX_W, MAX_ROWS = 140, 42          # pixel columns, playfield text rows (2 px each)
SCORE_FILE = os.path.expanduser('~/.starwake_scores.json')
TAU = math.pi * 2

# ------------------------------------------------------------------ colours
# 256-colour palette indices. Ramps go from hot/bright to cold/dark.
FIRE = [231, 230, 229, 228, 227, 226, 220, 214, 208, 202, 196, 160, 124, 88, 52]
CYAN = [231, 195, 159, 123, 87, 51, 45, 39, 33, 27, 25, 24, 23]
PINK = [231, 225, 219, 213, 207, 201, 200, 163, 127, 91, 54, 53]
LIME = [231, 230, 193, 156, 155, 154, 118, 82, 76, 70, 64, 28, 22]
GOLD = [231, 230, 229, 228, 227, 226, 220, 178, 136, 94]
SMOKE = [252, 250, 248, 246, 244, 242, 240, 238, 236, 234]
SUNSET = [226, 220, 214, 208, 209, 203, 204, 198, 199, 200, 201, 165]
PLANET = [233, 23, 24, 30, 31, 37, 38, 44, 80, 116, 152]
FG = ['\x1b[38;5;%dm' % i for i in range(256)]
BG = ['\x1b[48;5;%dm' % i for i in range(256)]


def _dim_table():
    """Byte translation table that darkens every 256-colour index."""
    t = bytearray(range(256))
    for c in range(16, 232):
        i = c - 16
        r, g, b = i // 36, (i // 6) % 6, i % 6
        t[c] = 16 + 36 * (r // 2) + 6 * (g // 2) + b // 2
    for c in range(232, 256):
        t[c] = 232 + (c - 232) // 3
    for c in range(16):
        t[c] = 16
    return bytes(t)


DIM = _dim_table()

# ------------------------------------------------------------------ pixel font (3x5)
_FONT_SRC = {
    'A': ".#. #.# ### #.# #.#", 'B': "##. #.# ##. #.# ##.", 'C': ".## #.. #.. #.. .##",
    'D': "##. #.# #.# #.# ##.", 'E': "### #.. ##. #.. ###", 'F': "### #.. ##. #.. #..",
    'G': ".## #.. #.# #.# .##", 'H': "#.# #.# ### #.# #.#", 'I': "### .#. .#. .#. ###",
    'J': "..# ..# ..# #.# .#.", 'K': "#.# #.# ##. #.# #.#", 'L': "#.. #.. #.. #.. ###",
    'M': "#.# ### ### #.# #.#", 'N': "##. #.# #.# #.# #.#", 'O': ".#. #.# #.# #.# .#.",
    'P': "##. #.# ##. #.. #..", 'Q': ".#. #.# #.# ##. .##", 'R': "##. #.# ##. #.# #.#",
    'S': ".## #.. .#. ..# ##.", 'T': "### .#. .#. .#. .#.", 'U': "#.# #.# #.# #.# ###",
    'V': "#.# #.# #.# #.# .#.", 'W': "#.# #.# ### ### #.#", 'X': "#.# #.# .#. #.# #.#",
    'Y': "#.# #.# .#. .#. .#.", 'Z': "### ..# .#. #.. ###",
    '0': "### #.# #.# #.# ###", '1': ".#. ##. .#. .#. ###", '2': "##. ..# .#. #.. ###",
    '3': "##. ..# .#. ..# ##.", '4': "#.# #.# ### ..# ..#", '5': "### #.. ##. ..# ##.",
    '6': ".## #.. ### #.# ###", '7': "### ..# .#. .#. .#.", '8': "### #.# ### #.# ###",
    '9': "### #.# ### ..# ##.", '+': "... .#. ### .#. ...", '-': "... ... ### ... ...",
    '!': ".#. .#. .#. ... .#.", '?': "##. ..# .#. ... .#.", '.': "... ... ... ... .#.",
    ':': "... .#. ... .#. ...", "'": ".#. .#. ... ... ...", ' ': "... ... ... ... ...",
}
FONT = {ch: [(x, y) for y, row in enumerate(src.split()) for x, b in enumerate(row) if b == '#']
        for ch, src in _FONT_SRC.items()}


def text_width(s, scale=1):
    return max(0, len(s) * 4 * scale - scale)


# ------------------------------------------------------------------ sprites
def compile_sprite(rows, pal):
    pts = []
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch != '.':
                pts.append((x, y, pal[ch]))
    return (max(len(r) for r in rows), len(rows), pts)


_PLAYER = ["bb.......",
           ".bccc....",
           "abcdddwwd",
           ".bccc....",
           "bb......."]
_PLAYER_BANK = [".b.......",
                ".bccc....",
                "abcdddwwd",
                "bbccc....",
                "bbb......"]
_PPAL = {'a': 24, 'b': 31, 'c': 45, 'd': 159, 'w': 231}

SPR = {
    'player': compile_sprite(_PLAYER, _PPAL),
    'player_up': compile_sprite(_PLAYER_BANK, _PPAL),
    'player_down': compile_sprite(_PLAYER_BANK[::-1], _PPAL),
    'drone': compile_sprite(["..mmm.",
                             ".mMMMm",
                             "mwMMMm",
                             ".mMMMm",
                             "..mmm."], {'m': 127, 'M': 201, 'w': 226}),
    'dart': compile_sprite(["...yyY",
                            "wYYYYY",
                            "...yyY"], {'y': 136, 'Y': 220, 'w': 231}),
    'pod': compile_sprite(["..gggg..",
                           ".gGGGGg.",
                           "gGwwGGGg",
                           "gGwwGGGg",
                           ".gGGGGg.",
                           "..gggg.."], {'g': 28, 'G': 42, 'w': 226}),
    'spin0': compile_sprite(["..c..",
                             "..C..",
                             "cCwCc",
                             "..C..",
                             "..c.."], {'c': 166, 'C': 208, 'w': 231}),
    'spin1': compile_sprite(["c...c",
                             ".C.C.",
                             "..w..",
                             ".C.C.",
                             "c...c"], {'c': 166, 'C': 208, 'w': 231}),
    'mine0': compile_sprite([".r.r.",
                             "rRRRr",
                             ".RwR.",
                             "rRRRr",
                             ".r.r."], {'r': 88, 'R': 160, 'w': 196}),
    'mine1': compile_sprite([".r.r.",
                             "rRRRr",
                             ".RwR.",
                             "rRRRr",
                             ".r.r."], {'r': 88, 'R': 160, 'w': 231}),
    'gnat': compile_sprite([".a.",
                            "aAa",
                            ".a."], {'a': 70, 'A': 154}),
}
_BOSS = ["...........kkkkkk.....",
         ".......kkkkKKKKKKkk...",
         ".....kkKKKKKKKKKKKKk..",
         "...kkKKKgKKKgKKKgKKKk.",
         "..kKKKKKgKKKgKKKgKKKKk",
         ".kKKwwKKKKKKKKKKKKKKKk",
         "kKKwrrwKKKkkkkkkKKKKKk",
         "kKKwrrwKKKkkkkkkKKKKKk",
         ".kKKwwKKKKKKKKKKKKKKKk",
         "..kKKKKKgKKKgKKKgKKKKk",
         "...kkKKKgKKKgKKKgKKKk.",
         ".....kkKKKKKKKKKKKKk..",
         ".......kkkkKKKKKKkk...",
         "...........kkkkkk....."]
SPR['boss'] = compile_sprite(_BOSS, {'k': 238, 'K': 61, 'g': 141, 'w': 250, 'r': 196})
SPR['boss_angry'] = compile_sprite(_BOSS, {'k': 237, 'K': 125, 'g': 213, 'w': 250, 'r': 196})
BOSS_EYE = [(x, y) for x, y, c in SPR['boss'][2] if c == 196]

_debris_ramps = {}


def debris_ramp(c):
    r = _debris_ramps.get(c)
    if r is None:
        r = _debris_ramps[c] = [231, c, c, c, c, 244, 240, 237]
    return r


def make_planet(R):
    """Pre-shade a gas giant with a tilted ring: (back ring, body, front ring)."""
    body, back, front = [], [], []
    lx, ly, lz = 0.62, -0.5, 0.6
    n = math.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx / n, ly / n, lz / n
    for dy in range(-R, R + 1):
        for dx in range(-R, R + 1):
            if dx * dx + dy * dy <= R * R + R * 0.5:
                nx, ny = dx / R, dy / R
                nz = math.sqrt(max(0.0, 1 - nx * nx - ny * ny))
                light = nx * lx + ny * ly + nz * lz + 0.09 * math.sin(dy * 1.4 + dx * 0.15)
                i = int((light * 0.55 + 0.45) * len(PLANET))
                body.append((dx, dy, PLANET[max(0, min(len(PLANET) - 1, i))]))
    tilt = -0.32
    ct, st = math.cos(tilt), math.sin(tilt)
    seen = set()
    for radius, col in ((1.75, 137), (1.95, 180), (2.15, 223)):
        steps = int(R * 16)
        for k in range(steps):
            a = TAU * k / steps
            px, py = math.cos(a) * R * radius, math.sin(a) * R * radius * 0.28
            rx, ry = round(px * ct - py * st), round(px * st + py * ct)
            if (rx, ry) in seen:
                continue
            seen.add((rx, ry))
            (front if math.sin(a) > 0 else back).append((rx, ry, col))
    return back, body, front


def make_ridge(length, comps):
    tab = []
    for i in range(length):
        tab.append(sum(a * math.sin(TAU * cyc * i / length + ph) for a, cyc, ph in comps))
    return tab


RIDGE_LEN = 4096
FAR_RIDGE = make_ridge(RIDGE_LEN, [(4.0, 30, 0.3), (2.5, 77, 1.9), (1.2, 190, 4.0)])
NEAR_RIDGE = make_ridge(RIDGE_LEN, [(3.0, 50, 2.0), (2.0, 120, 0.4), (1.0, 300, 5.1)])


# ------------------------------------------------------------------ terminal + input
ARROWS = {'A': 'up', 'B': 'down', 'C': 'right', 'D': 'left'}
CHARS = {'\r': 'enter', '\n': 'enter', ' ': 'space', '\x03': 'ctrl-c',
         '\x7f': 'backspace', '\x08': 'backspace', '\t': 'tab'}
KITTY = {13: 'enter', 27: 'esc', 32: 'space', 127: 'backspace', 9: 'tab', 8: 'backspace'}
KINDS = {1: 'press', 2: 'repeat', 3: 'release'}


def csi_event(params, final):
    if params[:1] in ('?', '>', '='):
        return None                      # a reply to one of our queries
    try:
        parts = params.split(';')
        mods, kind = 0, 'press'
        if len(parts) > 1:
            sub = parts[1].split(':')
            mods = int(sub[0] or 1) - 1
            if len(sub) > 1 and sub[1]:
                kind = KINDS.get(int(sub[1]), 'press')
        if final in ARROWS:
            return (ARROWS[final], kind)
        if final == 'u':
            code = int(parts[0].split(':')[0] or 0)
            if code == 99 and mods & 4:
                return ('ctrl-c', kind)
            key = KITTY.get(code)
            if key is None and 32 < code < 127:
                key = chr(code).lower()
            return (key, kind) if key else None
    except ValueError:
        pass
    return None


def parse_keys(s, flush):
    """Turn raw terminal input into (key, kind) events.

    Returns (events, leftover) where leftover is an incomplete escape
    sequence to retry next frame (unless flush is set)."""
    ev = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == '\x1b':
            if i + 1 >= n:
                if flush:
                    ev.append(('esc', 'press'))
                    i += 1
                    continue
                return ev, s[i:]
            nxt = s[i + 1]
            if nxt == '[':
                j = i + 2
                while j < n and not ('\x40' <= s[j] <= '\x7e'):
                    j += 1
                if j >= n:
                    return (ev, '') if flush else (ev, s[i:])
                e = csi_event(s[i + 2:j], s[j])
                if e:
                    ev.append(e)
                i = j + 1
                continue
            if nxt == 'O':
                if i + 2 >= n:
                    return (ev, '') if flush else (ev, s[i:])
                k = ARROWS.get(s[i + 2])
                if k:
                    ev.append((k, 'press'))
                i += 3
                continue
            ev.append(('esc', 'press'))
            i += 1
            continue
        ev.append((CHARS.get(ch, ch.lower()), 'press'))
        i += 1
    return ev, ''


class Terminal:
    def __init__(self):
        self.fd_in = sys.stdin.fileno()
        self.fd_out = sys.stdout.fileno()
        self.old = None
        self.kitty = False
        self.pending = ''

    def __enter__(self):
        self.old = termios.tcgetattr(self.fd_in)
        tty.setraw(self.fd_in)
        self.write('\x1b[?1049h\x1b[?25l\x1b[0m\x1b[2J')
        return self

    def __exit__(self, *exc):
        if self.kitty:
            self.write('\x1b[<u')
        self.write('\x1b[0m\x1b[2J\x1b[?25h\x1b[?1049l')
        termios.tcsetattr(self.fd_in, termios.TCSADRAIN, self.old)
        return False

    def write(self, s):
        data = s.encode('utf-8')
        while data:
            try:
                n = os.write(self.fd_out, data)
            except BlockingIOError:
                select.select([], [self.fd_out], [], 0.05)
                continue
            data = data[n:]

    def size(self):
        try:
            sz = os.get_terminal_size(self.fd_out)
            return sz.columns, sz.lines
        except OSError:
            return 80, 24

    def detect_kitty(self):
        """Ask the terminal whether it speaks the kitty keyboard protocol."""
        self.write('\x1b[?u\x1b[c')
        deadline = time.monotonic() + 0.4
        data = b''
        while time.monotonic() < deadline:
            r, _, _ = select.select([self.fd_in], [], [], max(0, deadline - time.monotonic()))
            if r:
                data += os.read(self.fd_in, 1024)
                if re.search(rb'\x1b\[\?[\d;]*c', data):
                    break
        if re.search(rb'\x1b\[\?\d+u', data):
            # 1 disambiguate + 2 press/repeat/release + 8 all keys as escapes
            self.write('\x1b[>11u')
            self.kitty = True

    def read_events(self):
        data = b''
        while select.select([self.fd_in], [], [], 0)[0]:
            chunk = os.read(self.fd_in, 4096)
            if not chunk:
                break
            data += chunk
        if not data and not self.pending:
            return []
        events, self.pending = parse_keys(self.pending + data.decode('utf-8', 'ignore'),
                                          flush=not data)
        return events


class Input:
    """Tracks which keys are held.

    With the kitty protocol we get real releases. Otherwise a key counts as
    held for a moment after each press/repeat, long enough to bridge the
    terminal's initial key-repeat delay."""
    ALIAS = {'w': 'up', 'a': 'left', 's': 'down', 'd': 'right'}
    OPP = {'left': 'right', 'right': 'left', 'up': 'down', 'down': 'up'}
    FIRST_HOLD = 0.25
    REPEAT_HOLD = 0.13

    def __init__(self, kitty):
        self.kitty = kitty
        self.held = {}
        self.pressed = set()
        self.typed = []

    def feed(self, events, now):
        for raw, kind in events:
            key = self.ALIAS.get(raw, raw)
            if kind == 'release':
                self.held.pop(key, None)
                self.held.pop(raw, None)
                continue
            self.typed.append(raw)
            if self.kitty:
                if kind == 'press':
                    self.pressed.update((raw, key))
                self.held[key] = float('inf')
            else:
                exp = self.held.get(key)
                if exp is None or exp <= now:
                    self.pressed.update((raw, key))
                    self.held[key] = now + self.FIRST_HOLD
                else:
                    self.held[key] = now + self.REPEAT_HOLD
                opp = self.OPP.get(key)
                if opp:
                    self.held.pop(opp, None)

    def down(self, key, now):
        return self.held.get(key, 0) > now

    def hit(self, *keys):
        return any(k in self.pressed for k in keys)

    def end_frame(self):
        self.pressed.clear()
        self.typed.clear()


# ------------------------------------------------------------------ entities
class Player:
    def __init__(self, y):
        self.x, self.y = -12.0, y
        self.vx = self.vy = 0.0
        self.lives, self.bombs, self.power = 3, 2, 1
        self.shield = False
        self.inv = 2.0
        self.dash_t = self.dash_cd = 0.0
        self.dash_v = (0.0, 0.0)
        self.fire_cd = self.missile_cd = 0.0
        self.alive = True
        self.respawn = 0.0
        self.enter_t = 0.9
        self.bank = 0
        self.ghosts = []


class Enemy:
    def __init__(self, kind, x, y, hp, score, spr):
        self.kind, self.x, self.y = kind, x, y
        self.hp = self.maxhp = hp
        self.score = score
        self.spr = spr
        self.w, self.h = spr[0], spr[1]
        self.t = 0.0
        self.flash = 0.0
        self.dead = False
        self.group = None
        self.vy = 0.0
        self.m = {}


def build_wave(n):
    pool = ['sine', 'darts']
    if n >= 2:
        pool += ['pods', 'mines']
    if n >= 3:
        pool += ['spinners', 'loopers']
    events, t, last = [], 1.8, None
    for _ in range(min(12, 4 + n)):
        kind = random.choice([k for k in pool if k != last] or pool)
        events.append((t, kind))
        last = kind
        t += max(1.5, 3.8 - n * 0.18) + random.uniform(0, 1.3)
    return events


def load_scores():
    try:
        with open(SCORE_FILE) as f:
            data = json.load(f)
        return sorted([d for d in data if isinstance(d, dict)],
                      key=lambda d: -d.get('score', 0))[:5]
    except (OSError, ValueError):
        return []


def save_scores(scores):
    try:
        with open(SCORE_FILE, 'w') as f:
            json.dump(scores, f)
    except OSError:
        pass


# ------------------------------------------------------------------ the game
class Game:
    def __init__(self, term):
        self.term = term
        self.inp = Input(term.kitty)
        self.scores = load_scores()
        self.state = 'title'
        self.running = True
        self.resized = True
        self.too_small = False
        self.W = self.H = 0
        self.ox = self.oy = 0
        self.t = 0.0
        self.now = time.monotonic()
        self.shake = self.flash = 0.0
        self.warp = self.warp_target = 1.0
        self.far_x = self.near_x = 0.0
        self.overlay = {}
        self.prev = []
        self.prev_hud = None
        self.score = 0
        self.wave = 0
        self.player = None
        self.clear_world()

    # ---------------------------------------------------------- setup
    def clear_world(self):
        self.enemies, self.pbullets, self.missiles, self.ebullets = [], [], [], []
        self.pickups, self.particles, self.rings, self.texts = [], [], [], []
        self.bomb = None
        self.boss = None
        self.boss_dying = None
        self.banner = None
        self.wave_events = []
        self.intermission = None
        self.over = False
        self.over_t = 0.0

    def layout(self):
        self.resized = False
        cols, rows = self.term.size()
        self.too_small = cols < MIN_COLS or rows < MIN_ROWS
        self.term.write('\x1b[0m\x1b[2J')
        if self.too_small:
            msg = 'STARWAKE needs at least %dx%d (now %dx%d) - enlarge the window' % (
                MIN_COLS, MIN_ROWS, cols, rows)
            self.term.write('\x1b[%d;1H%s' % (max(1, rows // 2), msg[:cols]))
            return
        W = min(cols, MAX_W)
        prow = min(rows - 1, MAX_ROWS)
        H = prow * 2
        self.mx = (cols - W) // 2
        self.my = (rows - 1 - prow) // 2
        if (W, H) != (self.W, self.H):
            old_h = self.H
            self.W, self.H, self.prow = W, H, prow
            self.fb = bytearray(W * H)
            base = bytearray(W * H)
            for y in range(H):
                f = y / H
                c = 16 if f < 0.6 else 232 if f < 0.8 else 233
                base[y * W:(y + 1) * W] = bytes((c,)) * W
            self.base = bytes(base)
            self.stars = []
            for speed, col, density in ((3.0, 237, 260), (8.0, 243, 420), (20.0, 252, 700)):
                pts = [[random.uniform(0, W), random.uniform(0, H * 0.8)]
                       for _ in range(max(6, W * H // density))]
                self.stars.append((speed, col, pts))
            R = max(5, H // 8)
            self.planet = [W * 0.86, H * 0.42, make_planet(R), R]
            if self.player and old_h:
                p = self.player
                p.x = min(p.x, W - 10)
                p.y = min(p.y, H - 6)
        self.prev = [None] * self.prow
        self.prev_hud = None

    def new_game(self):
        self.clear_world()
        self.player = Player(self.H / 2 - 2)
        self.score = 0
        self.chain = 0
        self.chain_t = 0.0
        self.mult = 1
        self.next_life = 50000
        self.start_wave(1)
        self.state = 'play'

    def start_wave(self, n):
        self.wave = n
        self.wave_t = 0.0
        self.intermission = None
        if n % 4 == 0:
            self.wave_events = [(2.6, 'boss')]
            self.banner = {'text': 'WARNING', 't': 0.0, 'dur': 2.8, 'ramp': [196, 160, 231],
                           'hazard': True}
        else:
            self.wave_events = build_wave(n)
            self.banner = {'text': 'WAVE %d' % n, 't': 0.0, 'dur': 2.0, 'ramp': SUNSET,
                           'hazard': False}

    # ---------------------------------------------------------- main loop
    def run(self):
        last = time.monotonic()
        frame = 1.0 / FPS
        while self.running:
            now = time.monotonic()
            dt = min(0.05, now - last)
            last = now
            self.now = now
            if self.resized:
                self.layout()
            self.inp.feed(self.term.read_events(), now)
            if self.inp.hit('ctrl-c'):
                break
            if not self.too_small:
                self.update(dt)
                self.draw()
                self.render()
            self.inp.end_frame()
            spare = frame - (time.monotonic() - now)
            if spare > 0:
                time.sleep(spare)

    # ---------------------------------------------------------- update
    def update(self, dt):
        self.t += dt
        st = self.state
        inp = self.inp
        if st == 'title':
            self.update_scenery(dt)
            self.update_fx(dt)
            if inp.hit('enter', 'space'):
                self.new_game()
            elif inp.hit('q', 'esc'):
                self.running = False
        elif st == 'paused':
            if inp.hit('p', 'esc', 'enter', 'space'):
                self.state = 'play'
            elif inp.hit('q'):
                self.state = 'title'
                self.clear_world()
        elif st == 'entry':
            self.update_scenery(dt)
            self.update_entry()
        elif st == 'play':
            self.update_play(dt)

    def update_scenery(self, dt):
        self.warp += (self.warp_target - self.warp) * min(1, dt * 3)
        w = self.warp
        W, H = self.W, self.H
        for speed, _, pts in self.stars:
            for s in pts:
                s[0] -= speed * w * dt
                if s[0] < -16:
                    s[0] += W + 32
                    s[1] = random.uniform(0, H * 0.8)
        self.far_x += 3.0 * w * dt
        self.near_x += 9.0 * w * dt
        pl = self.planet
        pl[0] -= 0.8 * dt * (1 + (w - 1) * 0.3)
        if pl[0] < -pl[3] * 3:
            pl[0] = W + pl[3] * 3
            pl[1] = random.uniform(pl[3] + 1, H * 0.45)

    def update_fx(self, dt):
        alive = []
        for p in self.particles:
            p[4] -= dt
            if p[4] > 0:
                p[0] += p[2] * dt
                p[1] += p[3] * dt
                d = 1 - p[7] * dt
                p[2] *= d
                p[3] *= d
                alive.append(p)
        self.particles = alive[-900:]
        rings = []
        for r in self.rings:
            r[4] -= dt
            if r[4] > 0:
                r[2] += r[3] * dt
                rings.append(r)
        self.rings = rings
        texts = []
        for tx in self.texts:
            tx[3] -= dt
            if tx[3] > 0:
                tx[1] -= 7 * dt
                texts.append(tx)
        self.texts = texts
        self.shake *= math.exp(-7 * dt)
        if self.shake < 0.3:
            self.shake = 0.0
        self.flash = max(0.0, self.flash - dt)

    def update_play(self, dt):
        inp = self.inp
        if inp.hit('p', 'esc', 'q'):
            self.state = 'paused'
            return
        p = self.player
        self.warp_target = 1.0
        if self.intermission is not None and self.intermission > 0.7:
            self.warp_target = 7.0
        elif p.alive and p.dash_t > 0:
            self.warp_target = 2.5
        self.update_scenery(dt)
        self.update_player(dt)
        self.update_waves(dt)
        self.update_enemies(dt)
        self.update_shots(dt)
        self.update_pickups(dt)
        self.update_bomb(dt)
        self.update_boss_death(dt)
        self.collide()
        self.update_fx(dt)
        if self.banner:
            self.banner['t'] += dt
            if self.banner['t'] >= self.banner['dur']:
                self.banner = None
        if self.chain_t > 0:
            self.chain_t -= dt
            if self.chain_t <= 0:
                self.chain = 0
        self.mult = min(8, 1 + self.chain // 6)
        if self.over:
            self.over_t += dt
            if self.over_t > 2.0 and inp.hit('enter', 'space'):
                self.finish_game()

    def finish_game(self):
        qualifies = self.score > 0 and (len(self.scores) < 5 or
                                        self.score > self.scores[-1].get('score', 0))
        if qualifies:
            self.state = 'entry'
            self.entry = {'name': list('AAA'), 'i': 0}
            try:
                last = os.environ.get('USER', 'AAA').upper()[:3]
                if len(last) == 3 and all(ch in FONT for ch in last):
                    self.entry['name'] = list(last)
            except Exception:
                pass
        else:
            self.state = 'title'
            self.clear_world()

    def update_entry(self):
        e = self.entry
        alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        for k in self.inp.typed:
            if k == 'enter':
                self.scores.append({'name': ''.join(e['name']), 'score': self.score,
                                    'wave': self.wave})
                self.scores = sorted(self.scores, key=lambda d: -d.get('score', 0))[:5]
                save_scores(self.scores)
                self.state = 'title'
                self.clear_world()
                return
            if k in ('up', 'down'):
                cur = alphabet.find(e['name'][e['i']])
                cur = (cur + (1 if k == 'up' else -1)) % len(alphabet)
                e['name'][e['i']] = alphabet[cur]
            elif k in ('left', 'backspace'):
                e['i'] = max(0, e['i'] - 1)
            elif k in ('right', 'space', 'tab'):
                e['i'] = min(2, e['i'] + 1)
            elif len(k) == 1 and k.upper() in alphabet:
                e['name'][e['i']] = k.upper()
                e['i'] = min(2, e['i'] + 1)

    # ---------------------------------------------------------- player
    def update_player(self, dt):
        p = self.player
        now = self.now
        inp = self.inp
        W, H = self.W, self.H
        for g in p.ghosts:
            g[2] -= dt
        p.ghosts = [g for g in p.ghosts if g[2] > 0]
        if not p.alive:
            if p.lives > 0:
                p.respawn -= dt
                if p.respawn <= 0:
                    p.alive = True
                    p.x, p.y = -12.0, H / 2 - 2
                    p.vx = p.vy = 0.0
                    p.enter_t = 0.9
                    p.inv = 2.6
            return
        p.inv = max(0.0, p.inv - dt)
        p.dash_cd = max(0.0, p.dash_cd - dt)
        if p.enter_t > 0:
            p.enter_t -= dt
            p.x += (10 - p.x) * min(1, dt * 5)
            p.bank = 0
            self.engine_trail(p, 2)
            return
        ax = inp.down('right', now) - inp.down('left', now)
        ay = inp.down('down', now) - inp.down('up', now)
        if inp.hit('space', 'z') and p.dash_cd <= 0:
            dx, dy = (ax, ay) if (ax or ay) else (1, 0)
            n = math.hypot(dx, dy)
            p.dash_v = (dx / n * 190, dy / n * 150)
            p.dash_t = 0.16
            p.dash_cd = 0.85
            p.inv = max(p.inv, 0.28)
            self.rings.append([p.x + 4, p.y + 2, 1.0, 50.0, 0.25, 0.25, CYAN])
        if inp.hit('x', 'b') and p.bombs > 0 and self.bomb is None:
            p.bombs -= 1
            self.bomb = [p.x + 4, p.y + 2, 0.0, set()]
            self.flash = 0.16
            self.shake = 6
        if p.dash_t > 0:
            p.dash_t -= dt
            p.vx, p.vy = p.dash_v
            p.ghosts.append([p.x, p.y, 0.32, p.bank])
        else:
            sp = 58.0 * (0.78 if ax and ay else 1.0)
            k = 1 - math.exp(-11 * dt)
            p.vx += (ax * sp - p.vx) * k
            p.vy += (ay * sp * 0.85 - p.vy) * k
        p.x = max(0.0, min(W - 9.0, p.x + p.vx * dt))
        p.y = max(1.0, min(H - 5.0, p.y + p.vy * dt))
        p.bank = -1 if p.vy < -14 else 1 if p.vy > 14 else 0
        self.engine_trail(p, 1 + (p.vx > 10) + (p.dash_t > 0) * 2)
        # guns
        p.fire_cd -= dt
        if p.fire_cd <= 0:
            p.fire_cd = max(0.0, p.fire_cd + 0.12)
            nx, ny = p.x + 9, p.y + 2.5
            spread = {1: [(0, 0)], 2: [(0, -1), (0, 1)],
                      3: [(0, 0), (-0.12, 0), (0.12, 0)],
                      4: [(0, -1), (0, 1), (-0.14, 0), (0.14, 0)],
                      5: [(0, -1), (0, 1), (-0.12, 0), (0.12, 0), (-0.27, 0), (0.27, 0)]}
            for ang, off in spread[p.power]:
                self.pbullets.append([nx, ny + off, math.cos(ang) * 175, math.sin(ang) * 175])
            self.particles.append([nx, ny, 20, 0, 0.06, 0.06, CYAN, 0])
        if p.power >= 4:
            p.missile_cd -= dt
            if p.missile_cd <= 0:
                p.missile_cd = 0.95 if p.power == 4 else 0.6
                self.missiles.append([p.x + 4, p.y, 25.0, -50.0, 2.6])
                self.missiles.append([p.x + 4, p.y + 4, 25.0, 50.0, 2.6])

    def engine_trail(self, p, n):
        dashing = p.dash_t > 0
        for _ in range(n):
            life = random.uniform(0.1, 0.28 if dashing else 0.2)
            self.particles.append([p.x - 0.5, p.y + 2 + random.uniform(-0.6, 0.6),
                                   -45 - random.uniform(0, 40) + min(0, p.vx) * 0.4,
                                   random.uniform(-6, 6) - p.vy * 0.2,
                                   life, life, CYAN if dashing else FIRE, 1.0])

    def hurt_player(self):
        p = self.player
        if not p.alive or p.inv > 0 or p.dash_t > 0 or p.enter_t > 0:
            return
        cx, cy = p.x + 4, p.y + 2
        if p.shield:
            p.shield = False
            p.inv = 1.3
            self.rings.append([cx, cy, 3.0, 40.0, 0.4, 0.4, CYAN])
            self.burst(cx, cy, 18, CYAN, 50)
            self.shake = max(self.shake, 3)
            return
        p.alive = False
        p.lives -= 1
        p.power = max(1, p.power - 1)
        p.shield = False
        p.dash_t = 0
        self.chain = 0
        self.explode(cx, cy, 2.2, CYAN)
        self.explode(cx, cy, 1.4, FIRE)
        self.debris(SPR['player'], p.x, p.y, cx, cy, 1.0)
        self.shake = 8
        self.flash = 0.08
        for b in self.ebullets:
            self.particles.append([b[0], b[1], 0, 0, 0.3, 0.3, PINK, 0])
        self.ebullets = []
        if p.lives > 0:
            p.respawn = 1.7
        else:
            self.over = True
            self.over_t = 0.0

    # ---------------------------------------------------------- waves + enemies
    def update_waves(self, dt):
        if self.over:
            return
        self.wave_t += dt
        while self.wave_events and self.wave_events[0][0] <= self.wave_t:
            self.spawn(self.wave_events.pop(0)[1])
        busy = self.wave_events or self.enemies or self.boss or self.boss_dying
        if not busy and self.intermission is None:
            self.intermission = 3.0
            self.banner = {'text': 'WAVE CLEAR', 't': 0.0, 'dur': 1.8, 'ramp': CYAN[3:],
                           'hazard': False}
        if self.intermission is not None:
            self.intermission -= dt
            if self.intermission <= 0:
                self.start_wave(self.wave + 1)

    def ry(self, top, bottom):
        a, b = top, self.H - bottom
        return random.uniform(a, b) if b > a else (a + b) / 2

    def spawn(self, kind):
        n, W, H = self.wave, self.W, self.H
        group = {'killed': 0, 'total': 0}

        def add(e):
            e.group = group
            group['total'] += 1
            self.enemies.append(e)
            return e

        if kind == 'sine':
            amp = random.uniform(4, max(5, H * 0.2))
            y0 = self.ry(3 + amp, 9 + amp)
            spd = 22 + n * 1.2
            for i in range(5 + min(3, n // 3)):
                e = add(Enemy('drone', W + 3 + i * 8, y0, 1, 100, SPR['drone']))
                e.m.update(base=y0, amp=amp, ph=i * 0.55, spd=spd)
        elif kind == 'darts':
            cnt = 3 + min(4, n // 2)
            cy = self.ry(10, 12)
            for i in range(cnt):
                off = i - (cnt - 1) / 2
                e = add(Enemy('dart', W + 3 + abs(off) * 6,
                              max(1, min(H - 5, cy + off * 5)), 1, 150, SPR['dart']))
                e.m.update(spd=52 + n * 2, home=0.9)
        elif kind == 'pods':
            cnt = 1 + (n >= 5) + (n >= 9)
            for i in range(cnt):
                y = (i + 1) * H / (cnt + 1) - 3
                e = add(Enemy('pod', W + 2 + i * 6, y, 6 + n, 500, SPR['pod']))
                e.m.update(stop=W * 0.72 + random.uniform(-6, 6), base=y,
                           fire=1.2 + i * 0.5, leave=9.0)
        elif kind == 'spinners':
            cnt = 2 + (n >= 7)
            for i in range(cnt):
                y = (i + 1) * H / (cnt + 1) - 2
                e = add(Enemy('spinner', W + 2 + i * 10, y, 3 + n // 3, 300, SPR['spin0']))
                e.m.update(base=y, amp=random.uniform(4, H * 0.18), ph=random.uniform(0, TAU),
                           fire=1.5 + i * 0.7)
        elif kind == 'mines':
            for i in range(4 + min(4, n // 3)):
                y = self.ry(3, 9)
                e = add(Enemy('mine', W + 3 + i * random.uniform(6, 12), y, 2, 120, SPR['mine0']))
                e.m.update(base=y, vx=-random.uniform(9, 15), ph=random.uniform(0, TAU), arm=None)
        elif kind == 'loopers':
            r = min(11.0, H * 0.22)
            cy = self.ry(r + 3, r + 9)
            for i in range(7 + min(5, n // 2)):
                e = add(Enemy('gnat', W + 20, cy, 1, 80, SPR['gnat']))
                e.m.update(delay=i * 0.16, cy=cy, r=r, v=24 + n, w=2.6)
        elif kind == 'boss':
            hp = 220 + 110 * (n // 4 - 1)
            spr = SPR['boss']
            e = Enemy('boss', W + 2, H / 2 - 7, hp, 15000 * (n // 4), spr)
            amp = max(0.0, H / 2 - 9) * 0.85
            e.m.update(state='enter', home=W - spr[0] - 4, base=H / 2 - 7, amp=amp, ph=0.0,
                       atk=None, atk_t=1.4, ci=0, tt=0.0, n=0, dur=0.0, ang=0.0, laser=None)
            self.enemies.append(e)
            self.boss = e

    def bullet_speed(self, s):
        return s * min(1.5, 1 + self.wave * 0.03)

    def target(self):
        p = self.player
        if p.alive:
            return p.x + 4, p.y + 2
        return -20.0, self.H / 2

    def fire_aimed(self, x, y, speed, count=1, spread=0.0, style=0):
        tx, ty = self.target()
        base = math.atan2(ty - y, tx - x)
        speed = self.bullet_speed(speed)
        for i in range(count):
            a = base + (i - (count - 1) / 2) * spread
            self.ebullets.append([x, y, math.cos(a) * speed, math.sin(a) * speed, style])

    def fire_ring(self, x, y, speed, count, offset=0.0, style=0):
        speed = self.bullet_speed(speed)
        for i in range(count):
            a = offset + TAU * i / count
            self.ebullets.append([x, y, math.cos(a) * speed, math.sin(a) * speed, style])

    def update_enemies(self, dt):
        W, H = self.W, self.H
        tx, ty = self.target()
        n = self.wave
        for e in self.enemies:
            if e.dead:
                continue
            e.t += dt
            e.flash = max(0.0, e.flash - dt)
            m = e.m
            k = e.kind
            onscreen = 2 < e.x < W - e.w - 1
            if k == 'drone':
                e.x -= m['spd'] * dt
                e.y = m['base'] + m['amp'] * math.sin(e.t * 2.2 + m['ph'])
                if n >= 2 and onscreen and random.random() < (0.05 + n * 0.015) * dt:
                    self.fire_aimed(e.x, e.y + 2, 34)
            elif k == 'dart':
                e.x -= m['spd'] * dt
                if e.x < W - 4 and m['home'] > 0:
                    m['home'] -= dt
                    e.vy += max(-120, min(120, (ty - e.y - 1) * 6)) * dt
                    e.vy = max(-38, min(38, e.vy))
                else:
                    e.vy *= 1 - 2 * dt
                e.y = max(0, min(H - 3, e.y + e.vy * dt))
                if random.random() < 0.7:
                    self.particles.append([e.x + 6, e.y + 1, 15, 0, 0.18, 0.18, GOLD, 0])
            elif k == 'pod':
                if e.t < m['leave']:
                    e.x += (m['stop'] - e.x) * min(1, dt * 1.4)
                else:
                    e.x -= (e.t - m['leave']) * 30 * dt
                e.y = m['base'] + 5 * math.sin(e.t * 1.1)
                m['fire'] -= dt
                if m['fire'] <= 0 and onscreen:
                    m['fire'] = max(0.9, 1.9 - n * 0.06)
                    self.fire_aimed(e.x, e.y + 2.5, 36, 3, 0.28)
            elif k == 'spinner':
                e.x -= 13 * dt
                e.y = m['base'] + m['amp'] * math.sin(e.t * 1.3 + m['ph'])
                e.spr = SPR['spin0'] if int(e.t * 10) % 2 else SPR['spin1']
                m['fire'] -= dt
                if m['fire'] <= 0 and onscreen:
                    m['fire'] = max(1.4, 2.6 - n * 0.05)
                    self.fire_ring(e.x + 2, e.y + 2, 28, min(12, 6 + n // 2), e.t, style=1)
            elif k == 'mine':
                e.x += m['vx'] * dt
                e.y = m['base'] + 2 * math.sin(e.t * 2 + m['ph'])
                close = math.hypot(tx - e.x - 2, ty - e.y - 2) < 11
                if m['arm'] is None and close and onscreen:
                    m['arm'] = 0.8
                if m['arm'] is not None:
                    m['arm'] -= dt
                    e.spr = SPR['mine1'] if int(e.t * 16) % 2 else SPR['mine0']
                    if m['arm'] <= 0:
                        e.dead = True
                        self.explode(e.x + 2, e.y + 2, 1.2, FIRE)
                        self.fire_ring(e.x + 2, e.y + 2, 26, 8, random.uniform(0, 1), style=1)
                else:
                    e.spr = SPR['mine1'] if int(e.t * 3) % 2 else SPR['mine0']
            elif k == 'gnat':
                tt = e.t - m['delay']
                if tt < 0:
                    e.x = W + 20
                    continue
                e.x = W + 4 - m['v'] * tt + m['r'] * math.sin(m['w'] * tt)
                e.y = m['cy'] - m['r'] * math.cos(m['w'] * tt)
                if n >= 4 and onscreen and random.random() < 0.02 * dt * n:
                    self.fire_aimed(e.x, e.y + 1, 32)
            elif k == 'boss':
                self.update_boss(e, dt)
            if k != 'boss' and (e.x < -e.w - 6 or e.y > H + 20):
                e.dead = True
        self.enemies = [e for e in self.enemies if not e.dead]

    def update_boss(self, e, dt):
        m = e.m
        angry = e.hp < e.maxhp * 0.5
        e.spr = SPR['boss_angry'] if angry else SPR['boss']
        if m['state'] == 'enter':
            e.x += (m['home'] - e.x) * min(1, dt * 1.3)
            m['ph'] += dt * 0.8
            e.y = m['base'] + math.sin(m['ph']) * m['amp'] * 0.3
            if abs(e.x - m['home']) < 0.6:
                m['state'] = 'fight'
            return
        eye_x, eye_y = e.x + 3, e.y + 7
        tx, ty = self.target()
        if m['atk'] != 'laser':
            m['ph'] += dt * (1.25 if angry else 0.85)
            goal = m['base'] + math.sin(m['ph']) * m['amp']
            e.y += (goal - e.y) * min(1, dt * 2.5)
        if m['atk'] is None:
            m['atk_t'] -= dt
            if m['atk_t'] <= 0:
                cycle = (['fan', 'rings', 'spiral', 'laser', 'minions', 'rings'] if angry
                         else ['fan', 'spiral', 'laser', 'minions'])
                m['atk'] = cycle[m['ci'] % len(cycle)]
                m['ci'] += 1
                m['tt'] = 0.0
                m['n'] = 0
                m['dur'] = 0.0
            return
        a = m['atk']
        m['dur'] += dt
        m['tt'] -= dt
        done = False
        if a == 'fan':
            if m['tt'] <= 0:
                m['tt'] = 0.32 if angry else 0.45
                self.fire_aimed(eye_x, eye_y, 40, 7 if angry else 5, 0.2, style=2)
                m['n'] += 1
            done = m['n'] >= 4
        elif a == 'spiral':
            if m['tt'] <= 0:
                m['tt'] = 0.05 if angry else 0.07
                arms = 3 if angry else 2
                for i in range(arms):
                    a2 = m['ang'] + TAU * i / arms
                    s = self.bullet_speed(32)
                    self.ebullets.append([eye_x, eye_y, math.cos(a2) * s, math.sin(a2) * s, 1])
                m['ang'] += 0.33
            done = m['dur'] > 2.8
        elif a == 'rings':
            if m['tt'] <= 0:
                m['tt'] = 0.55
                self.fire_ring(eye_x, eye_y, 30, 16, random.uniform(0, TAU), style=2)
                m['n'] += 1
            done = m['n'] >= 3
        elif a == 'minions':
            for i in range(4 if angry else 3):
                d = Enemy('dart', e.x, e.y + 3 + i * 3, 1, 150, SPR['dart'])
                d.m.update(spd=48, home=1.2)
                self.enemies.append(d)
            done = True
        elif a == 'laser':
            if m['dur'] < 0.6:
                e.y += max(-40 * dt, min(40 * dt, ty - eye_y))
                e.y = max(1, min(self.H - e.h - 1, e.y))
            if m['dur'] < 1.05:
                m['laser'] = ('tele', e.y + 7)
            elif m['dur'] < 1.85:
                m['laser'] = ('fire', e.y + 7)
                self.shake = max(self.shake, 1.5)
                if random.random() < 0.8:
                    self.particles.append([eye_x, eye_y + random.uniform(-2, 2),
                                           -random.uniform(20, 80), random.uniform(-25, 25),
                                           0.3, 0.3, PINK, 1])
            else:
                m['laser'] = None
                done = True
        if done:
            m['atk'] = None
            m['laser'] = None
            m['atk_t'] = 0.7 if angry else 1.1

    def update_boss_death(self, dt):
        bd = self.boss_dying
        if not bd:
            return
        bd['t'] -= dt
        bd['boom'] -= dt
        self.shake = max(self.shake, 2.5)
        if bd['boom'] <= 0:
            bd['boom'] = 0.07
            x = bd['x'] + random.uniform(0, bd['spr'][0])
            y = bd['y'] + random.uniform(0, bd['spr'][1])
            self.explode(x, y, random.uniform(0.7, 1.4), random.choice((FIRE, PINK, GOLD)))
        if bd['t'] <= 0:
            cx = bd['x'] + bd['spr'][0] / 2
            cy = bd['y'] + bd['spr'][1] / 2
            self.explode(cx, cy, 4.0, FIRE)
            self.explode(cx, cy, 3.0, PINK)
            self.debris(bd['spr'], bd['x'], bd['y'], cx, cy, 1.0)
            self.rings.append([cx, cy, 2.0, 90.0, 0.8, 0.8, PINK])
            self.rings.append([cx, cy, 1.0, 60.0, 0.9, 0.9, GOLD])
            self.shake = 10
            self.flash = 0.3
            self.add_score(bd['score'], cx, cy)
            self.drop(cx, cy, 'P')
            self.drop(cx + 6, cy - 6, 'B')
            self.drop(cx - 6, cy + 6, 'S')
            self.boss_dying = None

    # ---------------------------------------------------------- shots, pickups, bomb
    def update_shots(self, dt):
        W, H = self.W, self.H
        keep = []
        for b in self.pbullets:
            b[0] += b[2] * dt
            b[1] += b[3] * dt
            if b[0] < W + 3 and -2 < b[1] < H + 2:
                keep.append(b)
        self.pbullets = keep
        keep = []
        targets = [e for e in self.enemies if e.x < W - 2]
        for m in self.missiles:
            m[4] -= dt
            if m[4] <= 0:
                continue
            best, bd = None, 1e9
            for e in targets:
                d = (e.x + e.w / 2 - m[0]) ** 2 + (e.y + e.h / 2 - m[1]) ** 2
                if d < bd:
                    best, bd = e, d
            ang = math.atan2(m[3], m[2])
            spd = min(150.0, math.hypot(m[2], m[3]) + 130 * dt)
            if best:
                want = math.atan2(best.y + best.h / 2 - m[1], best.x + best.w / 2 - m[0])
                diff = (want - ang + math.pi) % TAU - math.pi
                ang += max(-6 * dt, min(6 * dt, diff))
            else:
                ang += max(-3 * dt, min(3 * dt, -ang))
            m[2], m[3] = math.cos(ang) * spd, math.sin(ang) * spd
            m[0] += m[2] * dt
            m[1] += m[3] * dt
            self.particles.append([m[0], m[1], random.uniform(-5, 5), random.uniform(-5, 5),
                                   0.35, 0.35, SMOKE, 2])
            if -4 < m[0] < W + 4 and -4 < m[1] < H + 4:
                keep.append(m)
        self.missiles = keep
        keep = []
        for b in self.ebullets:
            b[0] += b[2] * dt
            b[1] += b[3] * dt
            if -3 < b[0] < W + 3 and -3 < b[1] < H + 3:
                keep.append(b)
        self.ebullets = keep[-300:]

    def drop(self, x, y, kind=None):
        p = self.player
        if kind is None:
            opts = ['P', 'P', 'S', 'B'] if p.power < 5 else ['S', 'B', 'P']
            if p.bombs >= 5:
                opts = [o for o in opts if o != 'B']
            kind = random.choice(opts)
        self.pickups.append([x - 2, y - 3, kind, 0.0, y - 3])

    def update_pickups(self, dt):
        p = self.player
        keep = []
        for pk in self.pickups:
            pk[3] += dt
            pk[0] -= 12 * dt
            pk[1] = pk[4] + 2.5 * math.sin(pk[3] * 3)
            if p.alive:
                dx, dy = p.x + 4 - (pk[0] + 2), p.y + 2 - (pk[1] + 3)
                d = math.hypot(dx, dy)
                if d < 16:
                    pull = 70 * dt / max(d, 0.01)
                    pk[0] += dx * pull
                    pk[4] += dy * pull
                if d < 4.5:
                    self.collect(pk[2], pk[0] + 2, pk[1] + 3)
                    continue
            if pk[0] > -8:
                keep.append(pk)
        self.pickups = keep

    def collect(self, kind, x, y):
        p = self.player
        if kind == 'P':
            if p.power < 5:
                p.power += 1
                label = 'POWER UP' if p.power < 4 else 'MISSILES!' if p.power == 4 else 'MAX POWER'
            else:
                label = '+2000'
                self.score += 2000
            ramp = FIRE
        elif kind == 'S':
            p.shield = True
            label, ramp = 'SHIELD', CYAN
        else:
            p.bombs = min(5, p.bombs + 1)
            label, ramp = 'BOMB +1', PINK
        self.texts.append([x, y - 4, label, 1.2, ramp[5]])
        self.rings.append([x, y, 1.0, 35.0, 0.35, 0.35, ramp])
        self.burst(x, y, 12, ramp, 40)

    def update_bomb(self, dt):
        b = self.bomb
        if not b:
            return
        b[2] += 140 * dt
        r = b[2]
        keep = []
        for eb in self.ebullets:
            if (eb[0] - b[0]) ** 2 + (eb[1] - b[1]) ** 2 < r * r:
                self.particles.append([eb[0], eb[1], 0, -10, 0.4, 0.4, PINK, 0])
            else:
                keep.append(eb)
        self.ebullets = keep
        for e in self.enemies:
            if id(e) in b[3] or e.dead or e.x > self.W:
                continue
            if math.hypot(e.x + e.w / 2 - b[0], e.y + e.h / 2 - b[1]) < r + e.w / 2:
                b[3].add(id(e))
                self.damage(e, 30 if e.kind == 'boss' else 12)
        if r > math.hypot(self.W, self.H) * 1.05:
            self.bomb = None

    # ---------------------------------------------------------- collisions & scoring
    def collide(self):
        W = self.W
        dt = 1.0 / FPS
        live = [e for e in self.enemies if not e.dead and e.x < W - 1]
        keep = []
        for b in self.pbullets:
            px = b[0] - b[2] * dt
            hit = None
            for e in live:
                if (b[0] >= e.x - 1 and px <= e.x + e.w and e.y - 0.5 <= b[1] <= e.y + e.h - 0.5
                        and not e.dead):
                    hit = e
                    break
            if hit:
                self.damage(hit, 1)
                self.particles.append([b[0], b[1], -20, random.uniform(-20, 20), 0.12, 0.12,
                                       CYAN, 0])
            else:
                keep.append(b)
        self.pbullets = keep
        keep = []
        for m in self.missiles:
            hit = None
            for e in live:
                if e.x - 1 <= m[0] <= e.x + e.w + 1 and e.y - 1 <= m[1] <= e.y + e.h and not e.dead:
                    hit = e
                    break
            if hit:
                self.damage(hit, 3)
                self.explode(m[0], m[1], 0.5, FIRE)
            else:
                keep.append(m)
        self.missiles = keep
        p = self.player
        if not p.alive:
            return
        cx, cy = p.x + 4.5, p.y + 2.5
        for b in self.ebullets:
            if abs(b[0] - cx) < 1.9 and abs(b[1] - cy) < 1.4:
                self.hurt_player()
                return
        for e in live:
            if e.dead:
                continue
            if e.x + 0.5 <= cx <= e.x + e.w - 0.5 and e.y + 0.5 <= cy <= e.y + e.h - 0.5:
                if e.kind != 'boss':
                    self.damage(e, 99)
                self.hurt_player()
                return
        if self.boss and self.boss.m.get('laser') and self.boss.m['laser'][0] == 'fire':
            ly = self.boss.m['laser'][1]
            if abs(cy - ly) < 2.3 and cx < self.boss.x + 2:
                self.hurt_player()

    def damage(self, e, dmg):
        if e.dead:
            return
        e.hp -= dmg
        e.flash = 0.07
        if e.hp <= 0:
            self.kill(e)

    def kill(self, e):
        e.dead = True
        if e.kind == 'boss':
            self.boss = None
            self.boss_dying = {'x': e.x, 'y': e.y, 't': 2.4, 'boom': 0.0, 'spr': e.spr,
                               'score': e.score}
            self.ebullets = []
            return
        cx, cy = e.x + e.w / 2, e.y + e.h / 2
        ramp, power = {'drone': (PINK, 0.9), 'dart': (GOLD, 0.8), 'pod': (LIME, 1.7),
                       'spinner': (FIRE, 1.2), 'mine': (FIRE, 1.1),
                       'gnat': (LIME, 0.6)}.get(e.kind, (FIRE, 1.0))
        self.explode(cx, cy, power, ramp)
        self.debris(e.spr, e.x, e.y, cx, cy)
        self.chain += 1
        self.chain_t = 2.0
        self.mult = min(8, 1 + self.chain // 6)
        self.add_score(e.score, cx, cy)
        if e.kind == 'mine':
            self.fire_ring(cx, cy, 24, 8, random.uniform(0, 1), style=1)
        g = e.group
        if g is not None:
            g['killed'] += 1
            if g['killed'] == g['total'] and g['total'] >= 4:
                self.drop(cx, cy)
                self.texts.append([cx, cy - 8, 'SQUADRON', 1.2, 226])
                self.add_score(1000, cx, cy - 2, show=False)
                return
        if random.random() < (0.35 if e.kind == 'pod' else 0.04):
            self.drop(cx, cy)

    def add_score(self, base, x, y, show=True):
        pts = base * self.mult
        self.score += pts
        if show:
            self.texts.append([x, y - 3, '+%d' % pts, 0.8, 229 if self.mult > 1 else 250])
        p = self.player
        if self.score >= self.next_life:
            self.next_life += 50000
            if p:
                p.lives = min(9, p.lives + 1)
                self.texts.append([self.W / 2, self.H / 2, '1UP', 1.5, 51])

    # ---------------------------------------------------------- effects
    def explode(self, x, y, power=1.0, ramp=FIRE):
        for _ in range(int(14 * power)):
            a = random.uniform(0, TAU)
            s = random.uniform(6, 42) * math.sqrt(power)
            life = random.uniform(0.25, 0.7) * (0.7 + 0.3 * power)
            self.particles.append([x, y, math.cos(a) * s, math.sin(a) * s, life, life, ramp, 2.5])
        for _ in range(int(4 * power)):
            life = random.uniform(0.5, 1.0)
            self.particles.append([x + random.uniform(-2, 2), y + random.uniform(-2, 2),
                                   random.uniform(-8, 8), random.uniform(-8, 8),
                                   life, life, SMOKE, 1.5])
        self.rings.append([x, y, 1.0, 22.0 * math.sqrt(power), 0.28, 0.28, ramp])
        self.shake = max(self.shake, 1.2 * power)

    def burst(self, x, y, n, ramp, speed):
        for _ in range(n):
            a = random.uniform(0, TAU)
            s = random.uniform(0.3, 1.0) * speed
            life = random.uniform(0.2, 0.5)
            self.particles.append([x, y, math.cos(a) * s, math.sin(a) * s, life, life, ramp, 2])

    def debris(self, spr, sx, sy, cx, cy, frac=0.65):
        for dx, dy, c in spr[2]:
            if random.random() < frac:
                px, py = sx + dx, sy + dy
                a = math.atan2(py - cy, px - cx) + random.uniform(-0.5, 0.5)
                s = random.uniform(12, 55)
                life = random.uniform(0.4, 1.0)
                self.particles.append([px, py, math.cos(a) * s, math.sin(a) * s,
                                       life, life, debris_ramp(c), 1.6])

    # ---------------------------------------------------------- drawing primitives
    def pset(self, x, y, c):
        x = int((x + self.ox) // 1)
        y = int((y + self.oy) // 1)
        if 0 <= x < self.W and 0 <= y < self.H:
            self.fb[y * self.W + x] = c

    def blit(self, spr, x, y, color=None):
        w, h, pts = spr
        W, H, fb = self.W, self.H, self.fb
        bx = int((x + self.ox) // 1)
        by = int((y + self.oy) // 1)
        if bx >= W or by >= H or bx + w <= 0 or by + h <= 0:
            return
        if bx >= 0 and by >= 0 and bx + w <= W and by + h <= H:
            base = by * W + bx
            if color is None:
                for dx, dy, c in pts:
                    fb[base + dy * W + dx] = c
            else:
                for dx, dy, c in pts:
                    fb[base + dy * W + dx] = color
            return
        for dx, dy, c in pts:
            px, py = bx + dx, by + dy
            if 0 <= px < W and 0 <= py < H:
                fb[py * W + px] = c if color is None else color

    def circle(self, cx, cy, r, c):
        steps = max(10, int(r * 7))
        for k in range(steps):
            a = TAU * k / steps
            self.pset(cx + math.cos(a) * r, cy + math.sin(a) * r, c)

    def text(self, s, x, y, color, scale=1, shadow=None, wave=0.0):
        """Pixel-font text. color may be an int or f(char_index, pixel_row)."""
        passes = ([(1, 1, shadow)] if shadow is not None else []) + [(0, 0, None)]
        for ox, oy, sc in passes:
            cx = x
            for i, ch in enumerate(s.upper()):
                pts = FONT.get(ch)
                if pts:
                    bob = round(math.sin(self.t * 4 + i * 0.7) * wave) if wave else 0
                    for gx, gy in pts:
                        for sy in range(scale):
                            py = gy * scale + sy
                            c = sc if sc is not None else (color(i, py) if callable(color)
                                                           else color)
                            for sx in range(scale):
                                self.pset(cx + gx * scale + sx + ox, y + py + bob + oy, c)
                cx += 4 * scale

    def put(self, row, col, s, fg):
        if not 0 <= row < self.prow:
            return
        r = self.overlay.setdefault(row, {})
        for i, ch in enumerate(s):
            if 0 <= col + i < self.W:
                r[col + i] = (ch, fg)

    def put_center(self, row, s, fg):
        self.put(row, (self.W - len(s)) // 2, s, fg)

    # ---------------------------------------------------------- scene drawing
    def draw(self):
        self.overlay = {}
        self.ox = self.oy = 0
        if self.shake > 0:
            s = int(round(self.shake))
            self.ox = random.randint(-s, s)
            self.oy = random.randint(-s, s) // 2
        if self.state == 'title':
            self.ox = self.oy = 0
            self.draw_title()
        elif self.state == 'entry':
            self.draw_background()
            self.fb[:] = self.fb.translate(DIM)
            self.draw_entry()
        else:
            self.draw_game()
            if self.state == 'paused':
                self.fb[:] = self.fb.translate(DIM)
                self.ox = self.oy = 0
                self.big_center('PAUSED', self.H // 2 - 8, lambda i, y: SUNSET[y % len(SUNSET)])
                self.put_center(self.prow // 2 + 2, 'P / Enter  resume      Q  quit to title', 250)

    def draw_background(self):
        fb, W, H = self.fb, self.W, self.H
        if self.flash > 0:
            fb[:] = bytes((231 if self.flash > 0.08 else 189,)) * (W * H)
            return
        fb[:] = self.base
        ox, oy = self.ox, self.oy
        # planet
        px, py, (back, body, front), R = self.planet
        bx, by = int(px), int(py)
        for layer in (back, body, front):
            for dx, dy, c in layer:
                x, y = bx + dx, by + dy
                if 0 <= x < W and 0 <= y < H:
                    fb[y * W + x] = c
        # stars, stretched into streaks when warping
        for speed, col, pts in self.stars:
            ln = int(min(14, speed * (self.warp - 1) * 0.1))
            streak = 239 if speed < 5 else 245 if speed < 10 else 250
            for s in pts:
                x, y = int(s[0] + ox), int(s[1] + oy)
                if 0 <= y < H:
                    row = y * W
                    if 0 <= x < W:
                        fb[row + x] = col
                    for k in range(1, ln + 1):
                        if 0 <= x + k < W:
                            fb[row + x + k] = streak
        # parallax mountains
        for tab, scroll, base_h, fill, ridge in (
                (FAR_RIDGE, self.far_x, H * 0.17, 17, 18),
                (NEAR_RIDGE, self.near_x, H * 0.09, 53, 127)):
            off = int(scroll)
            col = bytes((fill,)) * H
            for x in range(W):
                h = int(base_h + tab[(x + off) % RIDGE_LEN])
                if h <= 0:
                    continue
                top = H - h
                fb[top * W + x::W] = col[:h]
                fb[top * W + x] = ridge

    def draw_title(self):
        self.draw_background()
        W, H, t = self.W, self.H, self.t
        s = 2 if W >= 72 and H >= 50 else 1
        logo_y = max(2, int(H * 0.12))
        self.big_center('STARWAKE', logo_y, lambda i, y: SUNSET[min(len(SUNSET) - 1, y * 12 // (5 * s))]
                        if (int(t * 9) - i) % 22 != 0 else 231, s, shadow=53, wave=1.2 * s)
        # demo ship looping through the scene
        dx = W * 0.5 + math.sin(t * 0.7) * W * 0.36
        dy = H * 0.62 + math.sin(t * 1.4) * H * 0.12
        vy = math.cos(t * 1.4)
        demo = SPR['player_up'] if vy < -0.4 else SPR['player_down'] if vy > 0.4 else SPR['player']
        if random.random() < 0.9:
            life = random.uniform(0.1, 0.25)
            self.particles.append([dx - 0.5, dy + 2, -50 - random.uniform(0, 30),
                                   random.uniform(-6, 6), life, life, FIRE, 1.0])
        self.draw_particles()
        self.blit(demo, dx, dy)
        row = (logo_y + 5 * s) // 2 + 2
        rows = []
        rows.append(("a terminal shoot-'em-up", 245))
        rows.append(('', 0))
        rows.append(('>>  PRESS ENTER TO LAUNCH  <<' if int(t * 2.5) % 2 else '', 226))
        rows.append(('', 0))
        rows.append(('ARROWS/WASD fly   SPACE dash   X bomb   P pause   Q quit', 117))
        rows.append(('Your guns fire on their own. Dash straight through bullets!', 244))
        rows.append(('', 0))
        if self.scores:
            rows.append(('- HIGH SCORES -', 213))
            for i, sc in enumerate(self.scores):
                rows.append(('%d. %-3s  %07d  W%d' % (i + 1, sc.get('name', '???')[:3],
                                                       sc.get('score', 0), sc.get('wave', 0)),
                             231 if i == 0 else 250))
        for text, fg in rows:
            if row >= self.prow - 2:
                break
            if text:
                self.put_center(row, text, fg)
            row += 1
        mode = ('keys: kitty protocol (true key-hold)' if self.inp.kitty else
                'keys: classic  -  kitty/WezTerm/foot/Ghostty give smoother control')
        self.put_center(self.prow - 1, mode, 240)

    def big_center(self, text, y, color, scale=None, shadow=None, wave=0.0):
        if scale is None:
            scale = 2 if text_width(text, 2) <= self.W - 4 else 1
        self.text(text, (self.W - text_width(text, scale)) // 2, y, color, scale, shadow, wave)

    def draw_particles(self):
        fb, W, H = self.fb, self.W, self.H
        ox, oy = self.ox, self.oy
        for p in self.particles:
            x = int((p[0] + ox) // 1)
            y = int((p[1] + oy) // 1)
            if 0 <= x < W and 0 <= y < H:
                ramp = p[6]
                fb[y * W + x] = ramp[min(len(ramp) - 1, int((1 - p[4] / p[5]) * len(ramp)))]

    def draw_game(self):
        self.draw_background()
        t = self.t
        W, H = self.W, self.H
        p = self.player
        # pickups
        for pk in self.pickups:
            ramp = {'P': FIRE, 'S': CYAN, 'B': PINK}[pk[2]]
            c = ramp[3 + int(pk[3] * 8) % 4]
            x0, y0 = pk[0], pk[1]
            for i in range(5):
                self.pset(x0 + i, y0 - 1, c)
                self.pset(x0 + i, y0 + 5, c)
            for j in range(5):
                self.pset(x0 - 1, y0 + j, c)
                self.pset(x0 + 5, y0 + j, c)
            self.text(pk[2], x0 + 1, y0, 231)
        # player
        if p.alive:
            for g in p.ghosts:
                col = CYAN[min(len(CYAN) - 1, 5 + int((1 - g[2] / 0.32) * 7))]
                self.blit(self.player_sprite(g[3]), g[0], g[1], col)
            blink = p.inv > 0 and p.enter_t <= 0 and int(t * 14) % 2 == 0
            if not blink:
                self.blit(self.player_sprite(p.bank), p.x, p.y,
                          231 if p.dash_t > 0 and int(t * 30) % 2 else None)
            if p.shield:
                self.circle(p.x + 4.5, p.y + 2.5, 6 + math.sin(t * 8) * 0.5,
                            CYAN[4 + int(t * 10) % 3])
        # enemies
        for e in self.enemies:
            self.blit(e.spr, e.x, e.y, 231 if e.flash > 0 else None)
            if e.kind == 'boss':
                eye = FIRE[int(t * 12) % 6 + 4] if e.hp < e.maxhp * 0.5 else PINK[int(t * 6) % 5]
                for ex, ey in BOSS_EYE:
                    self.pset(e.x + ex, e.y + ey, 231 if e.flash > 0 else eye)
                if e.hp < e.maxhp * 0.5 and random.random() < 0.4:
                    life = random.uniform(0.4, 0.8)
                    self.particles.append([e.x + random.uniform(4, e.w), e.y + random.uniform(0, e.h),
                                           random.uniform(-4, 4), -random.uniform(5, 15),
                                           life, life, SMOKE, 1])
            elif e.kind == 'pod' and e.hp <= 3 and random.random() < 0.3:
                self.particles.append([e.x + 4, e.y + 1, 5, -8, 0.5, 0.5, SMOKE, 1])
        bd = self.boss_dying
        if bd and int(t * 20) % 3:
            self.blit(bd['spr'], bd['x'] + random.uniform(-1, 1), bd['y'], None)
        # player shots
        for b in self.pbullets:
            self.pset(b[0], b[1], 231)
            self.pset(b[0] - 1, b[1] - b[3] / 175, 51)
            self.pset(b[0] - 2, b[1] - 2 * b[3] / 175, 31)
        for m in self.missiles:
            self.pset(m[0], m[1], 231)
            self.pset(m[0] - m[2] / 150, m[1] - m[3] / 150, 208)
        self.draw_particles()
        for r in self.rings:
            ramp = r[6]
            self.circle(r[0], r[1], r[2], ramp[min(len(ramp) - 1, int((1 - r[4] / r[5]) * len(ramp)))])
        # boss laser
        if self.boss and self.boss.m.get('laser'):
            kind, ly = self.boss.m['laser']
            x_end = int(self.boss.x + 2)
            if kind == 'tele':
                if int(t * 16) % 2:
                    for x in range(0, x_end, 2):
                        self.pset(x + int(t * 30) % 2, ly, 160)
            else:
                for x in range(0, x_end):
                    j = random.random() < 0.2
                    self.pset(x, ly - 2, 201 if not j else 16)
                    self.pset(x, ly - 1, 213)
                    self.pset(x, ly, 231)
                    self.pset(x, ly + 1, 213)
                    self.pset(x, ly + 2, 201 if not j else 16)
        # enemy bullets on top so they always read clearly
        blink = int(t * 12) % 2
        for b in self.ebullets:
            arm = (201 if blink else 213) if b[4] == 0 else (208 if blink else 220) if b[4] == 1 \
                else (196 if blink else 231)
            x, y = b[0], b[1]
            self.pset(x, y, 231)
            self.pset(x - 1, y, arm)
            self.pset(x + 1, y, arm)
            self.pset(x, y - 1, arm)
            self.pset(x, y + 1, arm)
        if self.bomb:
            bx, by, r, _ = self.bomb
            self.circle(bx, by, r, 231)
            if r > 2:
                self.circle(bx, by, r - 1.5, 213)
            if r > 5:
                self.circle(bx, by, r - 4, 129)
        for tx in self.texts:
            c = tx[4] if tx[3] > 0.25 or int(t * 20) % 2 else 240
            self.text(tx[2], tx[0] - text_width(tx[2]) / 2, tx[1], c)
        self.ox = self.oy = 0
        # boss health bar
        boss = self.boss
        if boss and boss.x < W:
            bw = int(W * 0.6)
            x0 = (W - bw) // 2
            fill = int(bw * max(0, boss.hp) / boss.maxhp)
            for x in range(bw):
                c = (196 if boss.hp < boss.maxhp * 0.5 else 201) if x < fill else 237
                self.fb[x0 + x] = c
                self.fb[W + x0 + x] = c
        if self.banner:
            self.draw_banner()
        if self.over:
            if self.over_t > 1.0:
                self.big_center('GAME OVER', H // 2 - 8, lambda i, y: PINK[3 + y % 6], shadow=53)
            if self.over_t > 2.0:
                self.put_center(self.prow // 2 + 3, 'FINAL SCORE %d  -  WAVE %d' % (self.score, self.wave), 231)
                if int(t * 2.5) % 2:
                    self.put_center(self.prow // 2 + 5, 'press ENTER', 226)

    def player_sprite(self, bank):
        return SPR['player_up'] if bank < 0 else SPR['player_down'] if bank > 0 else SPR['player']

    def draw_banner(self):
        b = self.banner
        W, H = self.W, self.H
        text = b['text']
        scale = 2 if text_width(text, 2) <= W - 6 else 1
        tw = text_width(text, scale)
        u = b['t'] / b['dur']
        cx = (W - tw) / 2
        if u < 0.18:
            k = 1 - u / 0.18
            cx += k * k * W
        elif u > 0.82:
            k = (u - 0.82) / 0.18
            cx -= k * k * W
        y = int(H * 0.32)
        ramp = b['ramp']
        if b['hazard']:
            if int(self.t * 6) % 2 == 0:
                return
            for yy in (y - 4, y - 3, y + 5 * scale + 2, y + 5 * scale + 3):
                for x in range(W):
                    self.pset(x, yy, 226 if (x + yy + int(self.t * 25)) % 8 < 4 else 16)
        self.text(text, int(cx), y, lambda i, py: ramp[(py + i) % len(ramp)], scale,
                  shadow=16)

    def draw_entry(self):
        W, H, t = self.W, self.H, self.t
        e = self.entry
        self.big_center('NEW HIGH SCORE', max(2, H // 7), lambda i, y: SUNSET[(y + i) % len(SUNSET)],
                        shadow=16)
        self.put_center(H // 7 // 2 + 7, '%d points  -  wave %d' % (self.score, self.wave), 231)
        s = 3
        gap = 6
        total = 3 * 3 * s + 2 * gap
        x0 = (W - total) // 2
        y0 = H // 2 - 2
        for i, ch in enumerate(e['name']):
            sel = i == e['i']
            c = (226 if int(t * 4) % 2 else 214) if sel else 250
            self.text(ch, x0 + i * (3 * s + gap), y0, c, s, shadow=16)
            if sel:
                for x in range(3 * s):
                    self.pset(x0 + i * (3 * s + gap) + x, y0 + 5 * s + 2, c)
        self.put_center(min(self.prow - 2, (y0 + 5 * s + 6) // 2 + 1),
                        'type or UP/DOWN to pick letters   LEFT/RIGHT move   ENTER save', 245)

    # ---------------------------------------------------------- HUD + terminal output
    def hud_string(self):
        W = self.W
        if self.state in ('title', 'entry') or self.player is None:
            hi = self.scores[0]['score'] if self.scores else 0
            segs = [(' STARWAKE', 213), ('   HI %07d' % hi, 245)]
        else:
            p = self.player
            hi = max(self.score, self.scores[0]['score'] if self.scores else 0)
            dash_fill = int(round((1 - p.dash_cd / 0.85) * 4))
            segs = [(' SCORE ', 245), ('%07d' % self.score, 231),
                    (' x%d' % self.mult if self.mult > 1 else '   ', 226),
                    ('  ', 0), ('►' * max(0, p.lives) + ' ' * max(0, 3 - p.lives), 51),
                    ('  BOMB ', 245), ('●' * p.bombs + ' ' * (5 - p.bombs), 213),
                    ('PWR ', 245), ('■' * p.power, 208), ('□' * (5 - p.power), 240),
                    ('  DASH ', 245), ('█' * dash_fill, 45 if dash_fill == 4 else 31),
                    ('░' * (4 - dash_fill), 238),
                    ('  WAVE %d' % self.wave, 141), ('   HI %07d' % hi, 242)]
        out, used = [], 0
        for txt, fg in segs:
            if used + len(txt) > W:
                break
            out.append(FG[fg] + txt)
            used += len(txt)
        return BG[234] + ''.join(out) + ' ' * (W - used)

    def render(self):
        W, prow, fb = self.W, self.prow, self.fb
        out = ['\x1b[?2026h']
        hud = self.hud_string()
        if hud != self.prev_hud:
            out.append('\x1b[%d;%dH' % (self.my + 1, self.mx + 1))
            out.append(hud)
            self.prev_hud = hud
        cur_fg = cur_bg = -1
        overlay = self.overlay
        prev = self.prev
        mx = self.mx + 1
        for r in range(prow):
            top = bytes(fb[2 * r * W:(2 * r + 1) * W])
            bot = bytes(fb[(2 * r + 1) * W:(2 * r + 2) * W])
            orow = overlay.get(r)
            p = prev[r]
            if p is not None and p[0] == top and p[1] == bot and p[2] == orow:
                continue
            prev[r] = (top, bot, orow)
            if p is None:
                ptop = pbot = None
                porow = None
            else:
                ptop, pbot, porow = p
            has_ov = bool(orow or porow)
            ypos = '\x1b[%d;' % (r + self.my + 2)
            cursor = -1
            for c0 in range(0, W, 16):
                c1 = c0 + 16
                if (ptop is not None and not has_ov and ptop[c0:c1] == top[c0:c1]
                        and pbot[c0:c1] == bot[c0:c1]):
                    continue
                for x in range(c0, min(c1, W)):
                    t = top[x]
                    b = bot[x]
                    o = orow.get(x) if orow else None
                    if ptop is not None and ptop[x] == t and pbot[x] == b and \
                            o == (porow.get(x) if porow else None):
                        continue
                    if cursor != x:
                        out.append('%s%dH' % (ypos, x + mx))
                    if o:
                        if cur_fg != o[1]:
                            out.append(FG[o[1]])
                            cur_fg = o[1]
                        if cur_bg != t:
                            out.append(BG[t])
                            cur_bg = t
                        out.append(o[0])
                    elif t == b:
                        if cur_bg != t:
                            out.append(BG[t])
                            cur_bg = t
                        out.append(' ')
                    else:
                        if cur_fg != t:
                            out.append(FG[t])
                            cur_fg = t
                        if cur_bg != b:
                            out.append(BG[b])
                            cur_bg = b
                        out.append('▀')
                    cursor = x + 1
        out.append('\x1b[?2026l')
        if len(out) > 2:
            self.term.write(''.join(out))


def main():
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print('STARWAKE needs to run in a real terminal.')
        return 1
    term = Terminal()

    def bail(*_):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, bail)
    signal.signal(signal.SIGHUP, bail)
    with term:
        if '--classic-keys' not in sys.argv[1:]:
            term.detect_kitty()
        game = Game(term)
        signal.signal(signal.SIGWINCH, lambda *_: setattr(game, 'resized', True))
        try:
            game.run()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())

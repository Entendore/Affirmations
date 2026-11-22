#!/usr/bin/env python3
"""
⏳ RespectTime Studio
Positive affirmations + "respect your time" reminders + YouTube Shorts maker (9:16 MP4).

NEW:
  🎵 Background music mixing (file, volume, fade in/out, loop, live preview) — needs FFmpeg
  🖼 Image backgrounds (Ken-Burns zoom/pan, auto cover-crop)
  🎞 Video backgrounds (auto cover-crop, loops, subtle zoom) — needs OpenCV
  Dark scrim keeps text readable over any background.

Install:  pip install PySide6 opencv-python numpy   (FFmpeg on PATH recommended)
Run:      python respecttime_studio.py
"""
import sys, os, math, json, random, shutil, subprocess, tempfile, threading
from dataclasses import dataclass, asdict, fields as dcfields
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPointF, QRectF, QUrl
from PySide6.QtGui import (QPainter, QPainterPath, QColor, QFont, QFontMetrics,
                           QLinearGradient, QRadialGradient, QPen, QBrush, QImage,
                           QPixmap, QIcon, QDesktopServices, QAction, QFontDatabase)
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout,
                               QHBoxLayout, QPushButton, QPlainTextEdit, QLineEdit,
                               QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QSlider,
                               QProgressBar, QGroupBox, QListWidget, QListWidgetItem,
                               QTabWidget, QFileDialog, QMessageBox, QDialog, QFrame,
                               QSizePolicy, QFormLayout, QSystemTrayIcon, QMenu)

try:
    import numpy as np
    import cv2
    CV2_OK = True
except Exception:
    CV2_OK = False

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    QTMM_OK = True
except Exception:
    QTMM_OK = False

CANVAS_W, CANVAS_H = 1080, 1920
STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "respecttime_data.json")

# ----------------------------- content banks -----------------------------
DEFAULT_AFFIRMATIONS = [
    "I am the master of my minutes.",
    "My time is precious — I protect it fiercely.",
    "Every second I spend on growth pays me forever.",
    "I don't chase time; I invest it.",
    "Today, I choose progress over perfection.",
    "My focus is a superpower.",
    "I am building a future I'm proud of.",
    "I show up for myself every single day.",
    "Calm mind, strong decisions.",
    "I am becoming the person I admire.",
    "Discipline is my form of self-love.",
    "I deserve the future I'm working for.",
]
DEFAULT_TIME_TIPS = [
    "Respect your time — it's the only currency you can't earn back.",
    "Guard your hours like treasure; your future is buying them.",
    "Saying no to distractions is saying yes to your dreams.",
    "You don't find time. You make it. You own it.",
    "One focused hour beats ten distracted ones.",
    "Your calendar is a promise to yourself. Keep it.",
    "Scrolling steals tomorrow. Focus funds it.",
    "Time respects those who respect it.",
    "Protect your mornings like they're made of gold — they are.",
    "Where your minutes go, your life goes.",
]
BADGES = ["DAILY AFFIRMATION", "MINDSET RESET", "REPEAT AFTER ME", "BECOME BETTER", "RESPECT YOUR TIME"]
TITLE_TEMPLATES = [
    "Respect your time ⏳ “{q}”",
    "“{q}” — say this every morning",
    "Watch this before you waste today ⏳",
    "POV: you finally respect your time ⏳",
    "Your future is watching how you spend today ⏳",
]

# ----------------------------- themes -----------------------------
@dataclass
class Theme:
    name: str; top_a: str; top_b: str; bot_a: str; bot_b: str
    text: str; accent: str; glow: str

THEMES = {
    "Midnight": Theme("Midnight", "#141e30", "#1c2b4a", "#243b55", "#101a33", "#f5f7ff", "#ffd166", "#7f5af0"),
    "Sunset":   Theme("Sunset",   "#3a1c5c", "#c33764", "#ff7e5f", "#feb47b", "#fff6ec", "#ffe9a8", "#ff9d6f"),
    "Ocean":    Theme("Ocean",    "#06203f", "#0a3d62", "#0e5a8a", "#062a4a", "#eaf6ff", "#5fd7ff", "#3aa0ff"),
    "Forest":   Theme("Forest",   "#0b2b1e", "#14503a", "#1d6b4a", "#0a2418", "#f0fff6", "#a8e6a1", "#5fd08a"),
    "Rose":     Theme("Rose",     "#2b0f1e", "#5c1a3a", "#8a2b52", "#33122a", "#fff0f6", "#ffb3d1", "#ff6f9c"),
    "Mono":     Theme("Mono",     "#0d0d0f", "#1a1a1e", "#26262c", "#101013", "#f5f5f5", "#ffffff", "#8a8a95"),
}

@dataclass
class Scene:
    text: str
    badge: str = "DAILY AFFIRMATION"
    duration: float = 3.5
    bg_kind: str = "none"      # none | image | video
    bg_path: str = ""

class ProjectState:
    def __init__(self):
        self.scenes: list[Scene] = []
        self.theme_name = "Midnight"
        self.handle = "@respect.your.time"
        self.font_family = ""
        self.bold = True
        self.default_duration = 3.5
        self.affirmations = list(DEFAULT_AFFIRMATIONS)
        self.tips = list(DEFAULT_TIME_TIPS)
        self.music_path = ""
        self.music_volume = 55      # percent
        self.music_fadein = 1.5     # seconds
        self.music_fadeout = 2.0    # seconds
        self.music_loop = True

def copy_state(s: ProjectState) -> ProjectState:
    c = ProjectState()
    c.scenes = [Scene(**asdict(x)) for x in s.scenes]
    c.theme_name, c.handle = s.theme_name, s.handle
    c.font_family, c.bold, c.default_duration = s.font_family, s.bold, s.default_duration
    c.music_path, c.music_volume = s.music_path, s.music_volume
    c.music_fadein, c.music_fadeout, c.music_loop = s.music_fadein, s.music_fadeout, s.music_loop
    return c

# ----------------------------- math / text helpers -----------------------------
def clamp01(x): return 0.0 if x < 0 else (1.0 if x > 1 else x)
def ease_out(x): x = clamp01(x); return 1 - (1 - x) ** 3
def smooth(x): x = clamp01(x); return x * x * (3 - 2 * x)
def lerp(a, b, t): return a + (b - a) * t

def mix_color(c1: QColor, c2: QColor, t: float) -> QColor:
    return QColor(round(lerp(c1.red(), c2.red(), t)), round(lerp(c1.green(), c2.green(), t)),
                  round(lerp(c1.blue(), c2.blue(), t)), round(lerp(c1.alpha(), c2.alpha(), t)))

def wrap_text(fm: QFontMetrics, text: str, max_w: float):
    lines, cur = [], ""
    for w in text.split():
        trial = f"{cur} {w}".strip()
        if fm.horizontalAdvance(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur); cur = w
    if cur: lines.append(cur)
    return lines or [""]

def fit_font(text, box_w, box_h, family, bold, base=116, min_size=48):
    f = QFont(family or "")
    size = base
    while size > min_size:
        f.setPixelSize(size); f.setBold(bold)
        fm = QFontMetrics(f)
        lines = wrap_text(fm, text, box_w)
        lh = size * 1.22
        if len(lines) * lh <= box_h:
            return f, lines, lh
        size -= 4
    f.setPixelSize(min_size); f.setBold(bold)
    return f, wrap_text(QFontMetrics(f), text, box_w), min_size * 1.22

# ----------------------------- background cache (images + videos) -----------------------------
class BackgroundCache:
    """Thread-safe cache so the live preview and the export worker can share decoders."""
    def __init__(self):
        self._lock = threading.RLock()
        self._images: dict[str, QImage] = {}
        self._caps: dict[str, dict] = {}

    def get_image(self, path: str) -> QImage:
        with self._lock:
            img = self._images.get(path)
            if img is None:
                img = QImage(path)
                self._images[path] = img
            return img

    def get_video_frame(self, path: str, t: float):
        """Return a BGR ndarray for time t (seconds). Loops automatically."""
        if not CV2_OK:
            return None
        with self._lock:
            e = self._caps.get(path)
            if e is None:
                cap = cv2.VideoCapture(path)
                if not cap.isOpened():
                    self._caps[path] = {"cap": None}
                    return None
                fps = cap.get(cv2.CAP_PROP_FPS)
                if not fps or fps < 1: fps = 30.0
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                e = {"cap": cap, "fps": float(fps),
                     "total": total if total > 0 else (1 << 30), "idx": -1}
                self._caps[path] = e
            cap = e["cap"]
            if cap is None: return None
            want = int(t * e["fps"]) % e["total"]
            # big jump backwards or far forward → seek; otherwise read sequentially (fast)
            if want < e["idx"] or want - e["idx"] > int(e["fps"] * 1.2) + 2:
                cap.set(cv2.CAP_PROP_POS_FRAMES, want)
                ok, fr = cap.read()
                if ok:
                    e["idx"] = want
                    return fr
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0); e["idx"] = -1
                ok, fr = cap.read()
                if ok:
                    e["idx"] = 0
                    return fr
                return None
            fr = None
            while e["idx"] < want:
                ok, fr = cap.read()
                if ok:
                    e["idx"] += 1
                else:  # wrap to start (loop)
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0); e["idx"] = -1
            return fr if fr is not None else None

    def release_all(self):
        with self._lock:
            for e in self._caps.values():
                try:
                    if e.get("cap"): e["cap"].release()
                except Exception:
                    pass
            self._caps.clear(); self._images.clear()

BG_CACHE = BackgroundCache()

def draw_image_background(p: QPainter, path, t_local, dur, W, H) -> bool:
    """Cover-fit image with a slow Ken-Burns zoom + gentle pan."""
    img = BG_CACHE.get_image(path)
    if img is None or img.isNull(): return False
    iw, ih = img.width(), img.height()
    if iw <= 0 or ih <= 0: return False
    prog = clamp01(t_local / max(dur, 0.1))
    z = 1.03 + 0.12 * ease_out(prog)
    s = max(W / iw, H / ih) * z
    dw, dh = iw * s, ih * s
    mx = max((dw - W) / 2, 0); my = max((dh - H) / 2, 0)
    px = math.sin(t_local * 0.21) * mx * 0.5
    py = math.cos(t_local * 0.17) * my * 0.5
    p.drawImage(QRectF((W - dw) / 2 + px, (H - dh) / 2 + py, dw, dh), img)
    return True

def draw_video_background(p: QPainter, path, t_local, dur, W, H) -> bool:
    """Cover-fit video frame with a subtle zoom."""
    frame = BG_CACHE.get_video_frame(path, t_local)
    if frame is None: return False
    h, w = frame.shape[:2]
    if w <= 0 or h <= 0: return False
    prog = clamp01(t_local / max(dur, 0.1))
    z = 1.02 + 0.08 * ease_out(prog)
    s = max(W / w, H / h) * z
    dw, dh = w * s, h * s
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888)
    p.drawImage(QRectF((W - dw) / 2, (H - dh) / 2, dw, dh), img)
    return True

def draw_bg_scrim(p: QPainter, W, H):
    """Dark gradient so white text stays readable on any photo/video."""
    g = QLinearGradient(0, 0, 0, float(H))
    g.setColorAt(0.00, QColor(0, 0, 0, 120))
    g.setColorAt(0.30, QColor(0, 0, 0, 45))
    g.setColorAt(0.65, QColor(0, 0, 0, 85))
    g.setColorAt(1.00, QColor(0, 0, 0, 175))
    p.save(); p.setPen(Qt.NoPen); p.setBrush(QBrush(g)); p.drawRect(0, 0, W, H); p.restore()

# ----------------------------- the Shorts renderer (logical 1080x1920) -----------------------------
def render_frame(p: QPainter, state: ProjectState, t: float, loop: bool = True):
    W, H = CANVAS_W, CANVAS_H
    th = THEMES.get(state.theme_name) or THEMES["Midnight"]
    fam = state.font_family or ""
    scenes = state.scenes or [Scene("Your affirmation goes here — add scenes in the Studio tab ✨")]
    total = max(sum(max(s.duration, 0.2) for s in scenes), 0.2)
    tt = (t % total) if loop else min(max(t, 0.0), total - 1e-4)

    acc = 0.0; idx = 0; local = 0.0
    for i, s in enumerate(scenes):
        d = max(s.duration, 0.2)
        if tt < acc + d:
            idx = i; local = tt - acc; break
        acc += d
    else:
        idx = len(scenes) - 1
        local = max(scenes[idx].duration, 0.2)
    local = min(local, max(scenes[idx].duration, 0.2))

    sc = scenes[idx]
    dur = max(sc.duration, 0.2)
    accent, glow, text_col = QColor(th.accent), QColor(th.glow), QColor(th.text)

    # ---- background: image / video / animated gradient ----
    drew_bg = False
    if sc.bg_kind == "image" and sc.bg_path:
        drew_bg = draw_image_background(p, sc.bg_path, local, dur, W, H)
    elif sc.bg_kind == "video" and sc.bg_path and CV2_OK:
        drew_bg = draw_video_background(p, sc.bg_path, local, dur, W, H)
    if drew_bg:
        draw_bg_scrim(p, W, H)
    else:
        ph = 0.5 + 0.5 * math.sin(t * 0.45)
        c1 = mix_color(QColor(th.top_a), QColor(th.top_b), ph)
        c2 = mix_color(QColor(th.bot_a), QColor(th.bot_b), ph)
        g = QLinearGradient(0.0, 0.0, W * 0.35, float(H))
        g.setColorAt(0.0, c1); g.setColorAt(1.0, c2)
        p.fillRect(0, 0, W, H, QBrush(g))
        for k in range(3):  # drifting glow orbs
            cx = W * (0.5 + 0.34 * math.sin(t * 0.31 + k * 2.09))
            cy = H * (0.44 + 0.27 * math.cos(t * 0.27 + k * 1.71))
            r = 470 + 70 * math.sin(t * 0.5 + k * 1.3)
            rg = QRadialGradient(cx, cy, max(r, 1.0))
            col = QColor(glow if k % 2 == 0 else accent); col.setAlpha(44)
            rg.setColorAt(0.0, col)
            col2 = QColor(col); col2.setAlpha(0)
            rg.setColorAt(1.0, col2)
            p.save(); p.setPen(Qt.NoPen); p.setBrush(QBrush(rg))
            p.drawEllipse(QPointF(cx, cy), r, r); p.restore()
    vg = QRadialGradient(W / 2, H / 2, H * 0.72)
    vg.setColorAt(0.0, QColor(0, 0, 0, 0)); vg.setColorAt(1.0, QColor(0, 0, 0, 120))
    p.save(); p.setPen(Qt.NoPen); p.setBrush(QBrush(vg)); p.drawRect(0, 0, W, H); p.restore()

    # ---- story-style progress segments ----
    m, gap, seg_h, y0 = 48, 14, 12, 64
    n = len(scenes)
    seg_w = (W - 2 * m - gap * (n - 1)) / n
    p.save(); p.setPen(Qt.NoPen)
    for i, s in enumerate(scenes):
        x = m + i * (seg_w + gap)
        p.setBrush(QColor(255, 255, 255, 46))
        p.drawRoundedRect(QRectF(x, y0, seg_w, seg_h), seg_h / 2, seg_h / 2)
        d = max(s.duration, 0.2)
        fill = 1.0 if i < idx else (clamp01(local / d) if i == idx else 0.0)
        if fill > 0:
            p.setBrush(accent)
            p.drawRoundedRect(QRectF(x, y0, max(seg_w * fill, seg_h), seg_h), seg_h / 2, seg_h / 2)
    p.restore()

    # ---- badge chip ----
    badge = (sc.badge or "").upper().strip()
    if badge:
        f = QFont(fam); f.setPixelSize(30); f.setBold(True)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 6.0)
        fm = QFontMetrics(f)
        bw = min(fm.horizontalAdvance(badge) + 80, W - 120); bh = 62
        bx, by = (W - bw) / 2, y0 + seg_h + 30
        p.save()
        p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(QRectF(bx, by, bw, bh), bh / 2, bh / 2)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 140), 2))
        p.drawRoundedRect(QRectF(bx, by, bw, bh), bh / 2, bh / 2)
        p.setFont(f); p.setPen(QColor(th.accent))
        p.drawText(QRectF(bx, by, bw, bh), Qt.AlignCenter, badge)
        p.restore()

    # ---- rotating accent ring ----
    r = 340
    p.save(); p.translate(QPointF(W / 2, H * 0.44)); p.setBrush(Qt.NoBrush)
    ring = QColor(accent); ring.setAlpha(38)
    p.setPen(QPen(ring, 3)); p.drawEllipse(QPointF(0, 0), r, r)
    a0 = (t * 40) % 360
    arc = QColor(accent); arc.setAlpha(90)
    pen = QPen(arc, 6); pen.setCapStyle(Qt.RoundCap); p.setPen(pen)
    rect = QRectF(-r, -r, 2 * r, 2 * r)
    p.drawArc(rect, int(a0 * 16), 55 * 16)
    p.drawArc(rect, int((a0 + 180) * 16), 55 * 16)
    p.restore()

    # ---- main text (line-by-line reveal + fade) ----
    out_a = smooth(clamp01((dur - local) / 0.45))
    font, lines, lh = fit_font(sc.text, W - 300, H * 0.42, fam, state.bold)
    block_h = len(lines) * lh
    top = H * 0.44 - block_h / 2

    qf = QFont(fam or "Georgia"); qf.setPixelSize(210); qf.setBold(True)
    p.save(); p.setFont(qf)
    qc = QColor(accent); qc.setAlphaF(0.14 * out_a)
    p.setPen(QColor(qc))
    p.drawText(QRectF(0, top - 260, W, 250), Qt.AlignHCenter | Qt.AlignVCenter, "“")
    p.restore()

    p.save(); p.setFont(font)
    for i, line in enumerate(lines):
        ain = ease_out((local - 0.05 - i * 0.14) / 0.5)
        a = ain * out_a
        if a <= 0.01: continue
        yoff = (1 - ain) * 70 + math.sin(t * 1.5 + i * 0.4) * 6
        rect = QRectF(0, top + i * lh + yoff, W, lh)
        p.setPen(QColor(0, 0, 0, int(150 * a)))
        p.drawText(rect.translated(0, 8), Qt.AlignHCenter | Qt.AlignVCenter, line)
        col = QColor(text_col); col.setAlphaF(a)
        p.setPen(QColor(col))
        p.drawText(rect, Qt.AlignHCenter | Qt.AlignVCenter, line)
    p.restore()

    # ---- bottom chrome ----
    p.save(); p.setPen(Qt.NoPen); p.setBrush(accent)
    p.drawRoundedRect(QRectF(W / 2 - 70, H - 330, 140, 8), 4, 4); p.restore()
    f2 = QFont(fam); f2.setPixelSize(34); f2.setBold(True)
    f2.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4.0)
    p.save(); p.setFont(f2); p.setPen(QColor(255, 255, 255, 150))
    p.drawText(QRectF(0, H - 300, W, 50), Qt.AlignHCenter, f"{idx + 1} / {n}"); p.restore()
    f3 = QFont(fam); f3.setPixelSize(54); f3.setBold(True)
    p.save(); p.setFont(f3); p.setPen(QColor(text_col))
    p.drawText(QRectF(0, H - 236, W, 84), Qt.AlignHCenter | Qt.AlignVCenter, state.handle or ""); p.restore()
    f4 = QFont(fam); f4.setPixelSize(26); f4.setBold(True)
    f4.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 10.0)
    p.save(); p.setFont(f4); p.setPen(QColor(255, 255, 255, 115))
    p.drawText(QRectF(0, H - 128, W, 44), Qt.AlignHCenter | Qt.AlignVCenter, "RESPECT YOUR TIME"); p.restore()

# ----------------------------- live preview -----------------------------
class PreviewCanvas(QWidget):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.t = 0.0
        self.playing = True
        self.setMinimumSize(300, 534)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        if self.playing and self.isVisible():
            self.t += self._timer.interval() / 1000.0
            self.update()

    def mousePressEvent(self, e):
        self.playing = not self.playing
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#0b0b11"))
        s = min(self.width() / CANVAS_W, self.height() / CANVAS_H)
        pw, ph = CANVAS_W * s, CANVAS_H * s
        ox, oy = (self.width() - pw) / 2, (self.height() - ph) / 2
        p.save()
        p.translate(ox, oy); p.scale(s, s)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, CANVAS_W, CANVAS_H), 46, 46)
        p.setClipPath(path)
        render_frame(p, self.state, self.t, loop=True)
        p.restore()
        p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor("#2c2c44"), 2))
        p.drawRoundedRect(QRectF(ox, oy, pw, ph), 46 * s, 46 * s)
        p.end()

# ----------------------------- export worker -----------------------------
def qimage_rgb_array(img: QImage):
    h, w, bpl = img.height(), img.width(), img.bytesPerLine()
    arr = np.frombuffer(img.constBits(), dtype=np.uint8).reshape(h, bpl)
    return arr[:, :w * 3].reshape(h, w, 3).copy()

class ExportWorker(QThread):
    pct = Signal(int)          # absolute percent 0-100
    phase = Signal(str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, state, out_path, w, h, fps):
        super().__init__()
        self.state, self.out, self.w, self.h, self.fps = state, out_path, w, h, fps
        self.total_dur = max(sum(max(s.duration, 0.2) for s in state.scenes), 0.2)
        self._cancel = False
        self._silent = ""

    def cancel(self): self._cancel = True

    def _frames_iter(self):
        frames = max(1, int(round(self.total_dur * self.fps)))
        for i in range(frames):
            yield i, frames, i / self.fps

    def _render(self, t):
        img = QImage(self.w, self.h, QImage.Format_RGB888)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        s = self.w / CANVAS_W
        p.scale(s, s)
        render_frame(p, self.state, t, loop=False)
        p.end()
        return img

    def run(self):
        try:
            if self.state.music_path and not shutil.which("ffmpeg"):
                raise RuntimeError("Background music mixing needs FFmpeg on your PATH.\n"
                                   "Install FFmpeg (ffmpeg.org) or clear the music track.")
            self.phase.emit("🎬 Rendering frames…")
            self._silent = self.out + ".silent.mp4"
            try:
                if CV2_OK:
                    self._run_cv2(self._silent)
                elif shutil.which("ffmpeg"):
                    self._run_ffmpeg_frames(self._silent)
                else:
                    raise RuntimeError("To export MP4 install: pip install opencv-python numpy "
                                       "(or put FFmpeg on PATH).")
                if self._cancel:
                    raise RuntimeError("Export cancelled.")
                self.phase.emit("📦 Encoding H.264…")
                self.pct.emit(88)
                self._finalize(self._silent)
                self._silent = ""
            finally:
                if self._silent and os.path.exists(self._silent):
                    try: os.remove(self._silent)
                    except Exception: pass
        except Exception as e:
            self.failed.emit(str(e))

    def _run_cv2(self, out_path):
        fd, tmp = tempfile.mkstemp(suffix=".mp4"); os.close(fd); os.remove(tmp)
        vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (self.w, self.h))
        if not vw.isOpened():
            raise RuntimeError("OpenCV could not open the video writer.")
        for i, frames, t in self._frames_iter():
            if self._cancel: break
            img = self._render(t)
            vw.write(cv2.cvtColor(qimage_rgb_array(img), cv2.COLOR_RGB2BGR))
            self.pct.emit(int((i + 1) / frames * 85))
        vw.release()
        if self._cancel:
            if os.path.exists(tmp): os.remove(tmp)
            return
        shutil.move(tmp, out_path)

    def _run_ffmpeg_frames(self, out_path):
        tmpd = tempfile.mkdtemp()
        try:
            for i, frames, t in self._frames_iter():
                if self._cancel: break
                self._render(t).save(os.path.join(tmpd, f"f_{i:06d}.png"), "PNG")
                self.pct.emit(int((i + 1) / frames * 85))
            if self._cancel: return
            res = subprocess.run(
                ["ffmpeg", "-y", "-framerate", str(self.fps), "-i", os.path.join(tmpd, "f_%06d.png"),
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                 "-movflags", "+faststart", out_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0:
                raise RuntimeError("FFmpeg failed: " + (res.stderr or "")[-400:])
        finally:
            shutil.rmtree(tmpd, ignore_errors=True)

    def _finalize(self, silent):
        """Encode to H.264, then mix background music if requested."""
        if not shutil.which("ffmpeg"):
            shutil.move(silent, self.out)
            self.pct.emit(100)
            self.finished_ok.emit(self.out)
            return
        enc = self.out + ".enc.mp4"
        res = subprocess.run(
            ["ffmpeg", "-y", "-i", silent, "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-crf", "20", "-preset", "medium", "-movflags", "+faststart", enc],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode != 0 or not os.path.exists(enc):
            raise RuntimeError("H.264 encoding failed. Is FFmpeg installed correctly?")
        try: os.remove(silent)
        except Exception: pass

        if self.state.music_path and os.path.exists(self.state.music_path):
            self.phase.emit("🎵 Mixing background music…")
            self.pct.emit(93)
            self._mux_audio(enc)
            try: os.remove(enc)
            except Exception: pass
        else:
            os.replace(enc, self.out)
        self.pct.emit(100)
        self.finished_ok.emit(self.out)

    def _mux_audio(self, video_in):
        st = self.state
        vol = max(0.0, min(1.0, st.music_volume / 100.0))
        filters = [f"volume={vol:.2f}"]
        if st.music_fadein > 0:
            filters.append(f"afade=t=in:st=0:d={st.music_fadein:.2f}")
        if st.music_fadeout > 0:
            start = max(self.total_dur - st.music_fadeout, 0.0)
            filters.append(f"afade=t=out:st={start:.2f}:d={st.music_fadeout:.2f}")
        cmd = ["ffmpeg", "-y", "-i", video_in]
        if st.music_loop:
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", st.music_path,
                "-filter_complex", f"[1:a]{','.join(filters)}[a]",
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", self.out]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0 or not os.path.exists(self.out):
            raise RuntimeError("Music mixing failed:\n" + (res.stderr or "")[-400:])

# ----------------------------- focus timer tab -----------------------------
class TimerTab(QWidget):
    def __init__(self, state, tray=None, parent=None):
        super().__init__(parent)
        self.state, self.tray = state, tray
        self.phase, self.running = "idle", False
        self.remaining = 25 * 60; self.total = 25 * 60; self.sessions = 0

        root = QHBoxLayout(self)
        g = QGroupBox("⏱ Focus sessions — respect your time")
        v = QVBoxLayout(g)
        self.phase_label = QLabel("Ready when you are.")
        self.phase_label.setAlignment(Qt.AlignCenter); self.phase_label.setObjectName("phaseLabel")
        self.time_label = QLabel("25:00"); self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setObjectName("bigTime")
        self.pb = QProgressBar(); self.pb.setRange(0, self.total); self.pb.setValue(self.total)
        self.pb.setTextVisible(False)
        btns = QHBoxLayout()
        self.b_start = QPushButton("▶  Start focus"); self.b_start.setMinimumHeight(40)
        self.b_start.clicked.connect(self._toggle)
        b_reset = QPushButton("⟳ Reset"); b_reset.clicked.connect(self._reset)
        b_skip = QPushButton("⏭ Skip"); b_skip.clicked.connect(self._skip)
        btns.addWidget(self.b_start); btns.addWidget(b_reset); btns.addWidget(b_skip)
        form = QFormLayout()
        self.work_spin = QSpinBox(); self.work_spin.setRange(5, 120); self.work_spin.setValue(25); self.work_spin.setSuffix(" min")
        self.break_spin = QSpinBox(); self.break_spin.setRange(1, 60); self.break_spin.setValue(5); self.break_spin.setSuffix(" min")
        form.addRow("Focus length:", self.work_spin); form.addRow("Break length:", self.break_spin)
        self.sessions_label = QLabel("🎯 Sessions completed: 0")
        v.addWidget(self.phase_label); v.addWidget(self.time_label); v.addWidget(self.pb)
        v.addLayout(btns); v.addLayout(form); v.addWidget(self.sessions_label)
        root.addWidget(g, 1)

        g2 = QGroupBox("🔔 Respect-your-time reminders")
        v2 = QVBoxLayout(g2)
        self.rem_cb = QCheckBox("Pop up a reminder while I work")
        self.rem_minutes = QSpinBox(); self.rem_minutes.setRange(5, 240); self.rem_minutes.setValue(45); self.rem_minutes.setSuffix(" min")
        form2 = QFormLayout(); form2.addRow("Every:", self.rem_minutes)
        b_test = QPushButton("🔔 Test reminder"); b_test.clicked.connect(self._remind)
        self.quote_label = QLabel(); self.quote_label.setWordWrap(True); self.quote_label.setObjectName("quoteLabel")
        b_q = QPushButton("🔄 New reminder quote"); b_q.clicked.connect(self._new_quote)
        note = QLabel("Keep the app running (it lives in the tray). Reminders appear as desktop notifications.")
        note.setWordWrap(True); note.setObjectName("muted")
        v2.addWidget(self.rem_cb); v2.addLayout(form2); v2.addWidget(b_test)
        v2.addWidget(self.quote_label); v2.addWidget(b_q); v2.addWidget(note); v2.addStretch(1)
        root.addWidget(g2, 1)

        self.timer = QTimer(self); self.timer.setInterval(1000); self.timer.timeout.connect(self._tick)
        self.rem_timer = QTimer(self); self.rem_timer.timeout.connect(self._remind)
        self.rem_cb.toggled.connect(self._remind_toggled)
        self.rem_minutes.valueChanged.connect(lambda _: self._remind_toggled(self.rem_cb.isChecked()))
        self._new_quote(); self._update_label()

    def _remind_toggled(self, on):
        self.rem_timer.start(self.rem_minutes.value() * 60_000) if on else self.rem_timer.stop()

    def _remind(self):
        msg = random.choice(self.state.affirmations + self.state.tips)
        if self.tray is not None:
            self.tray.showMessage("⏳ Respect your time", msg, QSystemTrayIcon.Information, 8000)
        else:
            self._popup("⏳ Respect your time", msg)

    def _new_quote(self):
        self.quote_label.setText("“" + random.choice(self.state.tips + self.state.affirmations) + "”")

    def _toggle(self):
        if self.phase == "idle":
            self._start_phase("focus"); self.running = True; self.timer.start()
        else:
            self.running = not self.running
        self.b_start.setText("⏸ Pause" if self.running else "▶ Resume")

    def _start_phase(self, p):
        self.phase = p
        mins = self.work_spin.value() if p == "focus" else self.break_spin.value()
        self.total = int(mins * 60); self.remaining = self.total
        self.pb.setRange(0, self.total); self.pb.setValue(self.total)
        if p == "focus":
            self.phase_label.setText("🔒 FOCUS — this block is sacred"); col = "#7ee787"
        else:
            self.phase_label.setText("☕ BREAK — rest without guilt"); col = "#ffd166"
        self.phase_label.setStyleSheet(f"color:{col}; font-weight:700;")
        self._update_label()

    def _tick(self):
        if not self.running: return
        self.remaining -= 1
        self.pb.setValue(max(self.remaining, 0)); self._update_label()
        if self.remaining <= 0: self._advance()

    def _advance(self, credit=True):
        if self.phase == "focus":
            if credit:
                self.sessions += 1
                self.sessions_label.setText(f"🎯 Sessions completed: {self.sessions}")
            self._start_phase("break"); QApplication.beep()
            self._popup("Break time ☕", "Session done — you just respected your time.\n\n"
                        + random.choice(self.state.affirmations))
        else:
            self._start_phase("focus"); QApplication.beep()
            self._popup("Back to focus ⚡", "Protect the next block like it owes you money.\n\n"
                        + random.choice(self.state.tips))

    def _skip(self):
        if self.phase == "idle": return
        self.running = False
        self._advance(credit=False)
        self.b_start.setText("▶ Resume")

    def _reset(self):
        self.phase, self.running = "idle", False
        self.total = int(self.work_spin.value() * 60); self.remaining = self.total
        self.pb.setRange(0, self.total); self.pb.setValue(self.total)
        self.phase_label.setText("Ready when you are."); self.phase_label.setStyleSheet("")
        self.b_start.setText("▶  Start focus"); self._update_label()

    def _update_label(self):
        mm, ss = divmod(max(self.remaining, 0), 60)
        self.time_label.setText(f"{mm:02d}:{ss:02d}")

    def _popup(self, title, msg):
        d = QDialog(self); d.setWindowTitle(title)
        v = QVBoxLayout(d)
        t = QLabel(title); t.setObjectName("popupTitle"); t.setWordWrap(True)
        m = QLabel(msg); m.setObjectName("popupMsg"); m.setWordWrap(True)
        b = QPushButton("OK, I respect that ✊"); b.clicked.connect(d.accept)
        v.addWidget(t); v.addWidget(m); v.addWidget(b, 0, Qt.AlignRight)
        d.resize(440, 240); d.exec()

# ----------------------------- main window -----------------------------
RESOLUTIONS = {"1080 × 1920 (Recommended)": (1080, 1920), "720 × 1280 (Faster)": (720, 1280)}
FPS_OPTIONS = {"30 fps (Recommended)": 30, "24 fps (Cinematic)": 24, "60 fps (Smooth)": 60}
AUDIO_FILTER = "Audio (*.mp3 *.wav *.m4a *.aac *.ogg *.flac)"
IMG_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
VID_FILTER = "Videos (*.mp4 *.mov *.avi *.mkv *.webm *.m4v)"

def default_export_path():
    vid = os.path.join(os.path.expanduser("~"), "Videos")
    folder = vid if os.path.isdir(vid) else os.path.expanduser("~")
    return os.path.join(folder, datetime.now().strftime("respecttime_short_%Y%m%d_%H%M.mp4"))

def make_app_icon() -> QIcon:
    pm = QPixmap(128, 128); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, 128, 128)
    g.setColorAt(0, QColor("#243b55")); g.setColorAt(1, QColor("#0f1830"))
    p.setPen(Qt.NoPen); p.setBrush(QBrush(g)); p.drawEllipse(4, 4, 120, 120)
    f = QFont("Arial"); f.setPixelSize(48); f.setBold(True)
    p.setFont(f); p.setPen(QColor("#ffd166"))
    p.drawText(pm.rect(), Qt.AlignCenter, "⏳"); p.end()
    return QIcon(pm)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("⏳ RespectTime Studio — affirmations + YouTube Shorts maker")
        self.resize(1320, 900)
        self.setWindowIcon(make_app_icon())
        self.state = ProjectState()
        self._load_store()
        self.worker = None
        self.exp_path = ""
        self._last_aff = -1; self._last_tip = -1
        self._music_player = None; self._music_out = None; self._music_playing = False
        self._build_menu()
        self._build_ui()
        self._make_tray()
        self.timer_tab.tray = self.tray
        if not self.state.scenes: self._random_short()
        else: self._refresh_scenes()
        self._sync_style_widgets(); self._sync_music_widgets()
        self._update_export_info()
        self._new_status_tip()
        self.tip_timer = QTimer(self); self.tip_timer.setInterval(45_000)
        self.tip_timer.timeout.connect(self._new_status_tip); self.tip_timer.start()

    # ---------- persistence ----------
    def _load_store(self):
        try:
            with open(STORE, "r", encoding="utf-8") as f: data = json.load(f)
            self.state.affirmations = data.get("affirmations") or list(DEFAULT_AFFIRMATIONS)
            self.state.tips = data.get("tips") or list(DEFAULT_TIME_TIPS)
            self.state.theme_name = data.get("theme") if data.get("theme") in THEMES else "Midnight"
            self.state.handle = data.get("handle", "@respect.your.time")
            self.state.font_family = data.get("font", "")
            self.state.bold = bool(data.get("bold", True))
            self.state.default_duration = float(data.get("default_duration", 3.5))
            self.state.music_path = data.get("music_path", "")
            self.state.music_volume = int(data.get("music_volume", 55))
            self.state.music_fadein = float(data.get("music_fadein", 1.5))
            self.state.music_fadeout = float(data.get("music_fadeout", 2.0))
            self.state.music_loop = bool(data.get("music_loop", True))
            valid = {f.name for f in dcfields(Scene)}
            self.state.scenes = [Scene(**{k: v for k, v in d.items() if k in valid})
                                 for d in data.get("scenes", [])]
        except Exception:
            pass

    def _save_store(self):
        data = {"affirmations": self.state.affirmations, "tips": self.state.tips,
                "theme": self.state.theme_name, "handle": self.state.handle,
                "font": self.state.font_family, "bold": self.state.bold,
                "default_duration": self.state.default_duration,
                "music_path": self.state.music_path, "music_volume": self.state.music_volume,
                "music_fadein": self.state.music_fadein, "music_fadeout": self.state.music_fadeout,
                "music_loop": self.state.music_loop,
                "scenes": [asdict(s) for s in self.state.scenes]}
        try:
            with open(STORE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------- menu / tray ----------
    def _build_menu(self):
        mb = self.menuBar()
        m_file = mb.addMenu("&File")
        a_exp = QAction("Export Short…", self)
        a_exp.triggered.connect(lambda: self.tabs.setCurrentIndex(1))
        a_save = QAction("Save content", self); a_save.setShortcut("Ctrl+S")
        a_save.triggered.connect(self._save_content)
        a_quit = QAction("Exit", self); a_quit.triggered.connect(self.close)
        m_file.addAction(a_exp); m_file.addAction(a_save); m_file.addSeparator(); m_file.addAction(a_quit)
        m_help = mb.addMenu("&Help")
        a_about = QAction("About", self)
        a_about.triggered.connect(lambda: QMessageBox.about(
            self, "About",
            "⏳ RespectTime Studio\n\nAffirmations • time-respect reminders • 9:16 Shorts exporter.\n"
            "Now with 🎵 music mixing and 🖼 image / 🎞 video backgrounds.\n"
            "Made with PySide6. Respect your time. 💛"))
        m_help.addAction(a_about)

    def _make_tray(self):
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(make_app_icon(), self)
            menu = QMenu()
            a_show = menu.addAction("Show RespectTime Studio")
            a_show.triggered.connect(self.showNormal)
            menu.addSeparator()
            a_quit = menu.addAction("Exit"); a_quit.triggered.connect(self.close)
            self.tray.setContextMenu(menu)
            self.tray.setToolTip("RespectTime Studio")
            self.tray.show()

    # ---------- UI ----------
    def _build_ui(self):
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_studio(), "🎬 Studio")
        self.tabs.addTab(self._build_export(), "📼 Export")
        self.tabs.addTab(self._build_content(), "✍️ Content")
        self.timer_tab = TimerTab(self.state)
        self.tabs.addTab(self.timer_tab, "⏱ Respect Timer")
        self.tabs.currentChanged.connect(lambda _: self._update_export_info())
        self.setCentralWidget(self.tabs)

    def _build_studio(self):
        st = QWidget(); root = QHBoxLayout(st)

        left = QVBoxLayout()
        card = QFrame(); card.setObjectName("previewCard")
        cv = QVBoxLayout(card); cv.setContentsMargins(10, 10, 10, 10)
        self.preview = PreviewCanvas(self.state)
        cv.addWidget(self.preview, 1)
        left.addWidget(card, 1)
        ctl = QHBoxLayout()
        b_re = QPushButton("⏮"); b_re.setFixedWidth(52); b_re.setToolTip("Back to start")
        b_re.clicked.connect(lambda: setattr(self.preview, "t", 0.0))
        b_pv = QPushButton("⏪"); b_pv.setFixedWidth(52); b_pv.clicked.connect(lambda: self._jump(-1))
        self.b_play = QPushButton("⏸ Pause"); self.b_play.setMinimumWidth(96)
        self.b_play.clicked.connect(self._toggle_play)
        b_nx = QPushButton("⏩"); b_nx.setFixedWidth(52); b_nx.clicked.connect(lambda: self._jump(1))
        ctl.addWidget(b_re); ctl.addWidget(b_pv); ctl.addWidget(self.b_play); ctl.addWidget(b_nx)
        left.addLayout(ctl)
        self.time_label = QLabel("Scene 1/1"); self.time_label.setObjectName("muted")
        self.time_label.setAlignment(Qt.AlignCenter)
        left.addWidget(self.time_label)
        root.addLayout(left, 5)

        right = QVBoxLayout()
        gs = QGroupBox("🎞 Scenes (story order)")
        v = QVBoxLayout(gs)
        self.scene_list = QListWidget()
        self.scene_list.currentRowChanged.connect(self._on_scene_selected)
        v.addWidget(self.scene_list, 1)
        r1 = QHBoxLayout()
        b_aff = QPushButton("＋ Affirmation"); b_aff.clicked.connect(self._add_affirmation)
        b_tip = QPushButton("＋ Time tip"); b_tip.clicked.connect(self._add_tip)
        b_cust = QPushButton("＋ Custom"); b_cust.clicked.connect(self._add_custom)
        b_rnd = QPushButton("🎲 Random Short"); b_rnd.setObjectName("accent"); b_rnd.clicked.connect(self._random_short)
        for b in (b_aff, b_tip, b_cust, b_rnd): r1.addWidget(b)
        v.addLayout(r1)
        r2 = QHBoxLayout()
        b_up = QPushButton("⬆"); b_up.setFixedWidth(48); b_up.clicked.connect(lambda: self._move(-1))
        b_dn = QPushButton("⬇"); b_dn.setFixedWidth(48); b_dn.clicked.connect(lambda: self._move(1))
        b_del = QPushButton("🗑 Remove"); b_del.clicked.connect(self._delete_scene)
        b_clr = QPushButton("Clear all"); b_clr.clicked.connect(self._clear_scenes)
        r2.addWidget(b_up); r2.addWidget(b_dn); r2.addWidget(b_del); r2.addWidget(b_clr); r2.addStretch(1)
        v.addLayout(r2)
        right.addWidget(gs, 3)

        # ---- scene text editor ----
        ge = QGroupBox("✏️ Edit selected scene")
        ve = QVBoxLayout(ge)
        form = QFormLayout()
        self.badge_edit = QLineEdit(); self.badge_edit.setPlaceholderText("DAILY AFFIRMATION")
        self.dur_spin = QDoubleSpinBox(); self.dur_spin.setRange(1.0, 10.0)
        self.dur_spin.setSingleStep(0.5); self.dur_spin.setSuffix(" s")
        form.addRow("Badge:", self.badge_edit); form.addRow("Duration:", self.dur_spin)
        ve.addLayout(form)
        self.scene_edit = QPlainTextEdit()
        self.scene_edit.setPlaceholderText("Write your affirmation or time-respect line here…")
        ve.addWidget(self.scene_edit, 1)
        b_apply = QPushButton("✔ Apply to selected"); b_apply.clicked.connect(self._apply_scene)
        ve.addWidget(b_apply)
        right.addWidget(ge, 2)

        # ---- background picker (NEW) ----
        gb = QGroupBox("🖼 Background (selected scene)")
        vb = QVBoxLayout(gb)
        fb = QHBoxLayout()
        self.bg_combo = QComboBox()
        self.bg_combo.addItems(["None (gradient)", "Image", "Video"])
        self.bg_combo.currentIndexChanged.connect(self._bg_kind_changed)
        self.bg_choose = QPushButton("📁 Choose file…"); self.bg_choose.clicked.connect(self._bg_choose_file)
        fb.addWidget(self.bg_combo, 1); fb.addWidget(self.bg_choose)
        vb.addLayout(fb)
        self.bg_path_label = QLabel("—"); self.bg_path_label.setObjectName("muted")
        self.bg_path_label.setWordWrap(True)
        vb.addWidget(self.bg_path_label)
        self.bg_warn = QLabel(""); self.bg_warn.setObjectName("warn"); self.bg_warn.hide()
        vb.addWidget(self.bg_warn)
        self.bg_all = QPushButton("↧ Apply this background to ALL scenes")
        self.bg_all.clicked.connect(self._bg_apply_all)
        vb.addWidget(self.bg_all)
        hint = QLabel("Backgrounds are auto cover-cropped to 9:16 with a slow Ken-Burns zoom "
                      "and a dark scrim so text stays readable.")
        hint.setWordWrap(True); hint.setObjectName("muted")
        vb.addWidget(hint)
        right.addWidget(gb)

        gy = QGroupBox("🎨 Style")
        vy = QHBoxLayout(gy)
        form2 = QFormLayout()
        self.theme_combo = QComboBox(); self.theme_combo.addItems(list(THEMES.keys()))
        self.theme_combo.currentTextChanged.connect(self._style_changed)
        self.handle_edit = QLineEdit(); self.handle_edit.textEdited.connect(self._style_changed)
        self.font_combo = QComboBox()
        try: fams = QFontDatabase.families()
        except Exception: fams = []
        self.font_combo.addItem("Default (system)"); self.font_combo.addItems(fams)
        self.font_combo.currentTextChanged.connect(self._style_changed)
        self.bold_check = QCheckBox("Bold"); self.bold_check.setChecked(True)
        self.bold_check.toggled.connect(self._style_changed)
        self.newdur_spin = QDoubleSpinBox(); self.newdur_spin.setRange(1.0, 10.0)
        self.newdur_spin.setValue(self.state.default_duration)
        self.newdur_spin.setSingleStep(0.5); self.newdur_spin.setSuffix(" s")
        self.newdur_spin.valueChanged.connect(self._style_changed)
        form2.addRow("Theme:", self.theme_combo); form2.addRow("Handle:", self.handle_edit)
        form2.addRow("Font:", self.font_combo); form2.addRow(self.bold_check, self.newdur_spin)
        vy.addLayout(form2); vy.addStretch(1)
        right.addWidget(gy)

        root.addLayout(right, 6)
        self.time_timer = QTimer(self); self.time_timer.setInterval(150)
        self.time_timer.timeout.connect(self._update_time_label); self.time_timer.start()
        return st

    def _build_export(self):
        ex = QWidget(); root = QHBoxLayout(ex)
        left = QVBoxLayout()
        g = QGroupBox("📼 Export video")
        v = QVBoxLayout(g)
        form = QFormLayout()
        self.res_combo = QComboBox(); self.res_combo.addItems(list(RESOLUTIONS.keys()))
        self.fps_combo = QComboBox(); self.fps_combo.addItems(list(FPS_OPTIONS.keys()))
        form.addRow("Resolution:", self.res_combo); form.addRow("Frame rate:", self.fps_combo)
        v.addLayout(form)
        prow = QHBoxLayout()
        self.exp_file = QLineEdit(); self.exp_file.setPlaceholderText(str(default_export_path()))
        b_browse = QPushButton("…"); b_browse.setFixedWidth(40)
        b_browse.clicked.connect(self._browse_out)
        prow.addWidget(self.exp_file); prow.addWidget(b_browse)
        v.addLayout(prow)
        self.exp_info = QLabel(""); self.exp_info.setObjectName("muted"); v.addWidget(self.exp_info)
        self.exp_progress = QProgressBar(); self.exp_progress.setRange(0, 100); v.addWidget(self.exp_progress)
        br = QHBoxLayout()
        self.exp_btn = QPushButton("🚀 Export MP4"); self.exp_btn.setObjectName("accent")
        self.exp_btn.setMinimumHeight(42); self.exp_btn.clicked.connect(self._do_export)
        self.cancel_btn = QPushButton("Cancel"); self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_export)
        self.open_btn = QPushButton("📂 Open folder"); self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_folder)
        br.addWidget(self.exp_btn); br.addWidget(self.cancel_btn); br.addWidget(self.open_btn)
        v.addLayout(br)
        if not CV2_OK and not shutil.which("ffmpeg"):
            warn = QLabel("⚠️ To render MP4 files install one of:\n• pip install opencv-python numpy\n• FFmpeg on your PATH")
            warn.setObjectName("warn"); warn.setWordWrap(True); v.addWidget(warn)
        tip = QLabel("💡 Shorts tips: vertical 9:16, under 60s. Add trending music + #Shorts in the YouTube app.")
        tip.setWordWrap(True); tip.setObjectName("muted"); v.addWidget(tip)
        left.addWidget(g); left.addStretch(1)
        root.addLayout(left, 3)

        # ---- background music (NEW) ----
        gm = QGroupBox("🎵 Background music (mixed into the MP4)")
        vm = QVBoxLayout(gm)
        mrow = QHBoxLayout()
        self.music_file = QLineEdit(); self.music_file.setPlaceholderText("No music selected — pick a track")
        self.music_file.setReadOnly(True)
        b_mbr = QPushButton("🎵 Browse"); b_mbr.clicked.connect(self._music_browse)
        b_mclr = QPushButton("✕"); b_mclr.setFixedWidth(36)
        b_mclr.setToolTip("Remove music")
        b_mclr.clicked.connect(self._music_clear)
        mrow.addWidget(self.music_file, 1); mrow.addWidget(b_mbr); mrow.addWidget(b_mclr)
        vm.addLayout(mrow)
        vrow = QHBoxLayout()
        vrow.addWidget(QLabel("Volume"))
        self.music_vol = QSlider(Qt.Horizontal); self.music_vol.setRange(0, 100)
        self.music_vol.setValue(self.state.music_volume)
        self.music_vol_lbl = QLabel(f"{self.music_vol.value()}%"); self.music_vol_lbl.setFixedWidth(44)
        self.music_vol.valueChanged.connect(lambda val: (self.music_vol_lbl.setText(f"{val}%"),
                                                         self._music_vol_live(val)))
        vrow.addWidget(self.music_vol, 1); vrow.addWidget(self.music_vol_lbl)
        vm.addLayout(vrow)
        frow = QHBoxLayout()
        fform = QFormLayout()
        self.music_fadein = QDoubleSpinBox(); self.music_fadein.setRange(0.0, 8.0)
        self.music_fadein.setSingleStep(0.5); self.music_fadein.setSuffix(" s")
        self.music_fadein.setValue(self.state.music_fadein)
        self.music_fadeout = QDoubleSpinBox(); self.music_fadeout.setRange(0.0, 8.0)
        self.music_fadeout.setSingleStep(0.5); self.music_fadeout.setSuffix(" s")
        self.music_fadeout.setValue(self.state.music_fadeout)
        fform.addRow("Fade in:", self.music_fadein); fform.addRow("Fade out:", self.music_fadeout)
        frow.addLayout(fform, 1)
        self.music_loop = QCheckBox("Loop if track is\nshorter than video")
        self.music_loop.setChecked(self.state.music_loop)
        frow.addWidget(self.music_loop)
        vm.addLayout(frow)
        prow2 = QHBoxLayout()
        self.b_music_prev = QPushButton("▶ Preview music"); self.b_music_prev.clicked.connect(self._music_toggle_preview)
        prow2.addWidget(self.b_music_prev); prow2.addStretch(1)
        vm.addLayout(prow2)
        self.music_note = QLabel(); self.music_note.setObjectName("warn"); self.music_note.setWordWrap(True)
        vm.addWidget(self.music_note)
        mm_note = QLabel("Mixing uses FFmpeg. Preview playback uses Qt Multimedia.")
        mm_note.setObjectName("muted"); mm_note.setWordWrap(True)
        vm.addWidget(mm_note)
        root.addWidget(gm)

        right = QVBoxLayout()
        g2 = QGroupBox("🏷 Publish kit")
        v2 = QVBoxLayout(g2)
        b_cap = QPushButton("📋 Copy caption + hashtags"); b_cap.clicked.connect(self._copy_caption)
        b_title = QPushButton("🎯 Generate title"); b_title.clicked.connect(self._gen_title)
        self.title_label = QLabel("—"); self.title_label.setWordWrap(True); self.title_label.setObjectName("quoteLabel")
        v2.addWidget(b_cap); v2.addWidget(b_title); v2.addWidget(self.title_label); v2.addStretch(1)
        right.addWidget(g2); right.addStretch(1)
        root.addLayout(right, 2)
        return ex

    def _build_content(self):
        c = QWidget(); root = QHBoxLayout(c)
        g1 = QGroupBox("💫 Positive affirmations (one per line)")
        v1 = QVBoxLayout(g1)
        self.aff_edit = QPlainTextEdit(); self.aff_edit.setPlainText("\n".join(self.state.affirmations))
        b1 = QPushButton("💾 Save affirmations"); b1.clicked.connect(self._save_content)
        v1.addWidget(self.aff_edit); v1.addWidget(b1)
        g2 = QGroupBox("⏳ Respect-your-time lines (one per line)")
        v2 = QVBoxLayout(g2)
        self.tip_edit = QPlainTextEdit(); self.tip_edit.setPlainText("\n".join(self.state.tips))
        b2 = QPushButton("↺ Restore defaults"); b2.clicked.connect(self._restore_defaults)
        v2.addWidget(self.tip_edit); v2.addWidget(b2)
        root.addWidget(g1); root.addWidget(g2)
        return c

    # ---------- studio actions ----------
    def _style_changed(self):
        self.state.theme_name = self.theme_combo.currentText()
        self.state.handle = self.handle_edit.text()
        self.state.font_family = "" if self.font_combo.currentIndex() == 0 else self.font_combo.currentText()
        self.state.bold = self.bold_check.isChecked()
        self.state.default_duration = self.newdur_spin.value()
        if hasattr(self, "preview"): self.preview.update()

    def _sync_style_widgets(self):
        i = self.theme_combo.findText(self.state.theme_name)
        self.theme_combo.setCurrentIndex(max(i, 0))
        self.handle_edit.setText(self.state.handle)
        if self.state.font_family:
            j = self.font_combo.findText(self.state.font_family)
            self.font_combo.setCurrentIndex(j if j > 0 else 0)
        self.bold_check.setChecked(self.state.bold)
        self.newdur_spin.setValue(self.state.default_duration)

    def _sync_music_widgets(self):
        self.music_file.setText(self.state.music_path)
        self.music_vol.setValue(self.state.music_volume)
        self.music_fadein.setValue(self.state.music_fadein)
        self.music_fadeout.setValue(self.state.music_fadeout)
        self.music_loop.setChecked(self.state.music_loop)
        self._update_music_note()

    # ----- background picker -----
    def _selected_scene(self) -> Scene | None:
        row = self.scene_list.currentRow()
        if 0 <= row < len(self.state.scenes): return self.state.scenes[row]
        return None

    def _bg_kind_changed(self, idx):
        sc = self._selected_scene()
        kinds = ["none", "image", "video"]
        kind = kinds[idx]
        if sc is None:
            self.statusBar().showMessage("Select a scene first.", 3000); return
        sc.bg_kind = kind
        if kind == "none":
            self.bg_path_label.setText("—")
        elif not sc.bg_path:
            self._bg_choose_file()
        self._update_bg_warn(); self._refresh_scenes(keep_row=True)
        if hasattr(self, "preview"): self.preview.update()

    def _bg_choose_file(self):
        sc = self._selected_scene()
        if sc is None:
            self.statusBar().showMessage("Select a scene first.", 3000); return
        kind = ["none", "image", "video"][self.bg_combo.currentIndex()]
        if kind == "none": return
        start = sc.bg_path or os.path.expanduser("~")
        if kind == "image":
            path, _ = QFileDialog.getOpenFileName(self, "Choose background image", start, IMG_FILTER)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Choose background video", start, VID_FILTER)
        if not path: 
            if not sc.bg_path:  # user cancelled without a file → revert to none
                sc.bg_kind = "none"; self.bg_combo.setCurrentIndex(0)
            return
        sc.bg_path = path
        self.bg_path_label.setText("🖼 " if kind == "image" else "🎞 " + os.path.basename(path))
        self._update_bg_warn(); self._refresh_scenes(keep_row=True)
        if hasattr(self, "preview"): self.preview.update()

    def _bg_apply_all(self):
        sc = self._selected_scene()
        if sc is None:
            self.statusBar().showMessage("Select a scene first.", 3000); return
        for s in self.state.scenes:
            s.bg_kind, s.bg_path = sc.bg_kind, sc.bg_path
        self._refresh_scenes()
        if hasattr(self, "preview"): self.preview.update()
        self.statusBar().showMessage("Background applied to all scenes ✔", 4000)

    def _update_bg_warn(self):
        sc = self._selected_scene()
        if sc and sc.bg_kind == "video" and not CV2_OK:
            self.bg_warn.setText("⚠️ Video backgrounds need OpenCV: pip install opencv-python numpy")
            self.bg_warn.show()
        else:
            self.bg_warn.hide()

    def _refresh_scenes(self, keep_row=False):
        row = self.scene_list.currentRow() if keep_row else -1
        self.scene_list.blockSignals(True)
        self.scene_list.clear()
        for i, s in enumerate(self.state.scenes):
            icon = {"image": "🖼 ", "video": "🎞 "}.get(s.bg_kind, "")
            self.scene_list.addItem(QListWidgetItem(f"{i + 1}.  {icon}{s.text[:56]}"))
        self.scene_list.blockSignals(False)
        if 0 <= row < len(self.state.scenes): self.scene_list.setCurrentRow(row)
        elif self.state.scenes: self.scene_list.setCurrentRow(0)
        if hasattr(self, "preview"): self.preview.update()
        self._update_export_info()

    def _on_scene_selected(self, row):
        if row < 0 or row >= len(self.state.scenes): return
        s = self.state.scenes[row]
        self.scene_edit.setPlainText(s.text)
        self.badge_edit.setText(s.badge)
        self.dur_spin.setValue(s.duration)
        self.bg_combo.blockSignals(True)
        self.bg_combo.setCurrentIndex({"none": 0, "image": 1, "video": 2}.get(s.bg_kind, 0))
        self.bg_combo.blockSignals(False)
        if s.bg_path:
            self.bg_path_label.setText(("🖼 " if s.bg_kind == "image" else "🎞 ") + os.path.basename(s.bg_path))
        else:
            self.bg_path_label.setText("—")
        self._update_bg_warn()

    def _pick(self, lst, attr):
        if not lst: return "Add lines in the Content tab ✍️"
        idx = random.randrange(len(lst))
        if len(lst) > 1:
            while idx == getattr(self, attr): idx = random.randrange(len(lst))
        setattr(self, attr, idx)
        return lst[idx]

    def _append_scene(self, s: Scene):
        self.state.scenes.append(s)
        self._refresh_scenes()
        self.scene_list.setCurrentRow(len(self.state.scenes) - 1)

    def _add_affirmation(self):
        self._append_scene(Scene(self._pick(self.state.affirmations, "_last_aff"),
                                 random.choice(BADGES), self.newdur_spin.value()))

    def _add_tip(self):
        self._append_scene(Scene(self._pick(self.state.tips, "_last_tip"),
                                 "RESPECT YOUR TIME", self.newdur_spin.value()))

    def _add_custom(self):
        txt = self.scene_edit.toPlainText().strip()
        if not txt:
            QMessageBox.information(self, "Custom scene", "Write your line in the editor first, then press ＋ Custom.")
            return
        self._append_scene(Scene(txt, "MY AFFIRMATION", self.newdur_spin.value()))

    def _random_short(self):
        affs = random.sample(self.state.affirmations, k=min(3, len(self.state.affirmations))) if self.state.affirmations else []
        tips = random.sample(self.state.tips, k=min(2, len(self.state.tips))) if self.state.tips else []
        items = [(t, random.choice(BADGES)) for t in affs] + [(t, "RESPECT YOUR TIME") for t in tips]
        random.shuffle(items)
        self.state.scenes = [Scene(t, b, round(random.uniform(3.0, 4.4), 1)) for t, b in items] or \
                            [Scene("Respect your time. ⏳", "RESPECT YOUR TIME", 3.5)]
        self._refresh_scenes(); self.preview.t = 0.0; self.preview.update()
        self.statusBar().showMessage("🎲 Fresh short loaded — hit Export when ready!", 5000)

    def _apply_scene(self):
        row = self.scene_list.currentRow()
        if row < 0 or row >= len(self.state.scenes):
            self.statusBar().showMessage("Select a scene first.", 3000); return
        s = self.state.scenes[row]
        s.text = self.scene_edit.toPlainText().strip() or s.text
        s.badge = self.badge_edit.text().strip()
        s.duration = self.dur_spin.value()
        self._refresh_scenes(keep_row=True)
        self.statusBar().showMessage("Scene updated ✔", 3000)

    def _move(self, delta):
        row = self.scene_list.currentRow()
        if row < 0: return
        new = row + delta
        if not (0 <= new < len(self.state.scenes)): return
        lst = self.state.scenes
        lst[row], lst[new] = lst[new], lst[row]
        self._refresh_scenes(); self.scene_list.setCurrentRow(new)

    def _delete_scene(self):
        row = self.scene_list.currentRow()
        if row >= 0:
            self.state.scenes.pop(row); self._refresh_scenes()

    def _clear_scenes(self):
        self.state.scenes.clear(); self._refresh_scenes()

    def _toggle_play(self):
        self.preview.playing = not self.preview.playing
        self.b_play.setText("⏸ Pause" if self.preview.playing else "▶ Play")

    def _jump(self, delta):
        scenes = self.state.scenes
        if not scenes: return
        starts = [0.0]
        for s in scenes[:-1]: starts.append(starts[-1] + s.duration)
        total = starts[-1] + scenes[-1].duration
        tt = self.preview.t % max(total, 0.1)
        cur = 0
        for i, s0 in enumerate(starts):
            if tt >= s0 - 1e-6: cur = i
        tgt = min(max(cur + delta, 0), len(scenes) - 1)
        self.preview.t = starts[tgt] + 0.001
        self.preview.playing = True
        self.b_play.setText("⏸ Pause")
        self.preview.update()

    def _update_time_label(self):
        scenes = self.state.scenes or [Scene("x", duration=3.5)]
        starts = [0.0]
        for s in scenes[:-1]: starts.append(starts[-1] + s.duration)
        total = starts[-1] + scenes[-1].duration
        tt = self.preview.t % max(total, 0.1)
        cur = 0
        for i, s0 in enumerate(starts):
            if tt >= s0 - 1e-6: cur = i
        self.time_label.setText(f"Scene {cur + 1}/{len(scenes)} • {tt:.1f}s / {total:.1f}s")

    # ---------- music actions ----------
    def _music_browse(self):
        start = self.state.music_path or os.path.join(os.path.expanduser("~"), "Music")
        path, _ = QFileDialog.getOpenFileName(self, "Choose background music", start, AUDIO_FILTER)
        if not path: return
        self.state.music_path = path
        self.music_file.setText(path)
        self._update_music_note(); self._update_export_info()

    def _music_clear(self):
        self._music_stop_preview()
        self.state.music_path = ""
        self.music_file.setText("")
        self._update_music_note(); self._update_export_info()

    def _update_music_note(self):
        has_music = bool(self.state.music_path)
        if has_music and not shutil.which("ffmpeg"):
            self.music_note.setText("⚠️ Mixing music into the MP4 requires FFmpeg on your PATH. "
                                    "Get it at ffmpeg.org — or the export will fail.")
        elif has_music and not os.path.exists(self.state.music_path):
            self.music_note.setText("⚠️ The selected music file no longer exists — pick it again.")
        else:
            self.music_note.setText("")

    def _music_vol_live(self, val):
        self.state.music_volume = val
        if self._music_out is not None:
            try: self._music_out.setVolume(val / 100.0)
            except Exception: pass

    def _music_toggle_preview(self):
        if not QTMM_OK:
            QMessageBox.information(self, "Preview unavailable",
                                    "Qt Multimedia isn't available in this PySide6 install.\n"
                                    "The music will still be mixed into your exported MP4.")
            return
        if self._music_playing:
            self._music_stop_preview(); return
        path = self.state.music_path
        if not path or not os.path.exists(path):
            QMessageBox.information(self, "No music", "Pick a music file first (🎵 Browse).")
            return
        if self._music_player is None:
            self._music_player = QMediaPlayer(self)
            self._music_out = QAudioOutput(self)
            self._music_player.setAudioOutput(self._music_out)
        self._music_out.setVolume(self.state.music_volume / 100.0)
        self._music_player.setSource(QUrl.fromLocalFile(path))
        try:
            self._music_player.setLoops(-1 if self.music_loop.isChecked() else 1)
        except Exception:
            pass
        self._music_player.play()
        self._music_playing = True
        self.b_music_prev.setText("⏹ Stop preview")

    def _music_stop_preview(self):
        if self._music_player is not None:
            try: self._music_player.stop()
            except Exception: pass
        self._music_playing = False
        self.b_music_prev.setText("▶ Preview music")

    # ---------- export actions ----------
    def _browse_out(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save MP4",
                    self.exp_file.text() or str(default_export_path()), "MP4 video (*.mp4)")
        if path: self.exp_file.setText(path)

    def _update_export_info(self):
        if not hasattr(self, "exp_info"): return
        total = sum(s.duration for s in self.state.scenes) if self.state.scenes else 0
        extras = []
        if self.state.music_path:
            extras.append("🎵 " + os.path.basename(self.state.music_path))
        nbg = sum(1 for s in self.state.scenes if s.bg_kind != "none")
        if nbg: extras.append(f"{nbg} bg")
        self.exp_info.setText(f"{len(self.state.scenes)} scenes • {total:.1f}s • vertical 9:16"
                              + (" • " + " • ".join(extras) if extras else ""))

    def _do_export(self):
        if not self.state.scenes:
            QMessageBox.warning(self, "No scenes", "Add at least one scene in the Studio tab."); return
        if self.worker and self.worker.isRunning(): return
        # sync music settings from widgets
        self.state.music_fadein = self.music_fadein.value()
        self.state.music_fadeout = self.music_fadeout.value()
        self.state.music_loop = self.music_loop.isChecked()
        if self.state.music_path and not os.path.exists(self.state.music_path):
            QMessageBox.warning(self, "Music missing", "The selected music file doesn't exist. Pick it again."); return
        path = self.exp_file.text().strip() or str(default_export_path())
        if not path.lower().endswith(".mp4"): path += ".mp4"
        if os.path.exists(path) and QMessageBox.question(
                self, "Overwrite?", f"{path}\nalready exists. Overwrite?") != QMessageBox.Yes:
            return
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.exp_file.setText(path)
        w, h = RESOLUTIONS[self.res_combo.currentText()]
        fps = FPS_OPTIONS[self.fps_combo.currentText()]
        self.exp_btn.setEnabled(False); self.cancel_btn.setEnabled(True); self.open_btn.setEnabled(False)
        self.exp_progress.setValue(0)
        self.worker = ExportWorker(copy_state(self.state), path, w, h, fps)
        self.worker.pct.connect(self.exp_progress.setValue)
        self.worker.phase.connect(lambda s: self.statusBar().showMessage(s))
        self.worker.finished_ok.connect(self._on_exp_done)
        self.worker.failed.connect(self._on_exp_failed)
        self.worker.start()
        self.statusBar().showMessage("⏳ Rendering your short… keep the app open.")

    def _cancel_export(self):
        if self.worker: self.worker.cancel()
        self.cancel_btn.setEnabled(False)

    def _on_exp_done(self, path):
        self.exp_btn.setEnabled(True); self.cancel_btn.setEnabled(False)
        self.open_btn.setEnabled(True); self.exp_path = path
        self.exp_progress.setValue(100)
        self.statusBar().showMessage("Export complete 🎉", 6000)
        music = " with music 🎵" if self.state.music_path else ""
        QMessageBox.information(self, "Export complete 🎉",
            f"Saved{music}:\n{path}\n\nNext steps:\n1. Open the YouTube app → Create → Short\n"
            "2. Pick this video, add music + #Shorts\n3. Publish and inspire someone today 💛")

    def _on_exp_failed(self, msg):
        self.exp_btn.setEnabled(True); self.cancel_btn.setEnabled(False)
        self.statusBar().showMessage("Export failed.", 5000)
        QMessageBox.critical(self, "Export failed", msg)

    def _open_folder(self):
        folder = os.path.dirname(self.exp_path) if self.exp_path else os.path.expanduser("~")
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _copy_caption(self):
        first = self.state.scenes[0].text if self.state.scenes else "Respect your time."
        cap = (f'“{first}”\n\nRespect your time. Protect your focus. Repeat daily. 🔁\n\n'
               "#shorts #affirmations #motivation #mindset #respectyourtime #discipline #growth")
        QApplication.clipboard().setText(cap)
        self.statusBar().showMessage("Caption copied 📋", 4000)

    def _gen_title(self):
        q = self.state.scenes[0].text if self.state.scenes else "Respect your time"
        t = random.choice(TITLE_TEMPLATES).format(q=q)
        self.title_label.setText(t)
        QApplication.clipboard().setText(t)
        self.statusBar().showMessage("Title copied 🎯", 4000)

    # ---------- content ----------
    def _save_content(self):
        self.state.affirmations = [l.strip() for l in self.aff_edit.toPlainText().splitlines() if l.strip()]
        self.state.tips = [l.strip() for l in self.tip_edit.toPlainText().splitlines() if l.strip()]
        self._save_store()
        self.statusBar().showMessage(
            f"Saved {len(self.state.affirmations)} affirmations & {len(self.state.tips)} time lines 💾", 5000)

    def _restore_defaults(self):
        self.aff_edit.setPlainText("\n".join(DEFAULT_AFFIRMATIONS))
        self.tip_edit.setPlainText("\n".join(DEFAULT_TIME_TIPS))

    def _new_status_tip(self):
        self.statusBar().showMessage("💡 " + random.choice(self.state.tips))

    # ---------- shutdown ----------
    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            if QMessageBox.question(self, "Export in progress",
                                    "An export is running. Quit anyway?") != QMessageBox.Yes:
                e.ignore(); return
            self.worker.cancel(); self.worker.wait(3000)
        self._music_stop_preview()
        BG_CACHE.release_all()
        self._save_store()
        e.accept()

# ----------------------------- stylesheet & main -----------------------------
STYLE = """
QWidget { background:#14141b; color:#e8e8f0; font-size:14px; }
QTabWidget::pane { border:1px solid #2a2a35; border-radius:8px; }
QTabBar::tab { padding:10px 18px; background:#1b1b26; border-top-left-radius:8px; border-top-right-radius:8px; }
QTabBar::tab:selected { background:#26263a; color:#ffd166; }
QPushButton { background:#2b2b3d; border:1px solid #3a3a52; border-radius:8px; padding:8px 14px; }
QPushButton:hover { background:#35354d; }
QPushButton:disabled { color:#77778a; }
QPushButton#accent { background:#ffd166; color:#1c1400; font-weight:700; border:1px solid #e6b84c; }
QPushButton#accent:hover { background:#ffdf85; }
QPlainTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background:#1e1e2a; border:1px solid #33334a; border-radius:6px; padding:6px; }
QSlider::groove:horizontal { height:6px; background:#1e1e2a; border-radius:3px; }
QSlider::handle:horizontal { width:14px; margin:-5px 0; border-radius:7px; background:#ffd166; }
QListWidget { background:#1a1a24; border:1px solid #30304a; border-radius:6px; }
QListWidget::item { padding:6px; }
QListWidget::item:selected { background:#33406b; color:#fff; }
QProgressBar { border:1px solid #33334a; border-radius:6px; height:18px; background:#1e1e2a; }
QProgressBar::chunk { background:#ffd166; border-radius:5px; }
QGroupBox { border:1px solid #2e2e44; border-radius:8px; margin-top:12px; font-weight:600; }
QGroupBox::title { subcontrol-origin: margin; left:12px; padding:0 4px; color:#ffd166; }
QFrame#previewCard { background:#0b0b11; border:1px solid #262640; border-radius:14px; }
QLabel#muted { color:#9a9ab0; }
QLabel#quoteLabel { color:#e8d9a0; font-style:italic; font-size:15px; }
QLabel#warn { color:#ff8f8f; }
QLabel#bigTime { font-size:64px; font-weight:800; letter-spacing:2px; }
QLabel#phaseLabel { font-size:16px; color:#9a9ab0; }
QLabel#popupTitle { font-size:22px; font-weight:800; color:#ffd166; }
QLabel#popupMsg { font-size:16px; }
QDialog { background:#171722; }
QStatusBar { background:#101018; color:#9a9ab0; }
"""

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""樱响（SakuraSound）桌面版：Qt 原生程序窗口（替代网页端）。

双击运行后是一个像 QQ 那样的独立程序窗口：标题栏、任务栏图标、
关闭后缩到托盘（右键托盘图标可退出），不再需要打开浏览器。

音频逻辑复用 web/server.py 的 AudioEngine（与网页版同一套核心）：
所有 pycaw 调用只发生在音频线程，界面线程每 100ms 读一次快照刷新。
响度条另有 60fps 插值动画：显示值向目标值缓动，看起来是 60 帧的
平滑动画，而不是 100ms 一跳的数据。本程序只做响度均衡：不做均衡器、不碰音频采样、不依赖任何音频驱动插件。
"""

import hashlib
import json
import random
import math
import os
import sys
import time
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "web"))

from PySide6.QtCore import QEvent, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QStyle,
    QStyleOptionSlider,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from server import AudioEngine

# ---------------------------------------------------------------- 外观

BG = "#F2EEF9"
CARD = "#FFFFFF"
CARD2 = "#FFFFFF"
BORDER = "#D9D2EC"
TEXT = "#2E2A3F"
MUTED = "#5B5B6E"
ACCENT = "#5B5BF0"
ACCENT2 = "#8B7CFF"
ACCENT_DEEP = "#4A45D0"
MARKER = "#FF5C8A"
DANGER = "#E11D48"

QSS = """
QWidget { background-color: %(bg)s; color: %(text)s; font-size: 16px;
          font-family: "ZCOOL KuaiLe", "PingFang SC", "Yuanti SC", "Hiragino Sans GB",
                       "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif; }
QSlider, QCheckBox { background: transparent; }
QFrame.card { background-color: rgba(255, 255, 255, 215); border: 1px solid rgba(255, 255, 255, 220); border-radius: 20px; }
QLabel { background: transparent; }
QLabel.apptitle { font-size: 30px; font-weight: bold; }
QLabel.subtitle { color: %(muted)s; font-size: 14px; }
QLabel.section { font-size: 15px; font-weight: bold; }
QLabel.muted { color: %(muted)s; font-size: 14px; }
QLabel.bigpct { font-size: 28px; font-weight: bold; }
QLabel.status { color: %(muted)s; font-size: 14px; }
QLabel.status-error { color: %(danger)s; font-size: 14px; }
QLabel.modepill { font-size: 14px; border-radius: 11px; padding: 6px 14px; }
QLabel.mode-real { background-color: #EDE9FE; color: #5B21B6; border: 1px solid #C4B5FD; }
QLabel.mode-mock { background-color: #E5E7EB; color: #4B5563; }
QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255, 170, 200, 195), stop:1 rgba(244, 114, 182, 195)); border: 1px solid rgba(255, 255, 255, 230); border-radius: 16px;
              padding: 8px 18px; color: #3B2F5E; }
QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(244, 114, 182, 210), stop:1 rgba(236, 72, 153, 210)); }
QPushButton:pressed { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(236, 72, 153, 220), stop:1 rgba(219, 39, 119, 220)); }
QPushButton[primary="true"] { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(236, 72, 153, 205), stop:1 rgba(219, 39, 119, 205)); border: 1px solid rgba(255, 255, 255, 230); color: #FFFFFF; font-weight: bold; }
QPushButton[primary="true"]:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(219, 39, 119, 215), stop:1 rgba(190, 24, 93, 215)); }
QPushButton[primary="true"]:pressed { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(190, 24, 93, 225), stop:1 rgba(157, 23, 77, 225)); }
QComboBox { background-color: %(card2)s; border: 1px solid %(border)s; border-radius: 10px;
            padding: 7px 36px 7px 10px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right;
            width: 28px; border: none; background: transparent; }
QComboBox::down-arrow { image: url(sakura_icon.png); width: 18px; height: 18px; }
QComboBox QAbstractItemView { background-color: %(card2)s; selection-background-color: %(accent)s; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px;
                       border: 1px solid %(border)s; background-color: %(card2)s; }
QCheckBox::indicator:checked { background-color: %(accent)s; border-color: %(accent)s; }
QSlider::groove:horizontal { height: 4px; background: %(border)s; border-radius: 2px; }
QSlider::sub-page:horizontal { background: %(accent)s; border-radius: 2px; }
QSlider::handle:horizontal { width: 28px; height: 28px; margin: -12px 0;
    image: url(sakura_icon.png); background: transparent; border: none; }
QSpinBox { background-color: %(card2)s; border: 1px solid %(border)s; border-radius: 8px;
           padding: 4px 6px; }
QDoubleSpinBox { background-color: %(card2)s; border: 1px solid %(border)s; border-radius: 8px;
           padding: 4px 6px; }
QLineEdit { background-color: %(card2)s; border: 1px solid %(border)s; border-radius: 8px;
           padding: 6px 8px; color: %(text)s; }
QTabWidget::pane { border: none; background: transparent; }
QTabBar { background: transparent; }
QStackedWidget { background: transparent; }
QTabBar::tab { background: transparent; color: %(muted)s; padding: 10px 18px; border: none; }
QTabBar::tab:selected { color: %(text)s; border-bottom: 2px solid %(accent)s; }
QScrollArea { border: none; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 0; }
QScrollBar::handle:vertical { background: %(border)s; border-radius: 4px; min-height: 40px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QPushButton.compact { padding: 8px 12px; font-size: 15px; }
QSlider[bipolar="true"]::sub-page:horizontal { background: %(border)s; }
""" % dict(bg=BG, text=TEXT, border=BORDER, muted=MUTED, danger=DANGER,
           card2=CARD2, accent=ACCENT, accent2=ACCENT2)


def apply_glass_opacity(pct):
    """毛玻璃透明度：卡片＋按钮一起调，往右越不透明（默认 84% = 现在的样子）。

    卡片白底 alpha = pct% × 255；按钮粉渐变各档 alpha 按 pct/84 等比缩放
    （84% 时正好是现在的值，不动）。白边框不跟着变，玻璃边框要一直看得见。
    直接重设应用样式表，卡片和按钮立刻变，不用重启。"""
    try:
        pct = max(50, min(100, int(pct)))
    except Exception:
        pct = 84
    alpha = int(round(pct / 100.0 * 255))
    factor = pct / 84.0
    qss = QSS
    qss = qss.replace("rgba(255, 255, 255, 215)",
                      "rgba(255, 255, 255, %d)" % alpha)
    qss = qss.replace("rgba(255, 255, 255, 220)",
                      "rgba(255, 255, 255, %d)" % min(255, alpha + 5))
    import re as _re
    _btn = [(255, 170, 200, 195), (244, 114, 182, 195), (244, 114, 182, 210),
            (236, 72, 153, 210), (236, 72, 153, 220), (219, 39, 119, 220),
            (236, 72, 153, 205), (219, 39, 119, 205), (219, 39, 119, 215),
            (190, 24, 93, 215), (190, 24, 93, 225), (157, 23, 77, 225)]
    def _scale(m):
        r, g, b, a = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        if (r, g, b, a) in _btn:
            return "rgba(%d, %d, %d, %d)" % (r, g, b, min(255, int(round(a * factor))))
        return m.group(0)
    qss = _re.sub(r"rgba\((\d+), (\d+), (\d+), (\d+)\)", _scale, qss)
    try:
        from PySide6.QtWidgets import QApplication as _QA
        _app = _QA.instance()
        if _app is not None:
            _app.setStyleSheet(qss)
    except Exception:
        pass
    return qss


def make_icon():
    """托盘/窗口图标：优先用正式樱响 sakura.ico（多尺寸），找不到时回落到
    手绘 64x64 图标（紫色圆角底 + 三根白色音量条）。"""
    _ico = os.path.join(HERE, "sakura.ico")
    if os.path.isfile(_ico):
        return QIcon(_ico)
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(ACCENT))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 12, 12)
    p.setBrush(QColor("white"))
    for i, h in enumerate((20, 30, 40)):
        x = 14 + i * 14
        p.drawRoundedRect(x, 52 - h, 8, h, 3, 3)
    p.end()
    return QIcon(pix)


AVATAR_COLORS = ["#7C6CFF", "#38BDF8", "#A78BFA", "#FB923C", "#F472B6", "#2DD4BF", "#FACC15"]


def avatar_color(name):
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()
    return AVATAR_COLORS[int(digest[:2], 16) % len(AVATAR_COLORS)]


# ---------------------------------------------------------------- 背景主题

THEME_PRESETS = {
    "玻璃粉紫": {"top": "#EADFFB", "bottom": "#FDEDF3", "glow": "#C4B5FD"},
    "玻璃薄荷": {"top": "#DFF7EC", "bottom": "#FDF6E3", "glow": "#6EE7B7"},
    "深海": {"top": "#1B2A3D", "bottom": "#0E1116", "glow": "#14B8A6"},
    "紫夜": {"top": "#2A1B4A", "bottom": "#0E1116", "glow": "#A78BFA"},
    "墨绿": {"top": "#14352A", "bottom": "#0E1116", "glow": "#22C55E"},
    "暖阳": {"top": "#3D2A17", "bottom": "#0E1116", "glow": "#FB923C"},
    "纯色": {"top": "#0E1116", "bottom": "#0E1116", "glow": None},
    "樱花树": {"top": "#8FB8E8", "bottom": "#FDEDF3", "glow": "#C4B5FD"},
}
DEFAULT_THEME = {"type": "gradient", "preset": "玻璃粉紫", "image": "", "dim": 0.05, "sakura": True, "sakura_tree": True, "glass": 84,
                 "fit": "cover", "anchor": [0.5, 0.5], "crop": None}


def theme_path():
    # 放在程序所在目录：安装版在 %LOCALAPPDATA%\SakuraSound，便携版在解压目录，都可写
    return os.path.join(HERE, "volrider-theme.json")


def load_theme():
    try:
        with open(theme_path(), encoding="utf-8") as f:
            data = json.load(f)
        theme = dict(DEFAULT_THEME)
        theme.update(data)
        return theme
    except Exception:
        return dict(DEFAULT_THEME)


def save_theme(theme):
    try:
        with open(theme_path(), "w", encoding="utf-8") as f:
            json.dump(theme, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # 目录只读时仅本会话生效，不报错打扰用户


# 持久化设置（volrider-settings.json）：只记响度相关的两项。
#   target：基准上限（0.5~0.9）；enabled：自动均衡开关。
#   主题文件 volrider-theme.json：fit / anchor / crop / dim / preset / type / image
# 2026-10-25 起 PEQ / Equalizer APO 已整块删掉：旧设置文件里若还留着
# apo_enabled / apo_path，保存响度设置时一并清掉，不再读它们。
def settings_path():
    return os.path.join(HERE, "volrider-settings.json")


def load_settings():
    try:
        with open(settings_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(data):
    try:
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class BackgroundWidget(QWidget):
    """窗口底层：画渐变/微光/自定义图片 + 黑色遮罩，内容卡片半透明地浮在上面。"""

    def __init__(self, theme):
        super().__init__()
        self.theme = dict(theme)
        # 樱花飘落：每片花瓣速度、大小、摇摆、转速、透明度都不同，落到底部
        # 回到顶部重生，无限循环；花瓣画在背景层，卡片在它上面，所以花瓣
        # 不会盖住文字，只在空处和半透明白卡片后若隐若现。
        self._sakura = bool(theme.get("sakura", True))
        self._petals = []
        self._sakura_t0 = time.time()
        self._sakura_last = self._sakura_t0
        self._sakura_timer = QTimer(self)
        self._sakura_timer.setInterval(40)
        self._sakura_timer.timeout.connect(self._advance_petals)
        if self._sakura:
            self._sakura_timer.start()
        self._pixmap = None
        self._cache_key = None
        self._source_pixmap = None
        self._source_key = None
        self._cropped_pixmap = None
        self._cropped_key = None
        self._static_cache = None
        self._static_key = None

    def set_theme(self, theme):
        self.theme = dict(theme)
        self._sakura = bool(theme.get("sakura", True))
        if self._sakura:
            if not self._sakura_timer.isActive():
                self._sakura_last = time.time()
                self._sakura_timer.start()
        else:
            self._sakura_timer.stop()
        self.update()

    def _tree_path(self):
        # 打包后 sakura-tree-cool.png 跟 qt_app.py 同目录；源码树里同名文件也在同目录。
        cand = os.path.join(HERE, "sakura-tree-cool.png")
        return cand if os.path.isfile(cand) else ""

    def _is_tree_mode(self):
        return self.theme.get("type") == "tree" and bool(self.theme.get("sakura_tree", True))

    def _tree_pixmap(self):
        path = self._tree_path()
        if not path:
            return None
        if getattr(self, "_tree_key", None) == path and getattr(self, "_tree_pix", None) is not None:
            return self._tree_pix
        pix = QPixmap(path)
        if pix.isNull():
            return None
        if pix.width() > 1920 or pix.height() > 1920:
            pix = pix.scaled(1920, 1920, Qt.KeepAspectRatio, Qt.FastTransformation)
        self._tree_pix = pix
        self._tree_key = path
        return pix

    def set_sakura(self, enabled):
        self._sakura = bool(enabled)
        if self._sakura:
            self._sakura_last = time.time()
            if not self._sakura_timer.isActive():
                self._sakura_timer.start()
        else:
            self._sakura_timer.stop()
        self.update()

    def _new_petal(self, top=False):
        w = max(1, self.width())
        h = max(1, self.height())
        if top and self._is_tree_mode():
            # 樱花树模式：从树冠起落（树冠在画面上部居中），不是全宽顶部均匀落下。
            _x = random.uniform(0.12 * w, 0.88 * w)
            _y = random.uniform(-20, 0.30 * h)
        elif top:
            # 自定义壁纸模式：从顶部均匀落下。
            _x = random.uniform(0, w)
            _y = random.uniform(-40, -10)
        else:
            _x = random.uniform(0, w)
            _y = random.uniform(-20, h)
        return {
            "x": _x,
            "y": _y,
            "size": random.uniform(9, 18),
            "speed": random.uniform(22, 55),       # px/秒：快慢不一
            "sway": random.uniform(8, 28),         # 左右摇摆幅度
            "sway_speed": random.uniform(0.6, 1.6),
            "phase": random.uniform(0, 6.28),
            "rot": random.uniform(0, 360),
            "rot_speed": random.uniform(-60, 60),  # 度/秒：正反转都有
            "alpha": random.uniform(150, 220),
            "color": random.choice(["#FFB7D5", "#FFC9DC", "#FFD1E3", "#F9A8D4"]),
        }

    def _advance_petals(self):
        if not self._sakura:
            return
        now = time.time()
        dt = min(0.1, max(0.0, now - self._sakura_last))
        self._sakura_last = now
        w, h = self.width(), self.height()
        if not self._petals:
            self._petals = [self._new_petal() for _ in range(36)]
        for pt in self._petals:
            pt["y"] += pt["speed"] * dt
            pt["rot"] += pt["rot_speed"] * dt
            if pt["y"] > h + 20:
                self._petals[self._petals.index(pt)] = self._new_petal(top=True)
        self.update()

    def _draw_petals(self, p):
        if not self._sakura:
            return
        if not self._petals:
            self._petals = [self._new_petal() for _ in range(36)]
        now = time.time()
        elapsed = now - self._sakura_t0
        w, h = self.width(), self.height()
        p.setRenderHint(QPainter.Antialiasing)
        for pt in self._petals:
            x = pt["x"] + pt["sway"] * math.sin(elapsed * pt["sway_speed"] + pt["phase"])
            y = pt["y"]
            alpha = pt["alpha"]
            if y > h - 60:  # 落到底部前渐隐，不会突然消失
                alpha *= max(0.0, (h + 20 - y) / 80.0)
            if y < -10:  # 刚从顶部重生时渐显
                alpha *= max(0.0, min(1.0, (y + 20) / 20.0))
            if alpha <= 5:
                continue
            s = pt["size"]
            p.save()
            p.translate(x, y)
            p.rotate(pt["rot"])
            col = QColor(pt["color"])
            col.setAlpha(int(alpha))
            p.setBrush(col)
            p.setPen(Qt.NoPen)
            # 花瓣形：上下尖、中间鼓，不是正圆，看起来才像花瓣不是圆点
            path = QPainterPath()
            path.moveTo(0, -s / 2)
            path.cubicTo(s / 2, -s / 4, s / 2, s / 4, 0, s / 2)
            path.cubicTo(-s / 2, s / 4, -s / 2, -s / 4, 0, -s / 2)
            p.drawPath(path)
            p.restore()
        self._pixmap = None
        self._cache_key = None
        self._source_pixmap = None
        self._source_key = None
        self._cropped_pixmap = None
        self._cropped_key = None
        self.update()

    def _get_cropped(self):
        """原图 + 裁切只算一次，绝不在 paintEvent 里重复做。

        以前的卡顿根因就在这里：paintEvent 每帧都 QPixmap(path) 从硬盘
        重新解码原图、再 pix.copy() 裁一刀，而响度条 60fps、刷新 100ms
        都在不断触发重绘——大图一换，解码就把 UI 拖卡了。
        现在原图只在主题切换时加载一次（超 1920px 的大图先一次性缩到
        1920 以内（窗口才 760 宽，1920 足够 2 倍高清屏，内存和缩放都省）），裁切也只切一次，paintEvent 只拿
        缓存的裁切图去缩放（缩放结果本身也按窗口尺寸缓存）。
        """
        t = self.theme
        path = t.get("image", "")
        crop = t.get("crop")
        key = (path, tuple(crop) if crop else None)
        if self._cropped_key == key and self._cropped_pixmap is not None:
            return self._cropped_pixmap
        if self._source_key != path or self._source_pixmap is None:
            self._source_pixmap = None
            self._source_key = path
            if path and os.path.isfile(path):
                src = QPixmap(path)
                if not src.isNull():
                    if src.width() > 1920 or src.height() > 1920:
                        src = src.scaled(1920, 1920, Qt.KeepAspectRatio,
                                         Qt.FastTransformation)
                    self._source_pixmap = src
        pix = self._source_pixmap
        if pix is not None and not pix.isNull() and crop:
            try:
                fx, fy, fw, fh = float(crop[0]), float(crop[1]), float(crop[2]), float(crop[3])
                x = max(0, int(fx * pix.width()))
                y = max(0, int(fy * pix.height()))
                cw = max(1, min(pix.width() - x, int(fw * pix.width())))
                ch = max(1, min(pix.height() - y, int(fh * pix.height())))
                pix = pix.copy(x, y, cw, ch)
            except Exception:
                pass
        self._cropped_pixmap = pix
        self._cropped_key = key
        return pix

    def _paint_static(self, p, ww, wh):
        """只画静态背景（渐变/图片/遮罩/微光），不画樱花。

        以前每帧樱花动画都把整张背景重画一遍：渐变填充 + 微光径向 +
        遮罩填充 + 图片 + 顶部渐变，5 次全窗口操作 × 25fps，大图就卡。
        现在静态背景只画一次、缓存成整窗 pixmap，每帧只贴缓存图 +
        画花瓣，1 次全窗口操作 + 几十个小花瓣，大图也不卡。
        """
        # ww/wh 始终是窗口尺寸（缩放目标、缓存 key、遮罩填充一律用它）；
        # cw/ch 只表示裁切出来的那块在原图里的像素尺寸，绝不能复写窗口尺寸
        # （之前 w/h 被裁切复写后，缩放目标就变成了裁切块本身，小图裁切会留空边）。
        ww, wh = self.width(), self.height()
        t = self.theme
        if t.get("type") == "image":
            pix = self._get_cropped()
            path = t.get("image", "")
            crop = t.get("crop")
            if pix is not None and not pix.isNull():
                fit = t.get("fit", "cover")
                try:
                    ax, ay = float(t.get("anchor", [0.5, 0.5])[0]), float(t.get("anchor", [0.5, 0.5])[1])
                except Exception:
                    ax, ay = 0.5, 0.5
                key = (ww, wh, fit, ax, ay, path, tuple(crop) if crop else None)
                if self._cache_key != key or self._pixmap is None:
                    if fit == "stretch":
                        self._pixmap = pix.scaled(ww, wh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                    elif fit == "contain":
                        self._pixmap = pix.scaled(ww, wh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    else:
                        self._pixmap = pix.scaled(ww, wh, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                    self._cache_key = key
                if fit == "contain":
                    # 先铺预设渐变当底，再把整图居中贴上，四周留渐变边
                    preset = THEME_PRESETS.get(t.get("preset", "玻璃粉紫"), THEME_PRESETS["玻璃粉紫"])
                    grad = QLinearGradient(0, 0, 0, wh)
                    grad.setColorAt(0, QColor(preset["top"]))
                    grad.setColorAt(1, QColor(preset["bottom"]))
                    p.fillRect(0, 0, ww, wh, grad)
                    x = (ww - self._pixmap.width()) // 2
                    y = (wh - self._pixmap.height()) // 2
                    p.drawPixmap(x, y, self._pixmap)
                elif fit == "stretch":
                    p.drawPixmap(0, 0, self._pixmap)
                else:
                    x = int((self._pixmap.width() - ww) * ax)
                    y = int((self._pixmap.height() - wh) * ay)
                    p.drawPixmap(0, 0, self._pixmap, x, y, ww, wh)
            else:
                p.fillRect(0, 0, ww, wh, QColor(BG))
            # 自定义图时顶部压一层浅色渐变：壁纸从页签行透出来，
            # 但页签文字和标题要压得住；预设渐变本身顶部已够暗，不加这一层。
            scrim_h = 140
            scrim = QLinearGradient(0, 0, 0, scrim_h)
            scrim.setColorAt(0, QColor(255, 255, 255, 120))
            scrim.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillRect(0, 0, ww, scrim_h, scrim)
        elif t.get("type") == "tree" and self._is_tree_mode():
            pix = self._tree_pixmap()
            if pix is not None and not pix.isNull():
                scaled = pix.scaled(ww, wh, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                x = (scaled.width() - ww) // 2
                y = (scaled.height() - wh) // 2
                p.drawPixmap(0, 0, scaled, x, y, ww, wh)
            else:
                preset = THEME_PRESETS.get("玻璃粉紫", THEME_PRESETS["玻璃粉紫"])
                grad = QLinearGradient(0, 0, 0, wh)
                grad.setColorAt(0, QColor(preset["top"]))
                grad.setColorAt(1, QColor(preset["bottom"]))
                p.fillRect(0, 0, ww, wh, grad)
        else:
            preset = THEME_PRESETS.get(t.get("preset", "玻璃粉紫"), THEME_PRESETS["玻璃粉紫"])
            grad = QLinearGradient(0, 0, 0, wh)
            grad.setColorAt(0, QColor(preset["top"]))
            grad.setColorAt(1, QColor(preset["bottom"]))
            p.fillRect(0, 0, ww, wh, grad)
            glow = preset.get("glow")
            if glow:
                rg = QRadialGradient(ww / 2, -wh * 0.25, wh * 0.9)
                c = QColor(glow)
                c.setAlpha(70)
                rg.setColorAt(0, c)
                c2 = QColor(glow)
                c2.setAlpha(0)
                rg.setColorAt(1, c2)
                p.fillRect(0, 0, ww, wh, rg)
        dim = float(t.get("dim", 0.05))
        if dim > 0:
            # 浅色主题：遮罩改白色提亮（原来黑色是给深色主题压暗底用的，浅色下反了）
            p.fillRect(0, 0, ww, wh, QColor(255, 255, 255, int(255 * max(0.0, min(0.8, dim)))))

    def paintEvent(self, _event):
        ww, wh = self.width(), self.height()
        if ww <= 0 or wh <= 0:
            return
        tt = self.theme
        try:
            _crop = tuple(tt.get("crop")) if tt.get("crop") else None
        except Exception:
            _crop = None
        try:
            _anchor = tuple(tt.get("anchor")) if isinstance(tt.get("anchor"), (list, tuple)) else tt.get("anchor")
        except Exception:
            _anchor = None
        key = (ww, wh, tt.get("type"), tt.get("preset"), tt.get("image"), _crop,
               tt.get("fit"), _anchor, float(tt.get("dim", 0.05)),
               bool(tt.get("sakura_tree", True)))
        if (self._static_key != key or self._static_cache is None
                or self._static_cache.width() != ww or self._static_cache.height() != wh):
            cache = QPixmap(ww, wh)
            cp = QPainter(cache)
            self._paint_static(cp, ww, wh)
            cp.end()
            self._static_cache = cache
            self._static_key = key
        p = QPainter(self)
        p.drawPixmap(0, 0, self._static_cache)
        self._draw_petals(p)
        p.end()


# ---------------------------------------------------------------- 可视化裁切器

class CropEditor(QWidget):
    """图上拖框裁切：框内是保留部分，框外压暗；拖动时通过回调实时通知预览。

    操作：拖框内移动；拖角/边缩放；在图上空白处按下拖动可拉出新框。
    裁切框以图片比例坐标（0~1）保存，换窗口大小也不变。
    """

    def __init__(self, pixmap, crop=None, on_change=None, aspect=None):
        super().__init__()
        self.pixmap = pixmap
        self.on_change = on_change
        if crop:
            self.fx, self.fy, self.fw, self.fh = (float(crop[0]), float(crop[1]),
                                                 float(crop[2]), float(crop[3]))
        else:
            self.fx, self.fy, self.fw, self.fh = 0.0, 0.0, 1.0, 1.0
        # 锁定框的比例 = 窗口比例：框住的那块确定后正好铺满窗口，不二次裁切、不留黑边
        self._ratio = None
        if aspect:
            self._ratio = float(aspect) * pixmap.height() / pixmap.width()
            self._fix_aspect()
            self._clamp()
        self._drag = None
        self.setMinimumSize(480, 360)
        self.setMouseTracking(True)

    def _fix_aspect(self, anchor_x="center", anchor_y="center"):
        """按窗口比例修正框的尺寸，锚点（拖动时不动的那条边/角）保持原位。"""
        if not self._ratio:
            return
        R = self._ratio
        if anchor_x == "left":
            ax = self.fx
        elif anchor_x == "right":
            ax = self.fx + self.fw
        else:
            ax = self.fx + self.fw / 2
        if anchor_y == "top":
            ay = self.fy
        elif anchor_y == "bottom":
            ay = self.fy + self.fh
        else:
            ay = self.fy + self.fh / 2
        if self.fw / max(self.fh, 1e-6) > R:
            self.fw = self.fh * R
        else:
            self.fh = self.fw / R
        if self.fw > 1.0:
            self.fw = 1.0
            self.fh = 1.0 / R
        if self.fh > 1.0:
            self.fh = 1.0
            self.fw = R
        if anchor_x == "left":
            self.fx = ax
        elif anchor_x == "right":
            self.fx = ax - self.fw
        else:
            self.fx = ax - self.fw / 2
        if anchor_y == "top":
            self.fy = ay
        elif anchor_y == "bottom":
            self.fy = ay - self.fh
        else:
            self.fy = ay - self.fh / 2

    def _display_rect(self):
        iw, ih = self.pixmap.width(), self.pixmap.height()
        w, h = self.width(), self.height()
        s = min(w / iw, h / ih)
        dw, dh = int(iw * s), int(ih * s)
        return (w - dw) // 2, (h - dh) // 2, dw, dh

    def _crop_rect(self):
        ox, oy, dw, dh = self._display_rect()
        return (ox + self.fx * dw, oy + self.fy * dh, self.fw * dw, self.fh * dh)

    def _hit(self, pos):
        x, y, w, h = self._crop_rect()
        tol = 10
        cx, cy = pos.x(), pos.y()
        for hx, hy, mode in ((x, y, "nw"), (x + w, y, "ne"),
                             (x, y + h, "sw"), (x + w, y + h, "se")):
            if abs(cx - hx) <= tol and abs(cy - hy) <= tol:
                return mode
        if abs(cy - y) <= tol and x <= cx <= x + w:
            return "n"
        if abs(cy - (y + h)) <= tol and x <= cx <= x + w:
            return "s"
        if abs(cx - x) <= tol and y <= cy <= y + h:
            return "w"
        if abs(cx - (x + w)) <= tol and y <= cy <= y + h:
            return "e"
        if x <= cx <= x + w and y <= cy <= y + h:
            return "move"
        ox, oy, dw, dh = self._display_rect()
        if ox <= cx <= ox + dw and oy <= cy <= oy + dh:
            return "new"
        return None

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        mode = self._hit(event.position())
        if mode is None:
            return
        self._drag = (mode, event.position(), (self.fx, self.fy, self.fw, self.fh))

    def mouseMoveEvent(self, event):
        if self._drag is None:
            cursors = {"nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor,
                       "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor,
                       "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
                       "w": Qt.SizeHorCursor, "e": Qt.SizeHorCursor,
                       "move": Qt.SizeAllCursor, "new": Qt.CrossCursor}
            self.setCursor(cursors.get(self._hit(event.position()), Qt.ArrowCursor))
            return
        mode, start, (fx0, fy0, fw0, fh0) = self._drag
        ox, oy, dw, dh = self._display_rect()
        dx = (event.position().x() - start.x()) / dw
        dy = (event.position().y() - start.y()) / dh
        if mode == "new":
            x0 = (start.x() - ox) / dw
            y0 = (start.y() - oy) / dh
            x1 = (event.position().x() - ox) / dw
            y1 = (event.position().y() - oy) / dh
            self.fx = max(0.0, min(x0, x1))
            self.fw = min(1.0 - self.fx, abs(x1 - x0))
            self.fy = max(0.0, min(y0, y1))
            self.fh = min(1.0 - self.fy, abs(y1 - y0))
        elif mode == "move":
            self.fx = max(0.0, min(1.0 - fw0, fx0 + dx))
            self.fy = max(0.0, min(1.0 - fh0, fy0 + dy))
        else:
            if "w" in mode:
                nx = min(fx0 + fw0 - 0.05, fx0 + dx)
                nx = max(0.0, nx)
                self.fw = fx0 + fw0 - nx
                self.fx = nx
            if "e" in mode:
                self.fw = max(0.05, min(1.0 - fx0, fw0 + dx))
            if "n" in mode:
                ny = min(fy0 + fh0 - 0.05, fy0 + dy)
                ny = max(0.0, ny)
                self.fh = fy0 + fh0 - ny
                self.fy = ny
            if "s" in mode:
                self.fh = max(0.05, min(1.0 - fy0, fh0 + dy))
        if mode != "move":
            anchors = {"new": ("center", "center"),
                       "nw": ("right", "bottom"), "ne": ("left", "bottom"),
                       "sw": ("right", "top"), "se": ("left", "top"),
                       "n": ("center", "bottom"), "s": ("center", "top"),
                       "w": ("right", "center"), "e": ("left", "center")}
            ax, ay = anchors.get(mode, ("center", "center"))
            self._fix_aspect(ax, ay)
        self._clamp()
        self.update()
        if self.on_change:
            self.on_change(self.crop())

    def mouseReleaseEvent(self, _event):
        self._drag = None

    def _clamp(self):
        self.fw = max(0.05, min(1.0, self.fw))
        self.fh = max(0.05, min(1.0, self.fh))
        self.fx = max(0.0, min(1.0 - self.fw, self.fx))
        self.fy = max(0.0, min(1.0 - self.fh, self.fy))

    def crop(self):
        return [self.fx, self.fy, self.fw, self.fh]

    def set_crop(self, crop):
        self.fx, self.fy, self.fw, self.fh = (float(crop[0]), float(crop[1]),
                                             float(crop[2]), float(crop[3]))
        self._fix_aspect()
        self._clamp()
        self.update()
        if self.on_change:
            self.on_change(self.crop())

    def paintEvent(self, _event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(10, 10, 12))
        ox, oy, dw, dh = self._display_rect()
        p.drawPixmap(ox, oy, dw, dh, self.pixmap)
        x, y, cw, ch = self._crop_rect()
        p.setBrush(QColor(0, 0, 0, 140))
        p.setPen(Qt.NoPen)
        p.drawRect(ox, oy, dw, int(y - oy))
        p.drawRect(ox, int(y + ch), dw, int(oy + dh - (y + ch)))
        p.drawRect(ox, int(y), int(x - ox), int(ch))
        p.drawRect(int(x + cw), int(y), int(ox + dw - (x + cw)), int(ch))
        p.setPen(QPen(QColor(255, 255, 255, 90), 1))
        for i in (1, 2):
            p.drawLine(int(x + cw * i / 3), int(y), int(x + cw * i / 3), int(y + ch))
            p.drawLine(int(x), int(y + ch * i / 3), int(x + cw), int(y + ch * i / 3))
        p.setPen(QPen(QColor("white"), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(int(x), int(y), int(cw), int(ch))
        p.setBrush(QColor(ACCENT))
        for hx, hy in ((x, y), (x + cw, y), (x, y + ch), (x + cw, y + ch)):
            p.drawRect(int(hx) - 5, int(hy) - 5, 10, 10)
        p.end()


class CropPreview(QWidget):
    """右侧实时预览：裁切结果按窗口比例铺满 + 遮罩 + 两张模拟卡片，
    就是主窗口最终看起来的样子，拖框时跟着变。"""

    def __init__(self, pixmap, dim=0.5):
        super().__init__()
        self.pixmap = pixmap
        self.dim = dim
        self.crop = [0.0, 0.0, 1.0, 1.0]
        # 预览框比例 = 默认窗口比例（220:250 ≈ 740:840），裁切框又是窗口比例，
        # 所以预览里框住的那块就是精确铺满的样子，不用再二次裁切
        self.setFixedSize(220, 250)

    def set_crop(self, crop):
        self.crop = crop
        self.update()
        self._prev_cache = None
        self._prev_key = None

    def paintEvent(self, _event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        fx, fy, fw, fh = self.crop
        # 预览缩放也缓存：以前每帧都 copy 大图 + Smooth 缩放，拖框时卡；
        # 现在裁切/尺寸不变就直接贴缓存图。
        _key = (fx, fy, fw, fh, w, h)
        if getattr(self, "_prev_key", None) != _key or getattr(self, "_prev_cache", None) is None:
            iw, ih = self.pixmap.width(), self.pixmap.height()
            src = self.pixmap.copy(max(0, int(fx * iw)), max(0, int(fy * ih)),
                                   max(1, int(fw * iw)), max(1, int(fh * ih)))
            self._prev_cache = src.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self._prev_key = _key
        p.drawPixmap(0, 0, self._prev_cache)
        p.fillRect(0, 0, w, h, QColor(0, 0, 0, int(255 * self.dim)))
        p.setBrush(QColor(255, 255, 255, 215))
        p.setPen(QPen(QColor(BORDER), 1))
        p.drawRoundedRect(10, 12, w - 20, 54, 8, 8)
        p.drawRoundedRect(10, 76, w - 20, 54, 8, 8)
        p.setBrush(QColor(ACCENT))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(20, 34, w - 40, 8, 4, 4)
        p.drawRoundedRect(20, 98, (w - 40) * 2 // 3, 8, 4, 4)
        p.end()


class CropDialog(QDialog):
    """点开裁切的弹窗：左边拖框，右边实时预览，确定才生效。"""

    def __init__(self, parent, image_path, crop, dim, aspect=None):
        super().__init__(parent)
        self.setWindowTitle("裁切背景图片")
        self.resize(960, 700)
        pix = QPixmap(image_path)
        self._pix = pix
        layout = QVBoxLayout(self)
        hint = QLabel("框的比例已锁定为当前窗口比例：框住的那块，确定后会自动铺满整个窗口，"
                      "不留黑边。拖动框内移动，拖角/边缩放，在图上空白处按下拖动可拉出新框；"
                      "右边预览就是最终效果。")
        hint.setProperty("class", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        body = QHBoxLayout()
        self.editor = CropEditor(pix, crop, on_change=self._on_crop_change, aspect=aspect)
        body.addWidget(self.editor, 1)
        right = QVBoxLayout()
        right.addWidget(QLabel("实时预览"))
        self.preview = CropPreview(pix, dim)
        self.preview.set_crop(self.editor.crop())
        right.addWidget(self.preview)
        right.addStretch()
        btn_row = QHBoxLayout()
        reset_btn = QPushButton("恢复整图")
        reset_btn.clicked.connect(self._reset)
        ok_btn = QPushButton("确定")
        ok_btn.setProperty("primary", True)
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        right.addLayout(btn_row)
        body.addLayout(right)
        layout.addLayout(body)

    def _on_crop_change(self, crop):
        self.preview.set_crop(crop)

    def _reset(self):
        self.editor.set_crop([0.0, 0.0, 1.0, 1.0])

    def result_crop(self):
        c = self.editor.crop()
        if c[2] >= 0.99 and c[3] >= 0.99:
            return None
        return c


# ---------------------------------------------------------------- 自定义绘制控件


class AvatarWidget(QWidget):
    """应用头像：彩色圆 + 樱花图标（不再用名字首字，用户 2026-10-25 要求换樱花）。

    圆底色仍按应用名取色（区分应用），圆里画一朵白樱花：5 片花瓣绕中心转
    72 度一瓣，花心粉色；36px 小尺寸下花瓣要够大才看得清，所以花瓣用
    椭圆直接画，不用细线描边。"""

    def __init__(self, name):
        super().__init__()
        self.color = avatar_color(name or "?")
        self.setFixedSize(36, 36)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(self.color))
        p.setPen(Qt.NoPen)
        p.drawEllipse(0, 0, 36, 36)
        # 樱花：5 瓣白花 + 粉色花心
        p.setBrush(QColor("white"))
        for i in range(5):
            p.save()
            p.translate(18, 18)
            p.rotate(i * 72)
            p.drawEllipse(-4, -14, 8, 12)
            p.restore()
        p.setBrush(QColor("#FF8FAB"))
        p.drawEllipse(14, 14, 8, 8)
        p.end()


class BarWidget(QWidget):
    """应用响度条：渐变填充 = 当前有效响度，橙色竖线 = 均衡基准。

    显示值（value/marker）由 60fps 动画定时器向目标值（target）缓动，
    所以条形图是平滑动画，而不是跟着 100ms 的数据一跳一跳。
    """

    def __init__(self):
        super().__init__()
        self.value = 0.0
        self.marker = 0.0
        self.target = 0.0
        self.marker_target = 0.0
        self._init = False
        self.setMinimumHeight(16)
        self.setMaximumHeight(16)

    def set_target(self, value, marker):
        if not self._init:
            self.value, self.marker = value, marker
            self._init = True
        self.target = value
        self.marker_target = marker

    def animate_step(self):
        # 60fps 下每帧缓动 0.25，时间常数约 60ms，和原来 30fps 下 0.4 的手感一致
        changed = False
        for attr, tgt in (("value", self.target), ("marker", self.marker_target)):
            cur = getattr(self, attr)
            if abs(cur - tgt) < 0.004:
                if cur != tgt:
                    setattr(self, attr, tgt)
                    changed = True
            else:
                setattr(self, attr, cur + (tgt - cur) * 0.25)
                changed = True
        return changed

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setBrush(QColor(BORDER))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(0, 0, w, h, 8, 8)
        fill = int(w * max(0.0, min(1.0, self.value)))
        if fill > 0:
            grad = QLinearGradient(0, 0, fill, 0)
            grad.setColorAt(0, QColor(ACCENT_DEEP))
            grad.setColorAt(1, QColor(ACCENT2))
            p.setBrush(grad)
            p.drawRoundedRect(0, 0, fill, h, 8, 8)
        mx = int(w * max(0.0, min(1.0, self.marker)))
        p.setPen(QPen(QColor(MARKER), 3))
        p.drawLine(mx, 0, mx, h)
        p.end()


# ---------------------------------------------------------------- 应用行


class ToggleSwitch(QWidget):
    """药丸开关：紫色开 / 灰色关，点一下切换，接口对齐 QCheckBox（isChecked/setChecked/toggled）。

    开关里还画一朵小樱花当状态标：开 = 轨道空位上画实心白樱花（用户要求），
    关 = 轨道空位上画空心樱花（只描边、不填充），开/关不只靠颜色区分。"""

    toggled = Signal(bool)

    def __init__(self, checked=False):
        super().__init__()
        self._checked = checked
        self.setFixedSize(46, 26)
        self.setCursor(Qt.PointingHandCursor)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        if self._checked != checked:
            self._checked = checked
            self.update()

    def mousePressEvent(self, _event):
        self.setChecked(not self._checked)
        self.toggled.emit(self._checked)

    def _draw_mini_sakura(self, p, cx, cy, solid):
        """在 (cx, cy) 画一朵直径约 16px 的小樱花：实心 = 白瓣 + 粉心；
        空心 = 紫灰描边瓣 + 空心圆环，不填充。"""
        for i in range(5):
            p.save()
            p.translate(cx, cy)
            p.rotate(i * 72)
            if solid:
                p.setBrush(QColor("white"))
                p.setPen(Qt.NoPen)
            else:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor("#8B7CFF"), 1))
            p.drawEllipse(-2, -8, 5, 7)
            p.restore()
        if solid:
            p.setBrush(QColor("#FF8FAB"))
            p.setPen(Qt.NoPen)
        else:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("#8B7CFF"), 1))
        p.drawEllipse(cx - 2, cy - 2, 4, 4)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._checked:
            p.setBrush(QColor(ACCENT))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(0, 0, 46, 26, 13, 13)
            # 开：左边的紫色空位上画实心樱花（白瓣粉心），右边是白圆钮
            self._draw_mini_sakura(p, 11, 13, True)
            p.setBrush(QColor("#FFFFFF"))
            p.setPen(Qt.NoPen)
            p.drawEllipse(23, 3, 20, 20)
        else:
            p.setBrush(QColor(CARD2))
            p.setPen(QPen(QColor(BORDER), 1))
            p.drawRoundedRect(0, 0, 46, 26, 13, 13)
            p.setBrush(QColor("#B8B0D0"))
            p.setPen(Qt.NoPen)
            p.drawEllipse(3, 3, 20, 20)
            # 关：右边的浅色空位上画空心樱花（只描边），左边是灰圆钮
            self._draw_mini_sakura(p, 35, 13, False)
        p.end()


class ClickSlider(QSlider):
    """点轨道直接跳到点击位置的滑杆（替代 Qt 默认的“点一下只走一格”）。

    Qt 原生 QSlider 点轨道时只按页进（pageStep）挪一格，点 80% 的位置
    也只能从当前值挪一格，用户只能拖着滑块慢慢蹭——这就是“不能直接点
    线条切到百分比”的原因。改法：
    ——点在滑块上：走原生拖动，不跳；
    ——点在轨道上：按点击位置算出值，立刻 setValue（此时已置 sliderDown，
      所以音量/基准这类“只在拖动时发命令”的滑杆也会立刻发命令），
      按住不放继续拖就跟着走，松手发 sliderReleased。
    竖向滑杆不在本程序里用，竖向时直接走原生行为。
    """

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._click_dragging = False
        # 手柄 28px + 上下留白，布局再挤也不能把樱花瓣截掉
        self.setMinimumHeight(32)

    def _value_at(self, pos):
        opt = QStyleOptionSlider()
        opt.initFrom(self)
        opt.orientation = self.orientation()
        opt.minimum = self.minimum()
        opt.maximum = self.maximum()
        opt.sliderPosition = self.value()
        opt.sliderValue = self.value()
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderGroove, self)
        if groove.width() <= 0:
            groove = self.rect()
        x = pos.x() - groove.x()
        return self.style().sliderValueFromPosition(
            self.minimum(), self.maximum(), x, groove.width(),
            self.invertedAppearance())

    def _handle_contains(self, pos):
        opt = QStyleOptionSlider()
        opt.initFrom(self)
        opt.orientation = self.orientation()
        opt.minimum = self.minimum()
        opt.maximum = self.maximum()
        opt.sliderPosition = self.value()
        opt.sliderValue = self.value()
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderHandle, self)
        return handle.contains(pos)

    def mousePressEvent(self, event):
        if (self.orientation() == Qt.Horizontal
                and event.button() == Qt.LeftButton
                and not self._handle_contains(event.position().toPoint())):
            self._click_dragging = True
            # setSliderDown 本身就会发 sliderPressed，别再手动发一次（实测会双发）。
            self.setSliderDown(True)
            self.setValue(self._value_at(event.position().toPoint()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._click_dragging:
            self.setValue(self._value_at(event.position().toPoint()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._click_dragging:
            self._click_dragging = False
            # setSliderDown(False) 本身就会发 sliderReleased，别再手动发一次。
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class AppRow(QFrame):
    """一行应用：头像 / 名字 / 响度条 / 音量滑杆 / 自动复选框。"""

    def __init__(self, name, cmd, key=None):
        super().__init__()
        self.name = name
        # 会话键：命令按它走（同一进程多个会话互不串台）；显示仍用进程名。
        self.key = key if key is not None else name
        self._cmd = cmd
        self.setProperty("class", "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(AvatarWidget(name))
        self.name_label = QLabel(name)
        self.name_label.setProperty("class", "section")
        self.name_label.setStyleSheet("font-size: 17px;")
        top.addWidget(self.name_label)
        top.addStretch()
        self.peak_label = QLabel("峰值 0%")
        self.peak_label.setProperty("class", "muted")
        top.addWidget(self.peak_label)
        self.bar = BarWidget()
        bottom = QHBoxLayout()
        vol_title = QLabel("音量")
        vol_title.setProperty("class", "muted")
        bottom.addWidget(vol_title)
        self.slider = ClickSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.valueChanged.connect(self._on_volume)
        bottom.addWidget(self.slider, 1)
        self.vol_label = QLabel("0%")
        self.vol_label.setStyleSheet("font-weight: bold; font-size: 18px; min-width: 52px;")
        bottom.addWidget(self.vol_label)
        auto_title = QLabel("自动")
        auto_title.setProperty("class", "muted")
        bottom.addWidget(auto_title)
        self.auto_switch = ToggleSwitch(True)
        self.auto_switch.toggled.connect(self._on_auto)
        bottom.addWidget(self.auto_switch)
        layout.addLayout(top)
        layout.addWidget(self.bar)
        layout.addLayout(bottom)

    def _on_volume(self, value):
        if not self.slider.isSliderDown():
            return
        self._cmd({"type": "session_volume", "name": self.name, "key": self.key,
                   "value": value / 100.0})

    def _on_auto(self, checked):
        self._cmd({"type": "auto_app", "name": self.name, "key": self.key, "value": checked})

    def update_state(self, data, master, reference):
        self.bar.set_target(data["smooth"] * master, reference * master)
        self.peak_label.setText("峰值 %d%%" % int(data["peak"] * 100))
        if not self.slider.isSliderDown():
            self.slider.setValue(int(data["volume"] * 100))
        self.vol_label.setText("%d%%" % int(data["volume"] * 100))
        if self.auto_switch.isChecked() != data["auto"]:
            self.auto_switch.setChecked(data["auto"])


def _card():
    frame = QFrame()
    frame.setProperty("class", "card")
    return frame


def _transparent(widget, name):
    """只让本控件自身透明：裸写 background: transparent 会被 Qt 扩散到子孙，
    实测曾吃掉主按钮的琥珀底色和模式徽标的底色，改用 ID 选择器只命中自身。"""
    widget.setObjectName(name)
    widget.setStyleSheet("#%s { background: transparent; }" % name)


def _section_row(text, size=None):
    """带紫色竖线的 section 标题行。"""
    row = QHBoxLayout()
    tick = QFrame()
    tick.setFixedSize(3, 14)
    tick.setStyleSheet("background-color: %s;" % ACCENT)
    row.addWidget(tick)
    label = QLabel(text)
    label.setProperty("class", "section")
    if size:
        label.setStyleSheet("font-size: %dpx;" % size)
    row.addWidget(label)
    row.addStretch()
    return row


# ---------------------------------------------------------------- 主窗口


class TitleBar(QWidget):
    """程序自带顶栏：替代系统标题栏（就是用户说的白条）。

    系统标题栏是 Windows 画的，跟程序主题无关、永远不透壁纸，
    想让壁纸铺到窗口最顶上只能把它去掉，顶栏由程序自己画：
    图标 + 标题透在壁纸上，右边是最小化 / 最大化 / 关闭。
    拖动顶栏 = 系统移动窗口（最大化时先点还原再拖，系统标题栏也是这个规矩）；
    双击顶栏 = 最大化/还原切换。关闭走 MainWindow.close()，按原有逻辑
    先缩到托盘、不是直接退出。
    """

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        _transparent(self, "customTitleBar")
        self.setFixedHeight(36)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 4, 0)
        layout.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(make_icon().pixmap(20, 20))
        layout.addWidget(icon)
        title = QLabel("樱响 · 系统响度均衡")
        title.setStyleSheet("font-weight: bold; font-size: 16px;")
        layout.addWidget(title)
        layout.addStretch()
        self.min_btn = QPushButton("—")
        self.max_btn = QPushButton("□")
        self.close_btn = QPushButton("×")
        for btn, tip in ((self.min_btn, "最小化"), (self.max_btn, "最大化/还原"),
                         (self.close_btn, "关闭（缩到托盘）")):
            btn.setFixedSize(36, 28)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; border-radius: 6px;"
                " color: %s; font-size: 16px; padding: 0px; }"
                "QPushButton:hover { background-color: #E9E2F8; }"
                % TEXT)
            layout.addWidget(btn)
        self.close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 6px;"
            " color: %s; font-size: 18px; padding: 0px; }"
            "QPushButton:hover { background-color: #E81123; color: white; }"
            % TEXT)
        self.min_btn.clicked.connect(self._main.showMinimized)
        self.max_btn.clicked.connect(self._main.toggle_maximize)
        self.close_btn.clicked.connect(self._main.close)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self._main.is_maximized_custom():
            try:
                self._main.windowHandle().startSystemMove()
            except Exception:
                pass
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._main.toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, mock):
        super().__init__()
        # 去系统标题栏（白条）：无边框窗口 + 程序自带顶栏，壁纸才能铺到最顶。
        # 任务栏图标仍用 windowTitle/windowIcon，不受影响。
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self._is_maximized = False
        self._normal_geometry = None
        self.setWindowTitle("樱响 · 系统响度均衡")
        self.resize(760, 900)
        self.setWindowIcon(make_icon())
        self.engine = AudioEngine(mock=mock)
        self._rows = {}
        self._quitting = False
        self._tray_msg_shown = False
        self._syncing = False
        self._device_user_choice = None
        self._device_choice_time = 0.0
        self._selftest_pending = False
        self._selftest_click_ts = 0.0
        self._init_alert_shown = False
        self._theme = load_theme()
        try:
            apply_glass_opacity(int(self._theme.get("glass", 84)))
        except Exception:
            pass

        self.bg_widget = BackgroundWidget(self._theme)
        bg_layout = QVBoxLayout(self.bg_widget)
        bg_layout.setContentsMargins(0, 0, 0, 0)
        tabs = QTabWidget()
        tabs.addTab(self._build_volume_tab(), "音量")
        tabs.addTab(self._build_bg_tab(), "背景")
        _transparent(tabs, "mainTabs")
        # 页签栏透明加固：只靠 QSS 的 QTabBar transparent 在 Windows 原生
        # 样式下仍可能被自动填充的底色盖住（页签行看起来就是一块不透的
        # 深色条、壁纸透不出来）。关掉自动填充、不画底座，让它真正透出
        # 底层的壁纸；页签文字仍靠顶部遮罩压住，可读性不受影响。
        _bar = tabs.tabBar()
        _bar.setAutoFillBackground(False)
        _bar.setAttribute(Qt.WA_TranslucentBackground, True)
        _bar.setDrawBase(False)
        self.title_bar = TitleBar(self)
        bg_layout.setSpacing(0)
        bg_layout.addWidget(self.title_bar)
        bg_layout.addWidget(tabs, 1)
        self.setCentralWidget(self.bg_widget)
        # 无边框后系统不再给改大小手柄：用应用级事件过滤器在窗口边缘
        # 8px 内接管拖动改大小（顶边 8px 也是改大小区、其下才是顶栏拖动区，
        # 和系统标题栏的规矩一致）；最大化（自定义铺满可用区）时不改大小。
        try:
            QApplication.instance().installEventFilter(self)
        except Exception:
            pass

        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(make_icon(), self)
            menu = QMenu()
            show_act = QAction("显示窗口", self)
            show_act.triggered.connect(self._show_window)
            quit_act = QAction("退出", self)
            quit_act.triggered.connect(self._quit)
            menu.addAction(show_act)
            menu.addAction(quit_act)
            self.tray.setContextMenu(menu)
            self.tray.setToolTip("樱响")
            self.tray.activated.connect(self._on_tray_activated)
            self.tray.show()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(100)
        self.anim_timer = QTimer(self)
        self.anim_timer.setTimerType(Qt.PreciseTimer)
        self.anim_timer.timeout.connect(self._animate_bars)
        self.anim_timer.start(16)  # 约 60fps
        self.engine.start()
        # 重启后记住上次的基准上限与自动开关（不靠引擎默认值 70%/开）：
        # 命令走队列，引擎线程收到后生效；界面刷新时再从引擎状态同步回来。
        _restored = load_settings()
        if isinstance(_restored.get("target"), (int, float)):
            self._cmd({"type": "target", "value": max(0.5, min(0.9, float(_restored["target"])))})
        if _restored.get("enabled") is False:
            self._cmd({"type": "enabled", "value": False})

        # 真实模式初始化失败时弹框明说（绝不静默进演示模式；演示只留给 --mock）。
        if not mock:
            self._init_timer = QTimer(self)
            self._init_timer.setSingleShot(True)
            self._init_timer.timeout.connect(self._check_engine_init)
            self._init_timer.start(2500)

    def _animate_bars(self):
        for row in self._rows.values():
            if row.bar.animate_step():
                row.bar.update()

    # ---- 音量页 ----

    def _build_volume_tab(self):
        page = QWidget()
        _transparent(page, "volumePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # 顶栏：标题 + 模式徽标
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("樱响")
        title.setProperty("class", "apptitle")
        sub = QLabel("系统响度均衡 · 让每个应用一样响")
        sub.setProperty("class", "subtitle")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        header.addLayout(title_box)
        header.addStretch()
        self.mode_label = QLabel("正在读取…")
        self.mode_label.setProperty("class", "modepill mode-mock")
        header.addWidget(self.mode_label)
        layout.addLayout(header)
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: %s;" % BORDER)
        layout.addWidget(divider)

        # 输出设备卡片
        dev_card = _card()
        dev_layout = QVBoxLayout(dev_card)
        dev_layout.setContentsMargins(18, 16, 18, 16)
        dev_layout.setSpacing(12)
        dev_layout.addLayout(_section_row("输出设备"))
        dev_row = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(300)
        self.device_combo.activated.connect(self._on_device_activated)
        dev_row.addWidget(self.device_combo, 1)
        self.set_default_btn = QPushButton("设为默认")
        self.set_default_btn.setProperty("primary", True)
        self.set_default_btn.clicked.connect(self._on_set_default)
        dev_row.addWidget(self.set_default_btn)
        self.selftest_btn = QPushButton("自检")
        self.selftest_btn.clicked.connect(self._on_selftest)
        dev_row.addWidget(self.selftest_btn)
        dev_layout.addLayout(dev_row)
        hint = QLabel("切换用的是 Windows 未公开接口，个别系统失效时状态栏会明说，届时请去系统声音设置里手动切换。")
        hint.setProperty("class", "muted")
        hint.setWordWrap(True)
        dev_layout.addWidget(hint)
        layout.addWidget(dev_card)

        # 总音量卡片
        master_card = _card()
        master_layout = QVBoxLayout(master_card)
        master_layout.setContentsMargins(18, 16, 18, 16)
        master_layout.setSpacing(12)
        master_top = QHBoxLayout()
        master_top.addLayout(_section_row("系统总音量"))
        master_top.addStretch()
        self.master_label = QLabel("100%")
        self.master_label.setProperty("class", "bigpct")
        master_top.addWidget(self.master_label)
        master_layout.addLayout(master_top)
        self.master_slider = ClickSlider(Qt.Horizontal)
        self.master_slider.setRange(0, 100)
        self.master_slider.valueChanged.connect(self._on_master)
        master_layout.addWidget(self.master_slider)
        layout.addWidget(master_card)

        # 均衡控制卡片
        ctl_card = _card()
        ctl_layout = QVBoxLayout(ctl_card)
        ctl_layout.setContentsMargins(18, 16, 18, 16)
        ctl_layout.setSpacing(12)
        ctl_row1 = QHBoxLayout()
        self.enabled_switch = ToggleSwitch(bool(load_settings().get("enabled", True)))
        self.enabled_switch.toggled.connect(self._on_enabled)
        ctl_row1.addWidget(self.enabled_switch)
        ctl_row1.addWidget(QLabel("自动均衡"))
        ctl_row1.addStretch()
        ctl_row1.addWidget(QLabel("开机自启动"))
        self.autostart_switch = ToggleSwitch(False)
        self.autostart_switch.toggled.connect(self._on_autostart)
        ctl_row1.addWidget(self.autostart_switch)
        ctl_layout.addLayout(ctl_row1)
        ctl_row2 = QHBoxLayout()
        ctl_row2.addWidget(QLabel("基准上限"))
        self.target_slider = ClickSlider(Qt.Horizontal)
        self.target_slider.setRange(50, 90)
        _saved_target = load_settings().get("target")
        try:
            _saved_target = int(round(float(_saved_target) * 100))
        except Exception:
            _saved_target = 70
        self.target_slider.setValue(max(50, min(90, _saved_target)))
        self.target_slider.valueChanged.connect(self._on_target)
        ctl_row2.addWidget(self.target_slider, 1)
        self.target_label = QLabel("%d%%" % self.target_slider.value())
        self.target_label.setStyleSheet("font-weight: bold; min-width: 44px;")
        ctl_row2.addWidget(self.target_label)
        ctl_layout.addLayout(ctl_row2)
        ctl_row3 = QHBoxLayout()
        ctl_row3.addWidget(QLabel("基准应用"))
        self.reference_combo = QComboBox()
        self.reference_combo.addItem("自动（所有出声应用）", "")
        self.reference_combo.activated.connect(self._on_reference)
        ctl_row3.addWidget(self.reference_combo, 1)
        ctl_layout.addLayout(ctl_row3)
        _ref_saved = load_settings()
        self._reference_pending = {"key": _ref_saved.get("reference_key"),
                                   "name": _ref_saved.get("reference_name")} \
            if (_ref_saved.get("reference_key") or _ref_saved.get("reference_name")) else None
        self.phase_label = QLabel("自动均衡：待触发（新程序出声时同步）")
        self.phase_label.setProperty("class", "muted")
        self.phase_label.setWordWrap(True)
        ctl_layout.addWidget(self.phase_label)
        layout.addWidget(ctl_card)

        apps_header = QHBoxLayout()
        apps_header.addLayout(_section_row("各音源实时响度"))
        apps_header.addStretch()
        self.apps_count = QLabel("")
        self.apps_count.setProperty("class", "muted")
        apps_header.addWidget(self.apps_count)
        layout.addLayout(apps_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        _transparent(scroll, "volumeScroll")
        _transparent(scroll.viewport(), "volumeViewport")
        self.rows_container = QWidget()
        _transparent(self.rows_container, "rowsContainer")
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(12)
        self.rows_layout.addStretch()
        scroll.setWidget(self.rows_container)
        layout.addWidget(scroll, 1)

        self.status_label = QLabel("正在读取音频会话…")
        self.status_label.setProperty("class", "status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        return page

    # ---- 背景页 ----

    def _preset_button_style(self, name, selected):
        p = THEME_PRESETS[name]
        border = ACCENT if selected else BORDER
        # 浅色预设（玻璃粉紫/薄荷）用深字，深色预设用白字，否则白字印浅底看不清
        try:
            _h = p["top"].lstrip("#")
            _r, _g, _b = int(_h[0:2], 16), int(_h[2:4], 16), int(_h[4:6], 16)
            _lum = 0.299 * _r + 0.587 * _g + 0.114 * _b
        except Exception:
            _lum = 0
        _fg = "#2E2A3F" if _lum > 150 else "white"
        return ("QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                "stop:0 %s, stop:1 %s); border: 2px solid %s; border-radius: 10px; "
                "padding: 18px 6px; color: %s; font-weight: bold; }"
                % (p["top"], p["bottom"], border, _fg))

    def _build_bg_tab(self):
        page = QWidget()
        _transparent(page, "bgPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        layout.addLayout(_section_row("背景", size=17))
        hint = QLabel("背景只换这个程序窗口的样子，不影响系统和其他程序。"
                      "图片存在你电脑上，换电脑、移动文件后要重新选。")
        hint.setProperty("class", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addLayout(_section_row("预设渐变"))
        preset_row = QHBoxLayout()
        self._preset_buttons = {}
        for name in THEME_PRESETS:
            btn = QPushButton(name)
            btn.clicked.connect(lambda _c, n=name: self._apply_preset(n))
            preset_row.addWidget(btn, 1)
            self._preset_buttons[name] = btn
        layout.addLayout(preset_row)

        tree_row = QHBoxLayout()
        self._tree_switch = ToggleSwitch(bool(self._theme.get("sakura_tree", True)))
        self._tree_switch.toggled.connect(self._on_tree)
        tree_row.addWidget(self._tree_switch)
        tree_row.addWidget(QLabel("樱花树背景（樱花树预设下显示树，关=只显示渐变）"))
        tree_row.addStretch()
        layout.addLayout(tree_row)

        sakura_row = QHBoxLayout()
        self._sakura_switch = ToggleSwitch(bool(self._theme.get("sakura", True)))
        self._sakura_switch.toggled.connect(self._on_sakura)
        # 保留旧属性名作别名：_refresh_bg_controls 等处沿用它，不再用 QCheckBox。
        self._sakura_check = self._sakura_switch
        sakura_row.addWidget(self._sakura_switch)
        sakura_row.addWidget(QLabel("樱花飘落"))
        sakura_row.addStretch()
        layout.addLayout(sakura_row)

        layout.addLayout(_section_row("自定义图片"))
        img_row = QHBoxLayout()
        pick_btn = QPushButton("选择图片…")
        pick_btn.setProperty("primary", True)
        pick_btn.clicked.connect(self._pick_bg_image)
        img_row.addWidget(pick_btn)
        self._crop_btn = QPushButton("裁切…")
        self._crop_btn.clicked.connect(self._open_crop)
        img_row.addWidget(self._crop_btn)
        self._bg_img_label = QLabel("")
        self._bg_img_label.setProperty("class", "muted")
        self._bg_img_label.setWordWrap(True)
        img_row.addWidget(self._bg_img_label, 1)
        clear_btn = QPushButton("清除")
        clear_btn.clicked.connect(self._clear_bg_image)
        img_row.addWidget(clear_btn)
        layout.addLayout(img_row)

        crop_note = QLabel("下面两组只对自定义图片生效，预设渐变不需要裁切。")
        crop_note.setProperty("class", "muted")
        layout.addWidget(crop_note)
        layout.addLayout(_section_row("裁切方式"))
        fit_row = QHBoxLayout()
        self._fit_buttons = {}
        for mode, text in (("cover", "填充铺满"), ("contain", "完整显示"), ("stretch", "拉伸铺满")):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _c, m=mode: self._set_fit(m))
            fit_row.addWidget(btn, 1)
            self._fit_buttons[mode] = btn
        layout.addLayout(fit_row)
        layout.addLayout(_section_row("裁切位置（填充铺满时，决定留住图片的哪一块）"))
        anchor_grid = QGridLayout()
        anchor_grid.setSpacing(6)
        self._anchor_buttons = {}
        labels = [["左上", "上", "右上"], ["左", "中", "右"], ["左下", "下", "右下"]]
        for row_i, ay in enumerate((0.0, 0.5, 1.0)):
            for col_i, ax in enumerate((0.0, 0.5, 1.0)):
                btn = QPushButton(labels[row_i][col_i])
                btn.setFixedSize(52, 36)
                btn.clicked.connect(lambda _c, x=ax, y=ay: self._set_anchor(x, y))
                anchor_grid.addWidget(btn, row_i, col_i)
                self._anchor_buttons[(ax, ay)] = btn
        anchor_wrap = QHBoxLayout()
        anchor_wrap.addLayout(anchor_grid)
        anchor_wrap.addStretch()
        layout.addLayout(anchor_wrap)

        layout.addLayout(_section_row("背景遮罩（背景越亮、字越难看清时往右拉）"))
        dim_row = QHBoxLayout()
        self._dim_slider = ClickSlider(Qt.Horizontal)
        self._dim_slider.setRange(0, 80)
        self._dim_slider.valueChanged.connect(self._on_dim)
        dim_row.addWidget(self._dim_slider, 1)
        self._dim_label = QLabel("15%")
        self._dim_label.setStyleSheet("font-weight: bold; min-width: 44px;")
        dim_row.addWidget(self._dim_label)
        layout.addLayout(dim_row)
        layout.addLayout(_section_row("毛玻璃透明度（卡片＋按钮，往右越不透明）"))
        glass_row = QHBoxLayout()
        self._glass_slider = ClickSlider(Qt.Horizontal)
        self._glass_slider.setRange(50, 100)
        self._glass_slider.valueChanged.connect(self._on_glass)
        glass_row.addWidget(self._glass_slider, 1)
        self._glass_label = QLabel("84%")
        self._glass_label.setStyleSheet("font-weight: bold; min-width: 44px;")
        glass_row.addWidget(self._glass_label)
        layout.addLayout(glass_row)
        layout.addStretch()
        self._refresh_bg_controls()
        return page

    def _apply_theme(self, theme):
        self._theme = dict(theme)
        self.bg_widget.set_theme(self._theme)
        save_theme(self._theme)
        self._refresh_bg_controls()

    def _on_sakura(self, checked):
        theme = dict(self._theme)
        theme["sakura"] = bool(checked)
        self._apply_theme(theme)

    def _on_tree(self, checked):
        theme = dict(self._theme)
        theme["sakura_tree"] = bool(checked)
        self._apply_theme(theme)

    def _apply_preset(self, name):
        theme = dict(self._theme)
        if name == "樱花树":
            theme["type"] = "tree"
            theme["preset"] = name
            theme["dim"] = 0.05
        else:
            theme["type"] = "gradient"
            theme["preset"] = name
            theme["dim"] = 0.15
        self._apply_theme(theme)

    def _pick_bg_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择背景图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            theme = dict(self._theme)
            theme["type"] = "image"
            theme["image"] = path
            theme["crop"] = None  # 换了新图，旧裁切作废
            theme["dim"] = max(float(theme.get("dim", 0.15)), 0.5)
            self._apply_theme(theme)

    def _open_crop(self):
        path = self._theme.get("image", "")
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "没有图片", "请先选择一张自定义图片。")
            return
        aspect = self.width() / max(1, self.height())
        dlg = CropDialog(self, path, self._theme.get("crop"),
                         float(self._theme.get("dim", 0.5)), aspect=aspect)
        if dlg.exec() == QDialog.Accepted:
            theme = dict(self._theme)
            theme["crop"] = dlg.result_crop()
            theme["fit"] = "cover"  # 裁切确定 = 按这块铺满，不留黑边
            self._apply_theme(theme)

    def _clear_bg_image(self):
        theme = dict(self._theme)
        theme["type"] = "gradient"
        theme["preset"] = "玻璃粉紫"
        theme["crop"] = None
        theme["dim"] = 0.05
        self._apply_theme(theme)

    def _on_dim(self, value):
        theme = dict(self._theme)
        theme["dim"] = value / 100.0
        self._theme = theme
        self.bg_widget.set_theme(theme)
        save_theme(theme)
        self._dim_label.setText("%d%%" % value)

    def _on_glass(self, value):
        theme = dict(self._theme)
        theme["glass"] = int(value)
        self._theme = theme
        self.bg_widget.set_theme(theme)
        save_theme(theme)
        apply_glass_opacity(value)
        self._glass_label.setText("%d%%" % value)

    def _set_fit(self, mode):
        theme = dict(self._theme)
        theme["fit"] = mode
        self._apply_theme(theme)

    def _set_anchor(self, ax, ay):
        theme = dict(self._theme)
        theme["anchor"] = [ax, ay]
        self._apply_theme(theme)

    def _seg_button_style(self, selected):
        border = ACCENT if selected else BORDER
        return ("QPushButton { background-color: %s; border: 2px solid %s; "
                "border-radius: 10px; padding: 8px 6px; }" % (CARD2, border))

    def _anchor_button_style(self, selected):
        if selected:
            return ("QPushButton { background-color: %s; border: 2px solid %s; "
                    "border-radius: 8px; font-size: 14px; color: white; }" % (ACCENT, ACCENT))
        return ("QPushButton { background-color: %s; border: 1px solid %s; "
                "border-radius: 8px; font-size: 14px; }" % (CARD2, BORDER))

    def _refresh_bg_controls(self):
        if not hasattr(self, "_preset_buttons"):
            return
        if hasattr(self, "_tree_switch"):
            self._tree_switch.setChecked(bool(self._theme.get("sakura_tree", True)))
        if hasattr(self, "_sakura_check"):
            self._sakura_check.blockSignals(True)
            self._sakura_check.setChecked(bool(self._theme.get("sakura", True)))
            self._sakura_check.blockSignals(False)
        for name, btn in self._preset_buttons.items():
            if name == "樱花树":
                selected = (self._theme.get("type") == "tree"
                            and self._theme.get("preset") == name)
            else:
                selected = (self._theme.get("type") == "gradient"
                            and self._theme.get("preset") == name)
            btn.setStyleSheet(self._preset_button_style(name, selected))
        img = self._theme.get("image", "") if self._theme.get("type") == "image" else ""
        img_text = img if img else "未选择（当前用预设渐变）"
        if img and self._theme.get("crop"):
            img_text += "（已裁切）"
        self._bg_img_label.setText(img_text)
        is_image = self._theme.get("type") == "image"
        if hasattr(self, "_crop_btn"):
            self._crop_btn.setEnabled(is_image)
        if hasattr(self, "_fit_buttons"):
            for mode, btn in self._fit_buttons.items():
                btn.setEnabled(is_image)
                btn.setStyleSheet(self._seg_button_style(self._theme.get("fit", "cover") == mode))
        if hasattr(self, "_anchor_buttons"):
            try:
                cur = self._theme.get("anchor", [0.5, 0.5])
                cax, cay = float(cur[0]), float(cur[1])
            except Exception:
                cax, cay = 0.5, 0.5
            for (ax, ay), btn in self._anchor_buttons.items():
                btn.setEnabled(is_image)
                btn.setStyleSheet(self._anchor_button_style(ax == cax and ay == cay))
        self._dim_slider.blockSignals(True)
        self._dim_slider.setValue(int(float(self._theme.get("dim", 0.15)) * 100))
        self._dim_slider.blockSignals(False)
        self._dim_label.setText("%d%%" % int(float(self._theme.get("dim", 0.15)) * 100))
        if hasattr(self, "_glass_slider"):
            _gv = int(self._theme.get("glass", 84))
            self._glass_slider.blockSignals(True)
            self._glass_slider.setValue(_gv)
            self._glass_slider.blockSignals(False)
            self._glass_label.setText("%d%%" % _gv)

    # ---- 命令 ----

    def _check_engine_init(self):
        """真实模式初始化结果出炉：失败时弹框明说原因与自查方向。

        引擎在失败后不再轮询（state 停留在 failed），这里只弹一次。
        """
        if self._init_alert_shown:
            return
        try:
            with self.engine.lock:
                st = dict(self.engine.state)
        except Exception:
            return
        if st.get("mode") != "failed":
            return
        self._init_alert_shown = True
        reason = st.get("error") or "音频服务初始化失败"
        QMessageBox.critical(
            self, "真实音频初始化失败",
            "樱响无法接上 Windows 音频服务，所以不会进入演示模式。\n\n"
            "原因：%s\n\n"
            "自查：\n"
            "1. 确认在 Windows 10/11 上运行，音频服务正常（别的程序能出声）；\n"
            "2. 确认解压完整，没有被杀毒软件拦住文件；\n"
            "3. 重启一次樱响再试。\n"
            "界面仍可打开查看，但音量控制暂不可用。" % reason,
        )

    def _cmd(self, cmd):
        self.engine.cmd_queue.put(cmd)

    def _on_master(self, value):
        if self.master_slider.isSliderDown():
            self._cmd({"type": "master_volume", "value": value / 100.0})

    def _save_loudness_settings(self):
        data = load_settings()
        data.pop("apo_enabled", None)
        data.pop("apo_path", None)
        data["target"] = self.target_slider.value() / 100.0
        data["enabled"] = self.enabled_switch.isChecked()
        if getattr(self, "_reference_pending", None):
            data["reference_key"] = self._reference_pending.get("key")
            data["reference_name"] = self._reference_pending.get("name")
        elif hasattr(self, "reference_combo"):
            _k = self.reference_combo.currentData()
            data["reference_key"] = _k if _k else None
            data["reference_name"] = self.reference_combo.currentText() if _k else None
        save_settings(data)

    def _on_reference(self, index):
        key = self.reference_combo.itemData(index) or ""
        name = self.reference_combo.currentText() if key else None
        self._reference_pending = None
        self._cmd({"type": "reference", "key": key, "name": name})
        self._save_loudness_settings()

    def _on_target(self, value):
        if self.target_slider.isSliderDown():
            self._cmd({"type": "target", "value": value / 100.0})
            self._save_loudness_settings()

    def _on_enabled(self, checked):
        if not self._syncing:
            self._cmd({"type": "enabled", "value": checked})
            self._save_loudness_settings()

    def _on_autostart(self, checked):
        if not self._syncing:
            self._cmd({"type": "autostart", "value": checked})

    def _on_device_activated(self, _index):
        # 下拉里一点就直接切，不用再点一次“设为默认”；切过去之前刷新不许弹回
        device_id = self.device_combo.currentData()
        self._device_user_choice = device_id
        self._device_choice_time = time.time()
        if device_id:
            self._cmd({"type": "default_device", "device_id": device_id,
                      "device_name": self.device_combo.currentText()})

    def _on_set_default(self):
        # 再确认一次当前下拉里的设备（切换失败时点它可重试）
        device_id = self.device_combo.currentData()
        if device_id:
            self._device_user_choice = device_id
            self._device_choice_time = time.time()
            self._cmd({"type": "default_device", "device_id": device_id,
                      "device_name": self.device_combo.currentText()})

    def _on_selftest(self):
        # 发自检命令；结果回到 state["selftest_result"] 后由 refresh() 弹框显示。
        self._selftest_pending = True
        self._selftest_click_ts = time.time()
        self._cmd({"type": "selftest_device"})

    def _show_selftest_dialog(self, result, devices):
        # result 来自引擎 state["selftest_result"]；devices 为当前设备列表（把 id 译回名字）。
        names = {d.get("id"): d.get("name") for d in devices}

        def _name(dev_id):
            return names.get(dev_id) or dev_id or "（未能读取）"

        def _hint(hr):
            if not isinstance(hr, int):
                return ""
            code = hr & 0xFFFFFFFF
            if code == 0x80070005:
                return "拒绝访问，可能是杀毒软件拦截或权限不足"
            if code == 0x80070490:
                return "找不到设备（设备可能已拔出或被禁用）"
            if code == 0x80040154:
                return "接口未注册（系统音频组件异常）"
            return ""

        def _role_line(role_name, hr):
            if isinstance(hr, int):
                line = "%s：%s（0x%08X）" % (
                    role_name, "成功" if hr == 0 else "失败", hr & 0xFFFFFFFF)
                hint = _hint(hr)
                if hr != 0 and hint:
                    line += "，" + hint
                return line
            return "%s：失败（未能捕获错误码）" % role_name

        if result.get("mock"):
            QMessageBox.information(
                self, "输出设备自检",
                "演示模式：本次自检没有执行真实切换，仅验证弹框链路。\n"
                "请在真实音频模式下再做一次自检。")
            return
        if result.get("error"):
            QMessageBox.warning(self, "输出设备自检",
                                "自检未能执行：%s" % result["error"])
            return
        mm = result.get("hresult_multimedia")
        dev_id = result.get("device_id")
        ver_id = result.get("verified_default_id")
        if ver_id == dev_id:
            ver_line = "验证：调用后默认设备一致，仍是该设备。"
        elif ver_id:
            ver_line = "验证：调用后默认设备不一致，变成了：%s。" % _name(ver_id)
        else:
            ver_line = "验证：未能读到调用后的默认设备。"
        if result.get("ok"):
            conclusion = ("结论：切换接口可用且验证一致；若之前切到别的设备仍失败，"
                          "问题可能出在目标设备上，请换一个目标设备再试，"
                          "并把本弹框截图发回。")
        elif mm == 0:
            conclusion = ("结论：调用返回成功，但实测默认设备没变，Windows 没有采纳"
                          "这次切换（可能被其他音频软件改回，或设备状态异常）。")
        elif isinstance(mm, int):
            conclusion = ("结论：切换接口调用失败，这是之前切换失败的直接原因；"
                          "请按上面括号里的提示排查，并把本弹框截图发回。")
        else:
            conclusion = "结论：未能捕获多媒体角色的调用结果，请把本弹框截图发回。"
        text = "\n".join([
            "当前默认设备：%s" % _name(dev_id),
            _role_line("多媒体角色", mm),
            _role_line("控制台角色", result.get("hresult_console")),
            ver_line,
            conclusion,
        ])
        QMessageBox.information(self, "输出设备自检", text)

    # ---- 刷新 ----

    def refresh(self):
        with self.engine.lock:
            state = dict(self.engine.state)
            sessions = list(state["sessions"])
            devices = list(state["devices"])
            events = list(state["events"])
        mode = state["mode"]
        if mode == "real":
            self.mode_label.setText("真实音频")
            self.mode_label.setProperty("class", "modepill mode-real")
        elif mode == "failed":
            self.mode_label.setText("音频初始化失败")
            self.mode_label.setProperty("class", "modepill mode-mock")
        else:
            self.mode_label.setText("演示模式")
            self.mode_label.setProperty("class", "modepill mode-mock")
        self.mode_label.style().unpolish(self.mode_label)
        self.mode_label.style().polish(self.mode_label)

        # 设备下拉：只有下拉框正展开时不动它；其它时候跟系统默认走，
        # 用户刚点的待切换项在确认前保持显示，3 秒没确认就当切换失败、弹回真默认
        if not self.device_combo.view().isVisible():
            ids = [d["id"] for d in devices]
            current = [self.device_combo.itemData(i) for i in range(self.device_combo.count())]
            if ids != current:
                if self._device_user_choice is not None and self._device_user_choice not in ids:
                    self._device_user_choice = None
                self.device_combo.blockSignals(True)
                self.device_combo.clear()
                for d in devices:
                    self.device_combo.addItem(d["name"], d["id"])
                self.device_combo.blockSignals(False)
            if self._device_user_choice is not None:
                if state["default_device"] == self._device_user_choice:
                    self._device_user_choice = None  # 切成功了，恢复自动同步
                elif time.time() - self._device_choice_time > 3.0:
                    self._device_user_choice = None  # 切换失败，恢复自动同步
                else:
                    idx = self.device_combo.findData(self._device_user_choice)
                    if idx >= 0 and idx != self.device_combo.currentIndex():
                        self.device_combo.blockSignals(True)
                        self.device_combo.setCurrentIndex(idx)
                        self.device_combo.blockSignals(False)
            if self._device_user_choice is None and state["default_device"]:
                idx = self.device_combo.findData(state["default_device"])
                if idx >= 0 and idx != self.device_combo.currentIndex():
                    self.device_combo.blockSignals(True)
                    self.device_combo.setCurrentIndex(idx)
                    self.device_combo.blockSignals(False)

        # 自检结果：引擎回填后弹框显示一次（时间戳防旧结果，弹前先清 pending 防重入）。
        result = state.get("selftest_result")
        if (self._selftest_pending and result is not None
                and result.get("ts", 0) >= self._selftest_click_ts):
            self._selftest_pending = False
            self._show_selftest_dialog(result, devices)

        if not self.master_slider.isSliderDown():
            self.master_slider.setValue(int(state["master"] * 100))
        self.master_label.setText("%d%%" % int(state["master"] * 100))
        if not self.target_slider.isSliderDown():
            self.target_slider.setValue(int(state["target"] * 100))
        self.target_label.setText("%d%%" % int(state["target"] * 100))
        _phase = state.get("phase")
        if _phase is not None and hasattr(self, "phase_label"):
            if _phase == "off":
                self.phase_label.setText("自动均衡：已关")
            elif isinstance(_phase, str) and _phase.startswith("syncing:"):
                try:
                    _left = int(_phase.split(":", 1)[1])
                except Exception:
                    _left = 0
                self.phase_label.setText("自动均衡：同步中（%d 秒后固定）" % _left)
            elif _phase == "fixed":
                self.phase_label.setText("自动均衡：已固定（下次拨开关、新程序出声或响度漂移时再同步）")
            else:
                self.phase_label.setText("自动均衡：待触发（新程序出声时同步）")

        self._syncing = True
        try:
            if self.enabled_switch.isChecked() != state["enabled"]:
                self.enabled_switch.setChecked(state["enabled"])
            if self.autostart_switch.isChecked() != state["autostart"]:
                self.autostart_switch.setChecked(state["autostart"])
        finally:
            self._syncing = False

        # 基准应用下拉：会话集合变了才重建；当前项跟引擎状态走（程序化设置不触发 activated）
        if hasattr(self, "reference_combo"):
            _ref_keys = [""] + [s.get("key", s["name"]) for s in sessions]
            _cur_keys = [self.reference_combo.itemData(i) or "" for i in range(self.reference_combo.count())]
            if _ref_keys != _cur_keys:
                _seen_names = {}
                self.reference_combo.blockSignals(True)
                self.reference_combo.clear()
                self.reference_combo.addItem("自动（所有出声应用）", "")
                for s in sessions:
                    _nm = s["name"]
                    _seen_names[_nm] = _seen_names.get(_nm, 0) + 1
                    _txt = _nm if _seen_names[_nm] == 1 else "%s · %s" % (_nm, str(s.get("key", ""))[-8:])
                    self.reference_combo.addItem(_txt, s.get("key", s["name"]))
                self.reference_combo.blockSignals(False)
            _state_ref = state.get("reference_key") or ""
            if _state_ref:
                _idx = self.reference_combo.findData(_state_ref)
                if _idx >= 0 and _idx != self.reference_combo.currentIndex():
                    self.reference_combo.blockSignals(True)
                    self.reference_combo.setCurrentIndex(_idx)
                    self.reference_combo.blockSignals(False)
            elif self.reference_combo.currentIndex() != 0:
                self.reference_combo.blockSignals(True)
                self.reference_combo.setCurrentIndex(0)
                self.reference_combo.blockSignals(False)
            # 恢复待办：保存的基准应用（按名也行，键换了也能认出来）一出现就设回去
            if getattr(self, "_reference_pending", None) and sessions:
                _pend = self._reference_pending
                _hit = None
                for s in sessions:
                    if _pend.get("key") and s.get("key") == _pend["key"]:
                        _hit = s
                        break
                if _hit is None and _pend.get("name"):
                    for s in sessions:
                        if s["name"] == _pend["name"]:
                            _hit = s
                            break
                if _hit is not None:
                    self._reference_pending = None
                    self._cmd({"type": "reference", "key": _hit.get("key", _hit["name"]),
                               "name": _hit["name"]})
                    self._save_loudness_settings()

        # 应用行：按会话键增删（同名会话各占一行，互不串台）
        keys = [s.get("key", s["name"]) for s in sessions]
        for key in list(self._rows):
            if key not in keys:
                row = self._rows.pop(key)
                self.rows_layout.removeWidget(row)
                row.deleteLater()
        for s in sessions:
            key = s.get("key", s["name"])
            row = self._rows.get(key)
            if row is None:
                row = AppRow(s["name"], self._cmd, key=key)
                self.rows_layout.insertWidget(len(self._rows), row)
                self._rows[key] = row
            row.update_state(s, state["master"], state["reference"])
        self.apps_count.setText("%d 个应用" % len(sessions) if sessions else "")

        if state["error"]:
            self.status_label.setProperty("class", "status-error")
            self.status_label.setStyleSheet("color: %s; font-size: 14px;" % DANGER)
            self.status_label.setText("读取失败：" + state["error"])
        elif events:
            self.status_label.setProperty("class", "status")
            self.status_label.setStyleSheet("color: %s; font-size: 14px;" % MUTED)
            self.status_label.setText(events[-1])

    # ---- 自带顶栏：最大化 / 边缘改大小 ----

    def is_maximized_custom(self):
        return self._is_maximized

    def toggle_maximize(self):
        # 不用 showMaximized：无边框窗口 showMaximized 在部分系统上会盖住
        # 任务栏。改用“铺满当前屏幕可用区”+ 记下还原前的几何尺寸，还原时
        # 精确回到原来大小和位置，行为可预测。
        if not self._is_maximized:
            self._normal_geometry = self.geometry()
            try:
                avail = self.screen().availableGeometry()
            except Exception:
                avail = QApplication.primaryScreen().availableGeometry()
            self.setGeometry(avail)
            self._is_maximized = True
            self.title_bar.max_btn.setText("❐")
        else:
            if self._normal_geometry is not None:
                self.setGeometry(self._normal_geometry)
            self._is_maximized = False
            self.title_bar.max_btn.setText("□")

    def eventFilter(self, obj, event):
        # 只接管本窗口边缘 8px 内的左键按下改大小；窗口内 20px 边距的控件
        # 都不在 8px 区内，不会误吞滑杆/按钮的点击。最大化时不改大小。
        try:
            if (event.type() == QEvent.MouseButtonPress
                    and event.button() == Qt.LeftButton
                    and not self._is_maximized
                    and isinstance(obj, QWidget)
                    and obj.window() is self
                    # 交互控件的点击绝不吞成改大小：顶栏的关闭按钮就在右边缘
                    # 8px 内，吞了它就点不掉窗口了。
                    and obj.__class__.__name__ not in (
                        "QPushButton", "QSlider", "QComboBox", "QCheckBox", "ToggleSwitch",
                        "QSpinBox", "QDoubleSpinBox", "QLineEdit", "QScrollBar")):
                pos = event.globalPosition().toPoint()
                geom = self.geometry()
                margin = 8
                edges = Qt.Edges()
                if pos.x() - geom.left() < margin:
                    edges |= Qt.LeftEdge
                if geom.right() - pos.x() < margin:
                    edges |= Qt.RightEdge
                if pos.y() - geom.top() < margin:
                    edges |= Qt.TopEdge
                if geom.bottom() - pos.y() < margin:
                    edges |= Qt.BottomEdge
                if edges:
                    try:
                        self.windowHandle().startSystemResize(edges)
                    except Exception:
                        pass
                    return True
        except Exception:
            pass
        return super().eventFilter(obj, event)

    # ---- 托盘与退出 ----

    def _show_window(self):
        self.show()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_window()

    def _quit(self):
        self._quitting = True
        self.engine.stop_flag = True
        QApplication.quit()

    def closeEvent(self, event):
        if self.tray is not None and not self._quitting:
            event.ignore()
            self.hide()
            if not self._tray_msg_shown:
                self._tray_msg_shown = True
                self.tray.showMessage("樱响", "已最小化到托盘，右键托盘图标可退出",
                                      QSystemTrayIcon.Information, 3000)
        else:
            self.engine.stop_flag = True
            event.accept()


def main():
    mock = "--mock" in sys.argv or os.environ.get("VOLRIDER_MOCK") == "1"
    # 只屏蔽 pycaw 读设备属性失败的那类警告（刷屏用，消息文本唯一，不会误伤其他警告）。
    warnings.filterwarnings(
        "ignore",
        message="COMError attempting to get property.*",
        category=UserWarning,
    )
    app = QApplication(sys.argv)
    # 圆润字体：内置站酷快乐体（OFL 免费圆体，1.5MB，跟程序同目录），
    # 不靠系统装没装圆体，真机上一定是圆的；缺字按链回落到苹方/圆体/
    # 冬青黑/Segoe UI/微软雅黑 UI/雅黑，不会变宋体。
    try:
        import os as _os
        _font_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                   "ZCOOLKuaiLe-Regular.ttf")
        QFontDatabase.addApplicationFont(_font_path)
    except Exception:
        pass
    _font = QFont()
    _font.setFamilies(["ZCOOL KuaiLe", "PingFang SC", "Yuanti SC", "Hiragino Sans GB",
                       "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei"])
    _font.setPointSize(11)
    app.setFont(_font)
    app.setStyleSheet(QSS)
    app.setQuitOnLastWindowClosed(False)
    win = MainWindow(mock)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    print("樱响（Qt 桌面版 · 只做响度均衡）", flush=True)
    main()

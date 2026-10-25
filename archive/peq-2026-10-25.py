"""VolRider PEQ：20 段参量均衡的数学核心（不碰音频流，只算曲线）。

为什么先只做“算曲线”：
  现在的 VolRider 是音量骑手路线——它只推拉各应用的音量滑杆，
  从头到尾接触不到音频采样，所以没法直接对声音做均衡。
  真正让声音变形的部分需要 APO/虚拟声卡路线（见 README）。
  因此本程序的 PEQ 是：程序内完整编辑 20 个频段 + 实时算出频响曲线
  并显示，同时一键导出 Equalizer APO 配置——装一次 Equalizer APO，
  把导出的配置放进去，均衡就真正作用于系统声音了。
  打开“APO 实时联动”后，调完频段会自动写进 APO 的 config.txt，
  APO 监听到文件变化自动重载，声音跟着变。

数学：RBJ 双二阶峰值滤波器（Peaking EQ），采样率按 48000 Hz 计。
总频响 = 各启用频段的 dB 相加（幅度相乘 = dB 相加）。
"""

import json
import math

SAMPLE_RATE = 48000
BAND_COUNT = 20
FREQ_MIN = 20.0
FREQ_MAX = 20000.0
GAIN_MIN = -12.0
GAIN_MAX = 12.0
Q_MIN = 0.1
Q_MAX = 10.0


def default_frequencies():
    """20 个频段的默认中心频率：30 Hz ~ 16 kHz 对数均分，取整显示。"""
    freqs = []
    for i in range(BAND_COUNT):
        f = 30.0 * (16000.0 / 30.0) ** (i / (BAND_COUNT - 1))
        freqs.append(round(f) if f >= 100 else round(f, 1))
    return freqs


class Band:
    """一个 PEQ 频段：中心频率 / 增益 / Q 值 / 是否启用。"""

    def __init__(self, freq, gain=0.0, q=1.0, enabled=True):
        self.freq = float(freq)
        self.gain = float(gain)
        self.q = float(q)
        self.enabled = bool(enabled)

    def clamp(self):
        self.freq = min(max(self.freq, FREQ_MIN), FREQ_MAX)
        self.gain = min(max(self.gain, GAIN_MIN), GAIN_MAX)
        self.q = min(max(self.q, Q_MIN), Q_MAX)

    def to_dict(self):
        return {"freq": self.freq, "gain": self.gain, "q": self.q, "enabled": self.enabled}

    @staticmethod
    def from_dict(d):
        b = Band(d.get("freq", 1000.0), d.get("gain", 0.0), d.get("q", 1.0), d.get("enabled", True))
        b.clamp()
        return b


def default_bands():
    return [Band(f) for f in default_frequencies()]


def _peaking_db(freq, band):
    """单个峰值滤波器在 freq 处的增益（dB）。gain 为 0 或未启用时返回 0。"""
    if not band.enabled or band.gain == 0.0:
        return 0.0
    a = 10.0 ** (band.gain / 40.0)  # RBJ 的 A = sqrt(10^(gain/20))
    w0 = 2.0 * math.pi * band.freq / SAMPLE_RATE
    alpha = math.sin(w0) / (2.0 * band.q)
    cos_w0 = math.cos(w0)
    b0 = 1.0 + alpha * a
    b1 = -2.0 * cos_w0
    b2 = 1.0 - alpha * a
    a0 = 1.0 + alpha / a
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha / a
    # z = e^(-jw)，w 为待求频率对应的数字角频率
    w = 2.0 * math.pi * freq / SAMPLE_RATE
    cw = math.cos(w)
    sw = math.sin(w)
    # z^-1 = cos(w) - j*sin(w)，z^-2 = cos(2w) - j*sin(2w)
    cw2 = math.cos(2.0 * w)
    sw2 = math.sin(2.0 * w)
    num_re = b0 + b1 * cw + b2 * cw2
    num_im = -b1 * sw - b2 * sw2
    den_re = a0 + a1 * cw + a2 * cw2
    den_im = -a1 * sw - a2 * sw2
    mag = math.hypot(num_re, num_im) / math.hypot(den_re, den_im)
    if mag <= 0.0:
        return -60.0
    return 20.0 * math.log10(mag)


def response_curve(bands, points=240):
    """返回 [(freq, total_db)]：20 Hz ~ 20 kHz 对数均分 points 个点。"""
    curve = []
    lo = math.log10(FREQ_MIN)
    hi = math.log10(FREQ_MAX)
    for i in range(points):
        f = 10.0 ** (lo + (hi - lo) * i / (points - 1))
        total = sum(_peaking_db(f, b) for b in bands)
        curve.append((f, total))
    return curve


def export_apo_config(bands):
    """导出 Equalizer APO 配置文本。

    格式与 Equalizer APO / Peace 通用：Preamp + 每段一行 PK 滤波器。
    只导出启用的频段；增益为 0 的段写出来也不影响声音，为干净起见一并跳过。
    """
    lines = [
        "# VolRider PEQ 导出：把本文件内容放进 Equalizer APO 的 config.txt 即可生效",
        "# 说明：本程序不直接处理音频流；装好 Equalizer APO 并打开“APO 实时联动”后，",
        "# 调完频段会自动同步到 APO 的 config.txt，APO 重载后声音跟着变",
        "Preamp: 0 dB",
    ]
    for b in bands:
        if not b.enabled or b.gain == 0.0:
            continue
        freq_text = ("%g" % b.freq)
        lines.append(
            "Filter: ON PK Fc %s Hz Gain %g dB Q %g" % (freq_text, b.gain, b.q)
        )
    if len(lines) == 4:
        lines.append("# （当前没有启用且增益不为 0 的频段，导出为空配置）")
    return "\n".join(lines) + "\n"


def save_preset(path, bands):
    with open(path, "w", encoding="utf-8") as f:
        json.dump([b.to_dict() for b in bands], f, ensure_ascii=False, indent=2)


def load_preset(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    bands = [Band.from_dict(d) for d in data]
    # 预设频段数不足或超出时，按默认补齐/截断，保证界面永远是 20 段
    defaults = default_frequencies()
    while len(bands) < BAND_COUNT:
        bands.append(Band(defaults[len(bands)]))
    return bands[:BAND_COUNT]

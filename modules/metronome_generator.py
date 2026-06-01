#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
节拍器生成器 — 高保真复刻 Audacity Rhythm Track 插件

基于 Audacity share/nyquist-plug-ins/rhythmtrack.ny
1:1 翻译原版合成算法，包括：
  - lowpass2 / highpass8 双极点+八阶滤波器链
  - jcrev (JC混响) — comb + allpass 网络
  - PWEV / PWL / PWLV 包络精确复刻
  - 三角波振荡器 (cowbell)
  - LCG 伪随机噪声 (metronome click)
  - Bessel 根谐波合成 (drip)

音色类型:
    0 - METRONOME:      节拍器拍 (白噪声+滤波+JC混响)
    1 - PING_SHORT:     砰 (短)
    2 - PING_LONG:      砰 (长)
    3 - COWBELL:        牛铃 (三角波环形调制)
    4 - RESONANT_NOISE: 共鸣噪音 (噪声+谐振低通)
    5 - NOISE_CLICK:    咔嚓噪音 (短促噪声)
    6 - DRIP_SHORT:     滴 (短) (贝塞尔根谐波)
    7 - DRIP_LONG:      滴 (长)

参考: Audacity share/nyquist-plug-ins/rhythmtrack.ny
"""

import os
import math
import numpy as np
import soundfile as sf
import scipy.signal
from typing import Optional, Tuple, List
from dataclasses import dataclass
from enum import Enum


# ═══════════════════════════════════════════════════════════════════
#  类型/配置
# ═══════════════════════════════════════════════════════════════════

class ClickType(Enum):
    """节拍声音类型 — 值与原版 $control choice 的索引一致"""
    METRONOME = 0
    PING_SHORT = 1
    PING_LONG = 2
    COWBELL = 3
    RESONANT_NOISE = 4
    NOISE_CLICK = 5
    DRIP_SHORT = 6
    DRIP_LONG = 7


@dataclass
class MetronomeConfig:
    """节拍器配置

    字段与原版 $control 声明的参数一一映射。
    新增 bars / offset 以完整复刻原版行为。
    """
    bpm: int = 120                    # TEMPO
    duration: float = 30.0            # CLICK-TRACK-DUR（bars=0 时使用）
    beats_per_measure: int = 4        # TIMESIG
    sample_rate: int = 44100

    swing: float = 0.0                # SWING, -1 .. 1
    click_type: ClickType = ClickType.METRONOME  # CLICK-TYPE

    strong_pitch: int = 84            # HIGH (MIDI)
    weak_pitch: int = 80              # LOW (MIDI)
    strong_volume: float = 0.75       # 强拍音量（原版固定 0.75）
    weak_volume: float = 0.5          # 弱拍音量（原版固定 0.5）

    bars: int = 0                     # BARS（0 = 使用 duration 换算）
    offset: float = 0.0               # OFFSET（首拍前静音）


# ═══════════════════════════════════════════════════════════════════
#  DSP 工具函数
# ═══════════════════════════════════════════════════════════════════

def _biquad(sig: np.ndarray, b0: float, b1: float, b2: float,
            a0: float, a1: float, a2: float) -> np.ndarray:
    """通用双二阶滤波器 (Direct Form I)。"""
    b = np.array([b0 / a0, b1 / a0, b2 / a0])
    a = np.array([1.0, a1 / a0, a2 / a0])
    return scipy.signal.lfilter(b, a, sig)


def _lowpass2(sig: np.ndarray, freq: float, q: float, sr: int) -> np.ndarray:
    """
    RBJ 二极点谐振低通。
    等效 Nyquist lowpass2(sig, hz, q)。
    """
    w0 = 2 * math.pi * freq / sr
    w0 = min(w0, 0.95 * math.pi)
    q = max(q, 0.1)
    alpha = math.sin(w0) / (2 * q)
    cos_w0 = math.cos(w0)

    b0 = (1 - cos_w0) / 2
    b1 = 1 - cos_w0
    b2 = (1 - cos_w0) / 2
    a0 = 1 + alpha
    a1 = -2 * cos_w0
    a2 = 1 - alpha
    return _biquad(sig, b0, b1, b2, a0, a1, a2)


def _highpass2(sig: np.ndarray, freq: float, q: float, sr: int) -> np.ndarray:
    """RBJ 二极点高通。"""
    w0 = 2 * math.pi * freq / sr
    w0 = min(w0, 0.95 * math.pi)
    q = max(q, 0.1)
    alpha = math.sin(w0) / (2 * q)
    cos_w0 = math.cos(w0)

    b0 = (1 + cos_w0) / 2
    b1 = -(1 + cos_w0)
    b2 = (1 + cos_w0) / 2
    a0 = 1 + alpha
    a1 = -2 * cos_w0
    a2 = 1 - alpha
    return _biquad(sig, b0, b1, b2, a0, a1, a2)


def _highpass8(sig: np.ndarray, freq: float, sr: int) -> np.ndarray:
    """
    八阶 Butterworth 高通滤波器。
    等效 Nyquist highpass8(sig, hz)。

    Butterworth 8 阶多项式拆分为 4 个 biquad 节，按 pole 角度分布 Q。
    """
    qs = (1.0 / (2 * np.sin(np.pi * (2 * k - 1) / 16))
          for k in (4, 3, 2, 1))  # 0.5098, 0.6013, 0.8999, 2.563
    for q in qs:
        sig = _highpass2(sig, freq, q, sr)
    return sig


def _comb_filter(sig: np.ndarray, delay: int, gain: float) -> np.ndarray:
    """梳状滤波器: y[n] = x[n] + gain * y[n-delay] (IIR)。"""
    b = np.array([1.0])
    a = np.zeros(delay + 1)
    a[0] = 1.0
    a[delay] = -gain
    return scipy.signal.lfilter(b, a, sig)


def _allpass_filter(sig: np.ndarray, delay: int, gain: float) -> np.ndarray:
    """全通滤波器: y[n] = -gain*x[n] + x[n-delay] + gain*y[n-delay]"""
    b = np.zeros(delay + 1)
    b[0] = -gain
    b[delay] = 1.0
    a = np.zeros(delay + 1)
    a[0] = 1.0
    a[delay] = -gain
    return scipy.signal.lfilter(b, a, sig)


def _jcrev(sig: np.ndarray, wet_mix: float, sr: int) -> np.ndarray:
    """
    JC 混响 (Chowning 型)，叠加式 (additive) 混音。

    out = dry + wet_mix * wet

    6 路并联梳状 (g=0.84) → 3 路串联全通 (g=0.7) → scaled add.

    Args:
        sig: 输入信号
        wet_mix: 混响增益叠加系数。推荐 ~0.22
        sr: 采样率
    """
    comb_delays_ms = [50, 56, 61, 68, 72, 78]
    ap_delays_ms = [6, 11, 24]

    acc = np.zeros_like(sig)
    for d_ms in comb_delays_ms:
        d_samp = max(1, int(d_ms * sr / 1000))
        acc += _comb_filter(sig, d_samp, 0.84)
    wet = acc / len(comb_delays_ms)

    for d_ms in ap_delays_ms:
        d_samp = max(1, int(d_ms * sr / 1000))
        wet = _allpass_filter(wet, d_samp, 0.7)

    return sig + wet_mix * wet


# ─── 包络生成 ─────────────────────────────────────────────────


def _pwl_envelope(pts: List[Tuple[float, float]], dur: float, sr: int) -> np.ndarray:
    """
    分段线性包络。
    等效 Nyquist (pwl t1 v1 t2 v2 ... tn vn) 配合 stretch-abs dur。
    首点隐含 (0, 0)，尾段延伸到 dur 并保持末值。
    """
    n_samp = max(1, int(dur * sr))
    env = np.zeros(n_samp)

    if not pts:
        return env

    times = [0.0]
    values = [0.0]
    for t, v in pts:
        times.append(min(t, dur))
        values.append(v)
    if times[-1] < dur:
        times.append(dur)
        values.append(values[-1])

    for i in range(len(times) - 1):
        t0, t1 = times[i], times[i + 1]
        s0 = int(t0 * sr)
        s1 = int(t1 * sr)
        if s1 > s0:
            env[s0:s1] = np.linspace(values[i], values[i + 1], s1 - s0)

    return env


def _pwlv_envelope(levels_durs: List[float], sr: int) -> np.ndarray:
    """
    分段线性包络 (level/duration 对)。
    等效 Nyquist pwlv(l1 d1 l2 d2 ... ln)。
    奇数个参数 = l1,d1,l2,d2,...,ln，末项 ln 无时长。
    """
    args = list(levels_durs)
    n = len(args)
    if n < 3 or n % 2 == 0:
        raise ValueError("pwlv 需要奇数个参数: l1,d1,l2,d2,...,ln")

    levels = args[0::2]
    durs = args[1::2]

    total_dur = sum(durs)
    n_samp = max(1, int(total_dur * sr))
    env = np.empty(n_samp)

    cur = 0.0
    for i in range(len(levels) - 1):
        v0, v1 = levels[i], levels[i + 1]
        dt = durs[i]
        s0 = int(cur * sr)
        s1 = int((cur + dt) * sr) if i < len(durs) else n_samp
        s1 = min(s1, n_samp)
        if s1 > s0:
            env[s0:s1] = np.linspace(v0, v1, s1 - s0)
        cur += dt

    return env


def _pwev_envelope(levels_durs: List[float], sr: int) -> np.ndarray:
    """
    分段指数包络。
    等效 Nyquist pwev(a1 d1 a2 d2 ... an)。
    奇数个参数 = a1,d1,a2,d2,...,an，末项 an 无时长。
    段间指数插值 (对数域线性)。
    """
    args = list(levels_durs)
    n = len(args)
    if n < 3 or n % 2 == 0:
        raise ValueError("pwev 需要奇数个参数: a1,d1,a2,d2,...,an")

    levels = args[0::2]
    durs = args[1::2]

    total_dur = sum(durs)
    n_samp = max(1, int(total_dur * sr))
    env = np.empty(n_samp)

    cur = 0.0
    for i in range(len(levels) - 1):
        v0, v1 = levels[i], levels[i + 1]
        dt = durs[i]
        s0 = int(cur * sr)
        s1 = int((cur + dt) * sr) if i < len(durs) else n_samp
        s1 = min(s1, n_samp)
        seg_len = s1 - s0
        if seg_len > 0:
            t = np.linspace(0, 1, seg_len, endpoint=False)
            if v0 > 0 and v1 > 0:
                env[s0:s1] = np.exp(np.log(v0) + t * (np.log(v1) - np.log(v0)))
            else:
                env[s0:s1] = np.linspace(v0, v1, seg_len)
        cur += dt

    return env


def _exp_dec_envelope(delay: float, rate: float, dur: float, sr: int) -> np.ndarray:
    """
    指数衰减包络。
    等效 Nyquist exp-dec(delay, rate, dur)。
    delay 秒静默后，e^{-t/rate} 衰减持续 dur 秒。
    """
    total = delay + dur
    n_samp = max(1, int(total * sr))
    env = np.ones(n_samp)

    d_samp = int(delay * sr)
    decay_len = min(int(dur * sr), n_samp - d_samp)
    if decay_len > 0:
        t = np.arange(decay_len) / sr
        env[d_samp:d_samp + decay_len] = np.exp(-t / rate)
    return env


# ─── MIDI 工具 ──────────────────────────────────────────────

def _midi_to_hz(midi: int) -> float:
    """MIDI 音高 -> 频率 (A4=440Hz)。"""
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


# ═══════════════════════════════════════════════════════════════════
#  音色生成函数
#  每个函数返回单个节拍声的 numpy 数组 (float32)
# ═══════════════════════════════════════════════════════════════════

def _metronome_tick(hz: float, peak: float, sr: int) -> np.ndarray:
    """
    节拍器拍 — 白噪声 + 滤波 + 包络 + JC 混响。
    等效 Nyquist metronome-tick + get-metronome-tick。
    """
    ln = 300
    sig = np.zeros(ln)
    x = 1
    for i in range(ln):
        x = (479 * x) % 997
        sig[i] = (x / 500.0) - 1.0

    total = int(0.2 * sr)
    buf = np.zeros(total)
    buf[:ln] = sig[:min(ln, total)]
    sig = buf

    env_pwev = _pwev_envelope([10.0, ln / sr, 2.0, 1.0, 0.0], sr)
    env_pwev = np.abs(env_pwev)
    if len(env_pwev) > len(sig):
        env_pwev = env_pwev[:len(sig)]
    else:
        env_pwev = np.pad(env_pwev, (0, len(sig) - len(env_pwev)), 'constant')
    sig = sig * env_pwev

    sig = _lowpass2(sig, 2.0 * hz, 6.0, sr)
    sig = _highpass8(sig, hz, sr)

    sig_peak = np.max(np.abs(sig[:min(300, len(sig))]))
    if sig_peak > 0:
        gain = 1.0 / sig_peak
    else:
        gain = 1.0
    sig = sig * peak * gain

    sig = _jcrev(sig, 0.22, sr)

    env_pwlv = _pwlv_envelope([1.11, 0.02, 1.11, 0.05, 0.0], sr)
    env_pwlv = np.abs(env_pwlv)
    if len(env_pwlv) > len(sig):
        env_pwlv = env_pwlv[:len(sig)]
    else:
        env_pwlv = np.pad(env_pwlv, (0, len(sig) - len(env_pwlv)), 'constant')
    sig = sig * env_pwlv

    return sig.astype(np.float32)


def _ping(hz: float, ticklen: float, amp: float, sr: int) -> np.ndarray:
    """
    砰声 — 正弦波 + PWL 包络。
    等效 Nyquist get-ping(pitch, ticklen)。
    """
    n = max(1, int(ticklen * sr))
    t = np.linspace(0, ticklen, n, endpoint=False)
    wave = np.sin(2 * np.pi * hz * t)

    env_stretched = _pwl_envelope([(0.005 * ticklen, amp),
                                    (0.995 * ticklen, amp)], ticklen, sr)
    if len(env_stretched) < n:
        env_stretched = np.pad(env_stretched, (0, n - len(env_stretched)),
                                'constant', constant_values=0)
    else:
        env_stretched = env_stretched[:n]

    sig = wave * env_stretched * amp
    return sig.astype(np.float32)


def _cowbell(hz: float, sr: int) -> np.ndarray:
    """
    牛铃声 — 三角波环形调制。
    等效 Nyquist cowbell(hz) + get-cowbell(pitch)。
    """
    dur = 1.0
    n = int(dur * sr)
    t = np.linspace(0, dur, n, endpoint=False)

    def tri(f):
        phase = f * t
        return scipy.signal.sawtooth(2 * np.pi * phase, width=0.5)

    env1 = _pwev_envelope([0.3, 0.8, 0.0005], sr)
    if len(env1) < n:
        env1 = np.pad(env1, (0, n - len(env1)), 'constant')

    env2 = _pwev_envelope([0.7, 0.2, 0.01], sr)
    if len(env2) < n:
        env2 = np.pad(env2, (0, n - len(env2)), 'constant')

    comp1 = tri(hz) * tri(hz * 3.46) * env1
    comp2 = tri(hz * 7.3) * tri(hz * 1.52) * env2

    sig = (comp1 + comp2) * 0.8

    last = np.max(np.where(np.abs(sig) > 1e-6))
    if last > 0:
        sig = sig[:last + int(0.01 * sr) + 1]

    return sig.astype(np.float32)


def _resonant_noise(hz: float, amp: float, sr: int) -> np.ndarray:
    """
    共鸣噪音 — 白噪声 + 谐振低通 + 包络。
    等效 Nyquist get-resonant-noise(pitch)。
    """
    dur = 0.05
    n = int(dur * sr)
    rng = np.random.RandomState(0)
    noise = rng.randn(n)

    sig = _lowpass2(noise, hz, 20.0, sr)

    p = np.max(np.abs(sig))
    if p > 0:
        sig = sig / p

    env = _pwl_envelope([(0.05 * dur, amp), (0.95 * dur, amp)], dur, sr)
    if len(env) < n:
        env = np.pad(env, (0, n - len(env)), 'constant', constant_values=0)
    sig = sig[:len(env)] * env

    return sig.astype(np.float32)


def _noise_click(hz: float, amp: float, sr: int) -> np.ndarray:
    """
    咔嚓噪音 — 短促白噪声 + 低通。
    等效 Nyquist get-noise-click(pitch)。
    """
    dur = 0.005
    n = int(dur * sr) + 1
    rng = np.random.RandomState(1)
    noise = rng.randn(n)

    sig = _lowpass2(noise, hz, 2.0, sr)

    p = np.max(np.abs(sig))
    if p > 0:
        sig = sig / p

    env = _pwl_envelope([(0.05 * dur, amp), (0.95 * dur, amp)], dur, sr)
    sig = sig[:min(len(sig), len(env))] * env[:min(len(sig), len(env))]

    return sig.astype(np.float32)


def _drip(hz: float, ticklen: float, amp: float, sr: int) -> np.ndarray:
    """
    水滴声 — Bessel 根谐波 + 低通 440Hz。
    等效 Nyquist drip(p) + get-drip(pitch, ticklen)。
    """
    maxhz = sr / 2.1
    hz1 = min(maxhz, 2.40483 * hz)
    hz2 = min(maxhz, 5.52008 * hz)
    hz3 = min(maxhz, 8.653 * hz)
    hz4 = min(maxhz, 11.8 * hz)

    dur_inner = 1.0
    n_inner = int(dur_inner * sr)
    t_inner = np.linspace(0, dur_inner, n_inner, endpoint=False)

    wave = (np.sin(2 * np.pi * hz1 * t_inner) * 0.5 +
            np.sin(2 * np.pi * hz2 * t_inner) * 0.25 +
            np.sin(2 * np.pi * hz3 * t_inner) * 0.125 +
            np.sin(2 * np.pi * hz4 * t_inner) * 0.0625)

    env_dec = _exp_dec_envelope(0.0, 0.015, 0.25, sr)
    if len(env_dec) < n_inner:
        env_dec = np.pad(env_dec, (0, n_inner - len(env_dec)), 'constant')
    wave = wave * env_dec

    sig = _lowpass2(wave, 440.0, 0.707, sr)

    p = np.max(np.abs(sig))
    if p > 0:
        sig = sig / p

    n_outer = max(1, int(ticklen * sr))
    if len(sig) >= n_outer:
        sig = sig[:n_outer]
    else:
        sig = np.pad(sig, (0, n_outer - len(sig)), 'constant')

    env = _pwl_envelope([(0.005 * ticklen, amp), (0.995 * ticklen, amp)],
                         ticklen, sr)
    sig = sig[:len(env)] * env

    return sig.astype(np.float32)


# ═══════════════════════════════════════════════════════════════════
#  主生成器
# ═══════════════════════════════════════════════════════════════════

class MetronomeGenerator:
    """
    节拍器生成器 — 高保真复刻 Audacity Rhythm Track。

    生成完整节奏音轨，支持 8 种音色、强弱拍区分、Swing。
    """

    CLICK_TYPE_NAMES = {
        ClickType.METRONOME: "节拍器拍",
        ClickType.PING_SHORT: "砰 (短)",
        ClickType.PING_LONG: "砰 (长)",
        ClickType.COWBELL: "牛铃",
        ClickType.RESONANT_NOISE: "共鸣噪音",
        ClickType.NOISE_CLICK: "咔嚓噪音",
        ClickType.DRIP_SHORT: "滴 (短)",
        ClickType.DRIP_LONG: "滴 (长)",
    }

    def __init__(self, config: Optional[MetronomeConfig] = None):
        self.config = config or MetronomeConfig()

    # ── 单节拍生成 ──────────────────────────────────────────

    def _generate_click(self, accent: bool) -> np.ndarray:
        """生成单个节拍声。accent=True -> 强拍 (高音+大音量)。"""
        cfg = self.config
        pitch_midi = cfg.strong_pitch if accent else cfg.weak_pitch
        amp = cfg.strong_volume if accent else cfg.weak_volume
        hz = _midi_to_hz(pitch_midi)
        sr = cfg.sample_rate

        dispatch = {
            ClickType.METRONOME: lambda: _metronome_tick(hz, amp, sr),
            ClickType.PING_SHORT: lambda: _ping(hz, 0.01, amp, sr),
            ClickType.PING_LONG: lambda: _ping(hz, 0.08, amp, sr),
            ClickType.COWBELL: lambda: _cowbell(hz, sr),
            ClickType.RESONANT_NOISE: lambda: _resonant_noise(hz, amp, sr),
            ClickType.NOISE_CLICK: lambda: _noise_click(hz, amp, sr),
            ClickType.DRIP_SHORT: lambda: _drip(hz, 0.007, amp, sr),
            ClickType.DRIP_LONG: lambda: _drip(hz, 0.1, amp, sr),
        }

        gen = dispatch.get(cfg.click_type)
        return gen() if gen else np.array([], dtype=np.float32)

    # ── 轨道装配 ───────────────────────────────────────────

    def generate(self, output_path: Optional[str] = None) -> Tuple[np.ndarray, int]:
        """
        生成完整节奏音轨。

        Args:
            output_path: 保存路径 (None = 不保存)

        Returns:
            (音频数组, 采样率)
        """
        cfg = self.config
        sr = cfg.sample_rate
        beat_len = 60.0 / cfg.bpm

        if cfg.bars > 0:
            bar_count = cfg.bars
        else:
            bar_count = int(np.ceil(cfg.duration / (cfg.beats_per_measure * beat_len)))

        total_beats = bar_count * cfg.beats_per_measure

        strong_click = self._generate_click(True)
        weak_click = self._generate_click(False)

        total_dur = cfg.offset + bar_count * cfg.beats_per_measure * beat_len
        total_samples = int(total_dur * sr) + 1
        track = np.zeros(total_samples, dtype=np.float32)

        off = int(cfg.offset * sr)

        for beat_idx in range(total_beats):
            is_strong = (beat_idx % cfg.beats_per_measure) == 0
            click = strong_click if is_strong else weak_click

            beat_in_bar = beat_idx % cfg.beats_per_measure
            if beat_in_bar % 2 == 1 and cfg.swing != 0:
                swing_offset = cfg.swing * (1.0 / 3.0)
            else:
                swing_offset = 0.0

            pos = off + int((beat_idx + swing_offset) * beat_len * sr)
            end = min(pos + len(click), total_samples)
            if pos >= total_samples:
                break
            click_len = end - pos
            if click_len > 0:
                track[pos:end] += click[:click_len]

        peak = np.max(np.abs(track))
        if peak > 1.0:
            track = track / peak * 0.95

        if output_path:
            sf.write(output_path, track, sr)
            print(f"[INFO] 节拍器已保存: {output_path}")
            print(f"       BPM: {cfg.bpm}, 小节: {bar_count}, "
                  f"音色: {self.CLICK_TYPE_NAMES[cfg.click_type]}")

        return track, sr

    def get_info(self) -> dict:
        """获取当前配置信息。"""
        cfg = self.config
        beat_len = 60.0 / cfg.bpm
        if cfg.bars > 0:
            bar_count = cfg.bars
        else:
            bar_count = int(np.ceil(cfg.duration / (cfg.beats_per_measure * beat_len)))
        total_beats = bar_count * cfg.beats_per_measure
        total_dur = cfg.offset + bar_count * cfg.beats_per_measure * beat_len

        return {
            "bpm": cfg.bpm,
            "duration": total_dur,
            "bars": bar_count,
            "total_beats": total_beats,
            "beats_per_measure": cfg.beats_per_measure,
            "click_type": self.CLICK_TYPE_NAMES[cfg.click_type],
            "sample_rate": cfg.sample_rate,
            "swing": cfg.swing,
            "strong_pitch": cfg.strong_pitch,
            "weak_pitch": cfg.weak_pitch,
            "offset": cfg.offset,
        }


# ═══════════════════════════════════════════════════════════════════
#  CLI 入口
# ═══════════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="节拍器生成器 — 高保真复刻 Audacity Rhythm Track",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python metronome_generator.py --bpm 180 --click-type 0
  python metronome_generator.py --bpm 120 --click-type 3 --bars 8
  python metronome_generator.py --bpm 140 --click-type 6 --swing 0.3
        """,
    )
    parser.add_argument("--bpm", type=int, default=120, help="速度")
    parser.add_argument("--duration", type=float, default=30.0, help="时长 (秒)")
    parser.add_argument("--beats-per-measure", type=int, default=4, help="拍号")
    parser.add_argument("--click-type", type=int, default=0,
                        choices=range(8), help="音色 (0-7)")
    parser.add_argument("--strong-pitch", type=int, default=84, help="强拍 MIDI 音高")
    parser.add_argument("--weak-pitch", type=int, default=80, help="弱拍 MIDI 音高")
    parser.add_argument("--swing", type=float, default=0.0, help="Swing (-1..1)")
    parser.add_argument("--bars", type=int, default=0, help="小节数 (0=按时长)")
    parser.add_argument("--offset", type=float, default=0.0, help="起始偏移 (秒)")
    parser.add_argument("-o", "--output", type=str, default=None, help="输出路径")

    args = parser.parse_args()

    config = MetronomeConfig(
        bpm=args.bpm,
        duration=args.duration,
        beats_per_measure=args.beats_per_measure,
        click_type=ClickType(args.click_type),
        strong_pitch=args.strong_pitch,
        weak_pitch=args.weak_pitch,
        swing=args.swing,
        bars=args.bars,
        offset=args.offset,
    )

    generator = MetronomeGenerator(config)
    info = generator.get_info()

    print("[RunBeat] 节拍器生成器 (复刻版)")
    print("=" * 60)
    for k, v in info.items():
        print(f"  {k}: {v}")
    print("-" * 60)

    if args.output:
        output_path = args.output
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_dir = os.path.dirname(script_dir)
        output_dir = os.path.join(project_dir, "audio_output", "metronome")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(
            output_dir,
            f"metronome_bpm{args.bpm}_type{args.click_type}.wav"
        )
    generator.generate(output_path)
    print(f"[DONE] {output_path}")

    return 0


if __name__ == "__main__":
    exit(main())

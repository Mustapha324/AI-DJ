"""Offline performer for automation-lane transitions.

The planner describes a transition as lanes (gain, 3-band EQ, filter sweeps,
playback rate, loop length, echo send) for the outgoing and incoming decks. This
module turns those lanes into audio for the WAV render; the browser live deck
runs the same lanes with Web Audio nodes, so both sound alike.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import butter, lfilter, sosfilt

from app.models.mix import AutomationLane, MixTransition

ECHO_DELAY_BEATS = 0.75
ECHO_FEEDBACK = 0.45
ECHO_TAPS = 8
ECHO_WET = 0.6
FILTER_Q = 1.1  # a little resonance, like a DJ mixer filter
_BLOCK = 256

_DEFAULTS = {"gain": 1.0, "low": 0.0, "mid": 0.0, "high": 0.0, "hpf": 20.0, "lpf": 20000.0, "rate": 1.0, "echo": 0.0, "loop": 0.0}


def lane_curve(lanes: list[AutomationLane], deck: str, param: str, length: int) -> np.ndarray | None:
    """Sample a lane at ``length`` points (None when the lane is absent)."""
    lane = next((item for item in lanes if item.deck == deck and item.param == param), None)
    if lane is None or length <= 0:
        return None
    points = sorted(lane.points)
    xs = np.array([min(1.0, max(0.0, x)) for x, _ in points], dtype=np.float64)
    ys = np.array([y for _, y in points], dtype=np.float64)
    grid = np.linspace(0.0, 1.0, length, dtype=np.float64)
    if param == "loop":
        index = np.searchsorted(xs, grid, side="right") - 1
        return np.where(index >= 0, ys[np.clip(index, 0, len(ys) - 1)], 0.0)
    if param in {"hpf", "lpf"}:
        # Filter sweeps move evenly in pitch (log frequency), like a real knob.
        return np.exp(np.interp(grid, xs, np.log(np.maximum(ys, 1.0))))
    return np.interp(grid, xs, ys)


def render_automated_transition(
    outgoing: np.ndarray,
    incoming: np.ndarray,
    sample_rate: int,
    transition: MixTransition,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (overlap, spill). ``spill`` is echo tail that rings on into the next song."""
    length = min(len(outgoing), len(incoming))
    if length == 0:
        return np.zeros(0, dtype=np.float32), np.zeros(0, dtype=np.float32)
    lanes = transition.automation
    beat_samples = max(1.0, transition.beat_seconds * sample_rate)
    out_dry, out_echo = _perform_deck(outgoing, length, lanes, "out", sample_rate, beat_samples)
    in_dry, in_echo = _perform_deck(incoming, length, lanes, "in", sample_rate, beat_samples)
    tail = max(length, len(out_echo), len(in_echo))
    wet = np.zeros(tail, dtype=np.float32)
    wet[: len(out_echo)] += out_echo
    wet[: len(in_echo)] += in_echo
    overlap = out_dry + in_dry + wet[:length]
    spill = wet[length:]
    return _soft_limit(overlap), spill.astype(np.float32)


def _perform_deck(
    audio: np.ndarray,
    length: int,
    lanes: list[AutomationLane],
    deck: str,
    sample_rate: int,
    beat_samples: float,
) -> tuple[np.ndarray, np.ndarray]:
    signal = _read_head(audio, length, lanes, deck, beat_samples, sample_rate)

    low, mid, high = (lane_curve(lanes, deck, name, length) for name in ("low", "mid", "high"))
    if low is not None or mid is not None or high is not None:
        bands = _three_bands(signal, sample_rate)
        signal = sum(
            band * (_db_to_gain(curve) if curve is not None else 1.0)
            for band, curve in zip(bands, (low, mid, high), strict=True)
        ).astype(np.float32)

    hpf = lane_curve(lanes, deck, "hpf", length)
    if hpf is not None and float(np.max(hpf)) > 25.0:
        signal = _swept_filter(signal, sample_rate, hpf, "highpass")
    lpf = lane_curve(lanes, deck, "lpf", length)
    if lpf is not None and float(np.min(lpf)) < 18000.0:
        signal = _swept_filter(signal, sample_rate, lpf, "lowpass")

    echo_send = lane_curve(lanes, deck, "echo", length)
    echo = np.zeros(0, dtype=np.float32)
    if echo_send is not None and float(np.max(echo_send)) > 0.001:
        # Pre-fader send: echoes keep ringing after the channel is faded out.
        echo = _echo(signal * echo_send.astype(np.float32), int(ECHO_DELAY_BEATS * beat_samples))

    gain = lane_curve(lanes, deck, "gain", length)
    dry = signal * (gain.astype(np.float32) if gain is not None else 1.0)
    return dry.astype(np.float32), echo


def _read_head(
    audio: np.ndarray,
    length: int,
    lanes: list[AutomationLane],
    deck: str,
    beat_samples: float,
    sample_rate: int,
) -> np.ndarray:
    rate = lane_curve(lanes, deck, "rate", length)
    loop = lane_curve(lanes, deck, "loop", length) if deck == "out" else None
    if rate is None and (loop is None or not np.any(loop > 0)):
        return audio[:length].astype(np.float32)

    rate = rate if rate is not None else np.ones(length)
    positions = np.concatenate([[0.0], np.cumsum(rate[:-1])])
    fade = np.ones(length, dtype=np.float64)
    if loop is not None and np.any(loop > 0):
        engage = int(np.argmax(loop > 0))
        anchor = positions[engage]
        travelled = np.concatenate([[0.0], np.cumsum(rate[engage:-1])])
        loop_samples = np.maximum(16.0, loop[engage:] * beat_samples)
        phase = np.mod(travelled, loop_samples)
        positions[engage:] = anchor + phase
        # Tiny fades at each loop seam so repeats do not click.
        edge = max(8.0, sample_rate * 0.003)
        fade[engage:] = np.clip(np.minimum(phase / edge, (loop_samples - phase) / edge), 0.0, 1.0)
    source = np.arange(len(audio), dtype=np.float64)
    read = np.interp(positions, source, audio.astype(np.float64), right=0.0)
    return (read * fade).astype(np.float32)


def _three_bands(audio: np.ndarray, sample_rate: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if audio.size < 32:
        return audio * 0.3, audio * 0.4, audio * 0.3
    nyquist = sample_rate / 2.0
    low_sos = butter(2, min(180.0, nyquist - 100.0), btype="lowpass", fs=sample_rate, output="sos")
    low = sosfilt(low_sos, audio).astype(np.float32)
    rest = audio - low
    mid_sos = butter(2, min(2500.0, nyquist - 200.0), btype="lowpass", fs=sample_rate, output="sos")
    mid = sosfilt(mid_sos, rest).astype(np.float32)
    return low, mid, (rest - mid).astype(np.float32)


def _swept_filter(audio: np.ndarray, sample_rate: int, frequencies: np.ndarray, kind: str) -> np.ndarray:
    """Resonant 2-pole filter whose cutoff follows ``frequencies`` (block-wise RBJ biquad)."""
    output = np.empty_like(audio, dtype=np.float32)
    state = np.zeros(2)
    nyquist = sample_rate / 2.0
    for start in range(0, len(audio), _BLOCK):
        stop = min(len(audio), start + _BLOCK)
        cutoff = float(np.clip(frequencies[(start + stop) // 2], 20.0, nyquist * 0.95))
        b, a = _rbj_biquad(cutoff, sample_rate, kind, FILTER_Q)
        output[start:stop], state = lfilter(b, a, audio[start:stop], zi=state)
    return output


def _rbj_biquad(cutoff: float, sample_rate: int, kind: str, q: float) -> tuple[np.ndarray, np.ndarray]:
    omega = 2.0 * math.pi * cutoff / sample_rate
    alpha = math.sin(omega) / (2.0 * q)
    cos_w = math.cos(omega)
    if kind == "highpass":
        b = np.array([(1 + cos_w) / 2, -(1 + cos_w), (1 + cos_w) / 2])
    else:
        b = np.array([(1 - cos_w) / 2, 1 - cos_w, (1 - cos_w) / 2])
    a = np.array([1 + alpha, -2 * cos_w, 1 - alpha])
    return b / a[0], a / a[0]


def _echo(send: np.ndarray, delay: int) -> np.ndarray:
    if delay <= 0:
        return np.zeros(len(send), dtype=np.float32)
    total = len(send) + delay * ECHO_TAPS
    wet = np.zeros(total, dtype=np.float32)
    for tap in range(1, ECHO_TAPS + 1):
        offset = tap * delay
        wet[offset : offset + len(send)] += send * (ECHO_WET * ECHO_FEEDBACK ** (tap - 1))
    return wet


def _db_to_gain(curve: np.ndarray) -> np.ndarray:
    return np.power(10.0, curve / 20.0).astype(np.float32)


def _soft_limit(audio: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak <= 0.98:
        return audio.astype(np.float32)
    return (np.tanh(audio / peak * 1.2) * 0.98 / math.tanh(1.2)).astype(np.float32)

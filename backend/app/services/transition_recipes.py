"""Deep transition recipes, written as automation lanes.

Positions are fractions of the transition window (0 = first downbeat of the
transition, 1 = the downbeat where the next song owns the floor). ``bars`` is the
window length, so one beat is ``1 / (4 * bars)``. The numbers follow common club
practice: phrases of 8/16 bars, the bass swaps fast on a downbeat (never two
basslines at once), mids and highs cross slowly, risers end on the "1".
"""

from __future__ import annotations

import math

from app.models.mix import AutomationLane

SILENT = 0.0
KILL_DB = -30.0


def build_lanes(technique: str, bars: float, tempo_ratio: float = 1.0, window_seconds: float = 8.0) -> list[AutomationLane]:
    builder = _RECIPES.get(technique)
    if builder is None:
        return []
    beat = 1.0 / (4.0 * max(bars, 0.25))
    edge = min(0.02, 0.004 / max(window_seconds, 0.1))  # a few ms, to avoid clicks
    lanes = builder(beat=beat, bars=bars, tempo_ratio=tempo_ratio, edge=edge)
    return [AutomationLane(deck=deck, param=param, points=points) for deck, param, points in lanes]


def _double_play(beat: float, bars: float, tempo_ratio: float, edge: float):
    """Both songs play together for the whole window (16 bars when it fits).

    Incoming highs first, then mids; one-beat bass swap on the middle downbeat;
    outgoing mids/highs leave in the second half; outgoing fader out at the end.
    """
    swap = 0.5
    return [
        ("in", "gain", [(0.0, SILENT), (beat * 0.5, 0.9), (swap, 0.9), (swap + beat, 1.0)]),
        ("in", "low", [(0.0, KILL_DB), (swap - beat * 0.5, KILL_DB), (swap + beat * 0.5, 0.0)]),
        ("in", "mid", [(0.0, -14.0), (0.25, -12.0), (swap - beat, -3.0), (swap + beat, 0.0)]),
        ("in", "high", [(0.0, -20.0), (0.25, 0.0)]),
        ("out", "low", [(0.0, 0.0), (swap - beat * 0.5, 0.0), (swap + beat * 0.5, KILL_DB)]),
        ("out", "mid", [(0.0, 0.0), (swap, 0.0), (0.75, -9.0)]),
        ("out", "high", [(0.0, 0.0), (0.25, 0.0), (swap, -6.0), (0.75, -12.0)]),
        ("out", "gain", _equal_power_out(0.75, 1.0, start_level=0.9, hold_from=swap)),
    ]


def _vocal_over(beat: float, bars: float, tempo_ratio: float, edge: float):
    """Mashup feel: the outgoing song is thinned to its vocal band and rides over the
    incoming beat, then echoes out. (Band tricks stand in for real stems.)"""
    thin = beat * 4  # one bar to thin out the outgoing song
    return [
        ("out", "low", [(0.0, 0.0), (thin, KILL_DB)]),
        ("out", "hpf", [(0.0, 20.0), (thin, 250.0)]),
        ("out", "lpf", [(0.0, 20000.0), (thin, 5000.0)]),
        ("out", "mid", [(0.0, 0.0), (thin, 2.0)]),
        ("out", "echo", [(0.0, 0.0), (0.72, 0.0), (0.8, 0.6), (0.94, 0.6), (1.0, 0.0)]),
        ("out", "gain", [(0.0, 1.0), (0.78, 1.0), (0.96, SILENT)]),
        ("in", "gain", [(0.0, SILENT), (beat * 0.25, 1.0)]),
        ("in", "low", [(0.0, KILL_DB), (thin - edge, KILL_DB), (thin, 0.0)]),
        ("in", "mid", [(0.0, -6.0), (0.85, -6.0), (1.0, 0.0)]),
    ]


def _loop_riser(beat: float, bars: float, tempo_ratio: float, edge: float):
    """Repeat the last bar, halve the loop, speed it up and filter it, then drop the next song on the 1."""
    beats_in_window = 4 * bars
    first = max(0.25, beats_in_window / 4)
    loop = [(0.0, first), (0.25, first / 2), (0.5, first / 4), (0.75, first / 8), (0.875, first / 16)]
    rise = min(1.12, max(1.04, tempo_ratio * 1.02))
    return [
        ("out", "loop", [(x, max(0.0625, value)) for x, value in loop]),
        ("out", "rate", [(x, rise**x) for x in (0.0, 0.25, 0.5, 0.75, 1.0)]),
        ("out", "hpf", [(0.0, 20.0), (1.0, 1000.0)]),
        ("out", "echo", [(0.0, 0.0), (1.0 - beat, 0.0), (1.0 - beat * 0.5, 0.7), (1.0, 0.7)]),
        ("out", "gain", [(0.0, 0.85), (1.0 - beat * 0.5, 1.0), (1.0 - beat * 0.25, SILENT)]),
        ("in", "gain", _slam_in(1.0, edge)),
    ]


def _key_lift(beat: float, bars: float, tempo_ratio: float, edge: float):
    """Pitch the outgoing loop up a semitone into the next song's key, then cut on the 1."""
    semitone = 2.0 ** (1.0 / 12.0)
    return [
        ("out", "loop", [(0.0, 4.0 * bars / 2), (0.5, 4.0), (0.75, 2.0), (0.875, 1.0)]),
        ("out", "rate", [(0.0, 1.0), (0.5, 1.0), (1.0, semitone)]),
        ("out", "hpf", [(0.0, 20.0), (0.5, 60.0), (1.0, 500.0)]),
        ("out", "gain", [(0.0, 1.0), (1.0 - edge * 2, 1.0), (1.0, SILENT)]),
        ("in", "gain", _slam_in(1.0, edge)),
    ]


def _beat_juggle(beat: float, bars: float, tempo_ratio: float, edge: float):
    """Call and response: trade the decks back and forth, faster each time, then the new song stays."""
    pattern_beats = [2, 2, 1, 1, 0.5, 0.5, 0.5, 0.5]  # A, B, A, B, ... (8 beats = 2 bars)
    scale = (4 * bars) / sum(pattern_beats)
    out_points: list[tuple[float, float]] = []
    in_points: list[tuple[float, float]] = []
    position = 0.0
    for index, length in enumerate(pattern_beats):
        a_on = index % 2 == 0
        out_points += [(position, 1.0 if a_on else SILENT), (position + edge, 1.0 if a_on else SILENT)]
        in_points += [(position, SILENT if a_on else 1.0), (position + edge, SILENT if a_on else 1.0)]
        position = min(1.0, position + length * scale * beat)
        out_points.append((max(0.0, position - edge), 1.0 if a_on else SILENT))
        in_points.append((max(0.0, position - edge), SILENT if a_on else 1.0))
    out_points.append((1.0, SILENT))
    in_points.append((1.0, 1.0))
    return [("out", "gain", _dedupe(out_points)), ("in", "gain", _dedupe(in_points))]


def _filter_swap(beat: float, bars: float, tempo_ratio: float, edge: float):
    """Resonant high-pass sweeps the outgoing song away while a low-pass opens the incoming one."""
    return [
        ("out", "hpf", [(0.0, 20.0), (0.9, 1200.0)]),
        ("out", "gain", [(0.0, 1.0), (0.6, 0.9), (0.9, 0.55), (1.0, SILENT)]),
        ("in", "gain", [(0.0, SILENT), (beat, 0.9), (1.0, 1.0)]),
        ("in", "lpf", [(0.0, 300.0), (1.0, 20000.0)]),
        ("in", "low", [(0.0, KILL_DB), (1.0 - beat * 0.5, KILL_DB), (1.0, 0.0)]),
    ]


def _slam_in(at: float, edge: float) -> list[tuple[float, float]]:
    return [(0.0, SILENT), (max(0.0, at - edge), SILENT), (at, 1.0)]


def _equal_power_out(start: float, end: float, start_level: float = 1.0, hold_from: float = 0.0):
    points = [(0.0, 1.0), (hold_from, start_level)] if hold_from > 0 else [(0.0, start_level)]
    for step in range(9):
        x = step / 8
        points.append((start + (end - start) * x, start_level * math.cos(x * math.pi / 2)))
    return _dedupe(points)


def _dedupe(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    cleaned: list[tuple[float, float]] = []
    for x, y in sorted(points, key=lambda item: item[0]):
        x = round(min(1.0, max(0.0, x)), 6)
        if cleaned and abs(cleaned[-1][0] - x) < 1e-9:
            cleaned[-1] = (x, y)
        else:
            cleaned.append((x, y))
    return cleaned


_RECIPES = {
    "double_play": _double_play,
    "vocal_over": _vocal_over,
    "loop_riser": _loop_riser,
    "key_lift": _key_lift,
    "beat_juggle": _beat_juggle,
    "filter_swap": _filter_swap,
}

LANE_TECHNIQUES = frozenset(_RECIPES)

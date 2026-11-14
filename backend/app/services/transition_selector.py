"""Pick the transition a working party DJ would use for each pair of songs.

How DJs choose (summarised from DJ technique guides):
- Compatible tempo + key: long EQ blend or bass swap on the phrase, so the
  two grooves ride together and the bass is never doubled.
- Tempo or genre change that cannot be beatmatched: get out cleanly with an
  echo-out, reverb wash, spinback or power-down, or cut on the "1".
- Energy lift: build tension (loop roll, filter) and slam the next drop.
- Energy drop: echo or reverb out, or power down, so the room resets.
- Open-format / hip-hop parties: short cuts on the downbeat; house/techno:
  long blends.
- Never the same move twice in a row, and gimmicks (spinback, power-down)
  only now and then so they still land.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from app.models.mix import MixableTrack
from app.services.compatibility import effective_tempo_ratio, genre_score, key_relation, key_score


@dataclass(frozen=True)
class Technique:
    name: str
    family: str  # "blend" (two songs ride together), "fx" (effect exit), "hard" (cut on the 1)
    gimmick: bool = False
    # Fixed length in bars for moves that happen on the last bar(s) of a phrase.
    fixed_bars: float | None = None
    # Where (0..1 through the transition) the incoming song comes in at full level.
    # 0 means it fades in from the start; 1 means it slams in exactly on the next "1".
    incoming_entry: float = 0.0
    # Longest the fixed-bar window may run; the bar count halves until it fits.
    max_seconds: float = 6.0


TECHNIQUES: dict[str, Technique] = {
    "eq_blend": Technique("eq_blend", "blend"),
    "bass_swap": Technique("bass_swap", "blend"),
    "phrase_blend": Technique("phrase_blend", "blend"),
    "filter_blend": Technique("filter_blend", "blend"),
    "tempo_handoff": Technique("tempo_handoff", "blend"),
    "echo_fade": Technique("echo_fade", "fx"),
    "reverb_wash": Technique("reverb_wash", "fx", fixed_bars=2, incoming_entry=0.5),
    "loop_echo_out": Technique("loop_echo_out", "fx"),
    "roll_build": Technique("roll_build", "hard", fixed_bars=2, incoming_entry=1.0),
    "drop_swap": Technique("drop_swap", "hard"),
    "quick_cut": Technique("quick_cut", "hard", fixed_bars=1),
    "kill_cut": Technique("kill_cut", "hard", fixed_bars=1, incoming_entry=1.0),
    "spinback": Technique("spinback", "hard", gimmick=True, fixed_bars=1, incoming_entry=1.0),
    "power_down": Technique("power_down", "hard", gimmick=True, fixed_bars=1, incoming_entry=1.0),
    # Deep moves (performed from automation lanes, see transition_recipes.py).
    "double_play": Technique("double_play", "blend", fixed_bars=16, max_seconds=34.0),
    "vocal_over": Technique("vocal_over", "blend", fixed_bars=8, max_seconds=20.0),
    "filter_swap": Technique("filter_swap", "fx", fixed_bars=8, max_seconds=18.0),
    "loop_riser": Technique("loop_riser", "hard", gimmick=True, fixed_bars=4, incoming_entry=1.0, max_seconds=10.0),
    "key_lift": Technique("key_lift", "hard", gimmick=True, fixed_bars=4, incoming_entry=1.0, max_seconds=10.0),
    "beat_juggle": Technique("beat_juggle", "hard", gimmick=True, fixed_bars=2, max_seconds=6.0),
}

SMOOTH_WORDS = ("smooth", "chill", "lounge", "ambient", "clean", "mellow", "deep", "long blend")
PARTY_WORDS = ("party", "hype", "open format", "hip hop", "hip-hop", "rap", "turn up", "wedding", "club", "banger")
_DANCE_GENRES = ("house", "techno", "trance", "dance", "electronic", "drum & bass", "dubstep")
_VOCAL_GENRES = ("pop", "r&b", "soul", "hip-hop", "rap", "rock", "country", "afrobeats", "latin", "reggae")

# Explicit requests in the vibe text. Order matters: more specific phrases first.
_DIRECTION_OVERRIDES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("double play", "play together", "both songs", "long mix", "ride together"), "double_play"),
    (("mashup", "mash up", "acapella", "vocal over", "vocals over"), "vocal_over"),
    (("riser", "repeat and speed", "loop and speed"), "loop_riser"),
    (("key change", "key lift", "pitch up"), "key_lift"),
    (("juggle", "back and forth", "call and response", "wordplay"), "beat_juggle"),
    (("filter swap", "filter sweep", "resonant"), "filter_swap"),
    (("quick cut", "hard cut", "scratch"), "quick_cut"),
    (("spinback", "spin back", "backspin", "rewind"), "spinback"),
    (("power down", "power-down", "brake", "vinyl stop", "turntable stop"), "power_down"),
    (("roll", "build up", "buildup"), "roll_build"),
    (("repeat", "loop"), "loop_echo_out"),
    (("cut on the one", "cut on the 1", "slam"), "kill_cut"),
    (("reverb", "wash"), "reverb_wash"),
    (("eq blend", "long blend", "eq mix"), "eq_blend"),
    (("echo",), "echo_fade"),
    (("filter",), "filter_blend"),
    (("bass swap",), "bass_swap"),
    (("drop",), "drop_swap"),
    (("fade",), "phrase_blend"),
)
_TEMPO_REQUEST_WORDS = ("tempo", "speed up", "slow down", "accelerate")


@dataclass(frozen=True)
class PairContext:
    compatibility: float
    tempo_ratio: float
    tempo_delta: float
    beatmatchable: bool
    tempo_locked: bool
    key_ok: bool
    energy_change: float
    genre_change: bool
    dance_pair: bool
    vocal_pair: bool
    hip_hop: bool
    set_position: float
    smooth: bool
    party: bool
    long_blend_ok: bool
    key_lift_ok: bool = False


def pair_context(
    source: MixableTrack,
    target: MixableTrack,
    compatibility_score: float,
    mix_direction: str | None,
    set_position: float = 0.5,
    long_blend_ok: bool = False,
) -> PairContext:
    ratio = effective_tempo_ratio(source.bpm, target.bpm)
    has_tempo = bool(source.bpm and target.bpm)
    source_genre = source.genre.lower()
    target_genre = target.genre.lower()
    direction = (mix_direction or "").lower()
    return PairContext(
        compatibility=compatibility_score,
        tempo_ratio=ratio,
        tempo_delta=abs(ratio - 1.0) * (source.bpm or 120.0) if has_tempo else 0.0,
        beatmatchable=has_tempo and 0.94 <= ratio <= 1.06,
        tempo_locked=has_tempo and 0.985 <= ratio <= 1.015,
        key_ok=key_score(source.key, target.key) >= 0.8,
        energy_change=(target.overall_energy - source.overall_energy)
        / max(source.overall_energy, target.overall_energy, 1e-9),
        genre_change=genre_score(source.genre, target.genre) < 0.6,
        dance_pair=any(word in source_genre for word in _DANCE_GENRES)
        and any(word in target_genre for word in _DANCE_GENRES),
        vocal_pair=any(word in source_genre for word in _VOCAL_GENRES)
        or any(word in target_genre for word in _VOCAL_GENRES),
        hip_hop=any(word in f"{source_genre} {target_genre}" for word in ("hip-hop", "rap")),
        set_position=min(1.0, max(0.0, set_position)),
        smooth=any(word in direction for word in SMOOTH_WORDS),
        party=any(word in direction for word in PARTY_WORDS),
        long_blend_ok=long_blend_ok,
        key_lift_ok=key_relation(source.key, target.key) in {"semitone_lift", "energy_boost"},
    )


def direction_override(context: PairContext, mix_direction: str | None) -> str | None:
    direction = (mix_direction or "").lower()
    # "repeat the song, speed it up, then switch" is the loop riser, not a tempo blend.
    if any(word in direction for word in ("repeat", "loop")) and any(
        word in direction for word in ("speed", "faster", "riser")
    ):
        return "loop_riser"
    if any(word in direction for word in _TEMPO_REQUEST_WORDS):
        return "tempo_handoff" if context.beatmatchable else "echo_fade"
    for words, technique in _DIRECTION_OVERRIDES:
        if any(word in direction for word in words):
            needs_beatmatch = technique in {"eq_blend", "double_play", "vocal_over", "beat_juggle"}
            if needs_beatmatch and not context.beatmatchable:
                return "phrase_blend" if technique != "beat_juggle" else "quick_cut"
            return technique
    return None


def suitability(technique: str, c: PairContext) -> float:
    """How well a move fits this pair of songs, before variety penalties. -inf = not usable."""
    warmup = c.set_position < 0.3
    peak = 0.45 <= c.set_position <= 0.85
    closing = c.set_position > 0.85
    lift = c.energy_change >= 0.15
    drop = c.energy_change <= -0.15
    score: float

    if technique == "eq_blend":
        if not c.long_blend_ok:
            return -math.inf
        score = 0.95 + 0.1 * c.dance_pair - 0.25 * c.vocal_pair + 0.05 * warmup
    elif technique == "bass_swap":
        if not c.beatmatchable or c.compatibility < 0.62:
            return -math.inf
        score = 0.68 + 0.15 * c.dance_pair + 0.1 * c.key_ok + 0.05 * c.tempo_locked - 0.2 * c.vocal_pair
    elif technique == "phrase_blend":
        if not c.beatmatchable or c.compatibility < 0.6:
            return -math.inf
        score = 0.58 + 0.15 * c.key_ok + 0.1 * c.smooth + 0.05 * warmup - 0.1 * (c.party and c.vocal_pair)
    elif technique == "filter_blend":
        if not c.beatmatchable:
            return -math.inf
        # A filter hides a key clash and smooths small energy changes.
        score = 0.55 + 0.12 * (not c.key_ok) + 0.08 * (abs(c.energy_change) < 0.2) + 0.05 * c.smooth
    elif technique == "tempo_handoff":
        if not c.beatmatchable or c.tempo_delta < 2.0:
            return -math.inf
        # Tempo ramps suit beat-driven dance music; open-format DJs mostly cut instead.
        score = 0.6 + 0.16 * c.dance_pair + 0.05 * c.key_ok - 0.12 * c.vocal_pair - 0.1 * c.party
    elif technique == "echo_fade":
        score = 0.5 + 0.22 * (not c.beatmatchable) + 0.1 * drop + 0.08 * c.vocal_pair
    elif technique == "reverb_wash":
        score = 0.46 + 0.22 * (not c.beatmatchable) + 0.14 * drop + 0.14 * closing + 0.1 * c.smooth + 0.06 * c.genre_change
    elif technique == "loop_echo_out":
        score = 0.48 + 0.12 * c.beatmatchable + 0.08 * c.dance_pair - 0.1 * c.vocal_pair
    elif technique == "roll_build":
        score = 0.36 + 0.34 * lift + 0.14 * peak + 0.16 * c.party + 0.06 * c.dance_pair - 0.3 * c.smooth
    elif technique == "drop_swap":
        if not c.beatmatchable:
            return -math.inf
        score = 0.4 + 0.38 * (c.energy_change >= 0.2) + 0.1 * peak + 0.06 * c.party - 0.2 * c.smooth
    elif technique == "quick_cut":
        score = 0.42 + 0.24 * (c.hip_hop or c.vocal_pair) + 0.16 * (not c.beatmatchable) + 0.2 * c.party - 0.28 * c.smooth
    elif technique == "kill_cut":
        score = (
            0.42
            + 0.18 * (not c.beatmatchable)
            + 0.12 * (c.energy_change > 0.05)
            + 0.08 * c.vocal_pair
            + 0.2 * c.party
            - 0.28 * c.smooth
        )
    elif technique == "spinback":
        if warmup:
            return -math.inf
        score = (
            0.3 + 0.28 * c.genre_change + 0.2 * (not c.beatmatchable) + 0.1 * c.party + 0.06 * c.hip_hop - 0.4 * c.smooth
        )
    elif technique == "power_down":
        if warmup:
            return -math.inf
        slower = c.tempo_ratio < 0.94
        score = 0.3 + 0.28 * drop + 0.18 * slower + 0.1 * c.genre_change + 0.06 * closing - 0.4 * c.smooth
    elif technique == "double_play":
        # Both songs ride together for 16 bars: only when tempo and key are locked.
        if not c.long_blend_ok:
            return -math.inf
        score = 0.98 + 0.12 * c.dance_pair - 0.3 * c.vocal_pair + 0.05 * c.smooth - 0.1 * (c.party and not c.dance_pair)
    elif technique == "vocal_over":
        if not c.beatmatchable or not c.key_ok or c.compatibility < 0.68:
            return -math.inf
        score = 0.5 + 0.3 * c.vocal_pair + 0.1 * c.party + 0.05 * c.tempo_locked - 0.1 * c.smooth
    elif technique == "filter_swap":
        if not c.beatmatchable:
            return -math.inf
        score = 0.58 + 0.12 * c.dance_pair + 0.12 * (not c.key_ok) + 0.05 * c.smooth - 0.1 * c.vocal_pair
    elif technique == "loop_riser":
        faster = c.tempo_ratio > 1.03
        score = (
            0.38
            + 0.24 * faster
            + 0.14 * c.genre_change
            + 0.22 * lift
            + 0.1 * peak
            + 0.12 * c.party
            - 0.35 * c.smooth
            - 0.2 * warmup
        )
    elif technique == "key_lift":
        if not c.key_lift_ok or c.energy_change < 0:
            return -math.inf
        score = 0.8 + 0.1 * lift + 0.05 * peak - 0.3 * c.smooth
    elif technique == "beat_juggle":
        if not c.beatmatchable or abs(c.tempo_ratio - 1.0) > 0.03 or not c.key_ok:
            return -math.inf
        score = 0.4 + 0.2 * c.party + 0.15 * c.hip_hop + 0.08 * c.vocal_pair - 0.4 * c.smooth
    else:
        return -math.inf
    return score


class TransitionHistory:
    """What the set has used so far, so the selector can keep it varied."""

    def __init__(self) -> None:
        self.used: list[str] = []

    def add(self, technique: str) -> None:
        self.used.append(technique)


def choose_technique(
    source: MixableTrack,
    target: MixableTrack,
    compatibility_score: float,
    mix_direction: str | None,
    history: TransitionHistory | None = None,
    set_position: float = 0.5,
    long_blend_ok: bool = False,
) -> str:
    context = pair_context(source, target, compatibility_score, mix_direction, set_position, long_blend_ok)
    forced = direction_override(context, mix_direction)
    if forced:
        return forced
    used = history.used if history else []
    ranked = rank_techniques(context, used, f"{source.track_id}>{target.track_id}")
    return ranked[0][0]


def rank_techniques(context: PairContext, used: list[str], pair_key: str) -> list[tuple[str, float]]:
    recent = used[-3:]
    previous = used[-1] if used else None
    last_gimmick = max((index for index, name in enumerate(used) if TECHNIQUES[name].gimmick), default=None)
    ranked: list[tuple[str, float]] = []
    for name, spec in TECHNIQUES.items():
        base = suitability(name, context)
        if base == -math.inf:
            continue
        score = base
        if name == previous:
            score -= 0.6
        score -= 0.22 * recent.count(name)
        score -= 0.05 * used.count(name)
        if previous and TECHNIQUES[previous].family == spec.family:
            score -= 0.08
        if spec.gimmick and last_gimmick is not None and len(used) - last_gimmick <= 4:
            score -= 0.5
        score += _stable_jitter(pair_key, name)
        ranked.append((name, score))
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return ranked


def _stable_jitter(pair_key: str, technique: str) -> float:
    """Small deterministic nudge so similar pairs do not always get the same move."""
    digest = hashlib.sha1(f"{pair_key}:{technique}".encode()).digest()
    return (digest[0] / 255.0) * 0.07

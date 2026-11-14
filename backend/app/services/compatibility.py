from __future__ import annotations

from app.analyzer.key_detector import PITCH_CLASSES
from app.models.track import CompatibilityBreakdown, KeyEstimate, TrackAnalysis, TrackCompatibility


# Weights for the overall score. Tempo and key matter most for a smooth blend,
# genre keeps the room's vibe consistent, energy avoids jarring jumps.
WEIGHTS = {"tempo": 0.32, "key": 0.26, "energy": 0.17, "genre": 0.15, "structure": 0.10}

# Camelot wheel numbers for major keys (B side). Minor keys (A side) use the
# number of their relative major, i.e. three semitones up.
_MAJOR_CAMELOT = {"B": 1, "F#": 2, "C#": 3, "G#": 4, "D#": 5, "A#": 6, "F": 7, "C": 8, "G": 9, "D": 10, "A": 11, "E": 12}

GENRE_FAMILIES = {
    "club": ("house", "techno", "trance", "electronic", "dance", "edm", "drum & bass", "dubstep"),
    "urban": ("hip-hop", "rap", "r&b", "soul", "afrobeats", "amapiano", "reggae", "dancehall", "latin"),
    "band": ("rock", "country", "jazz"),
    "pop": ("pop",),
}
# Families that usually blend well into each other on a dance floor.
_NEIGHBOR_FAMILIES = {frozenset(("club", "pop")), frozenset(("urban", "pop"))}


class CompatibilityService:
    def compare(self, source: TrackAnalysis, target: TrackAnalysis) -> TrackCompatibility:
        breakdown = CompatibilityBreakdown(
            tempo=round(tempo_score(source.estimated_bpm, target.estimated_bpm), 3),
            key=round(key_score(source.key, target.key), 3),
            energy=round(_energy_score(source.overall_rms_energy, target.overall_rms_energy), 3),
            structure=round(_structure_score(source, target), 3),
            genre=round(genre_score(source.genre, target.genre), 3),
        )
        overall = sum(getattr(breakdown, name) * weight for name, weight in WEIGHTS.items())
        return TrackCompatibility(
            source_track_id=source.track_id,
            target_track_id=target.track_id,
            target_title=target.title,
            target_file_name=target.file_name,
            compatibility_score=round(_clamp(overall), 3),
            score_breakdown=breakdown,
        )


def tempo_score(source_bpm: float | None, target_bpm: float | None) -> float:
    """Score how easily two tempos can be beatmatched, including half/double time."""
    if not source_bpm or not target_bpm:
        return 0.45
    direct = _tempo_diff_score(abs(source_bpm - target_bpm))
    # 70 BPM hip-hop into 140 BPM trap/dubstep works when you treat it as half time.
    half_double = max(
        _tempo_diff_score(abs(source_bpm * 2 - target_bpm)),
        _tempo_diff_score(abs(source_bpm - target_bpm * 2)),
    ) * 0.88
    return max(direct, half_double)


def effective_tempo_ratio(source_bpm: float | None, target_bpm: float | None) -> float:
    """Ratio target/source after folding half/double time, so 70 -> 140 reads as 1.0."""
    if not source_bpm or not target_bpm:
        return 1.0
    candidates = (target_bpm / source_bpm, (target_bpm / 2) / source_bpm, (target_bpm * 2) / source_bpm)
    return min(candidates, key=lambda ratio: abs(ratio - 1.0))


def _tempo_diff_score(diff: float) -> float:
    if diff <= 1:
        return 1.0
    if diff <= 4:
        return 0.95
    if diff <= 8:
        return 0.8
    if diff <= 12:
        return 0.6
    return max(0.0, 1.0 - (diff / 40.0))


def camelot_code(key: KeyEstimate) -> tuple[int, str] | None:
    index = _pitch_index(key.root)
    if index is None:
        return None
    major_root = PITCH_CLASSES[(index + 3) % 12] if key.mode == "minor" else key.root
    number = _MAJOR_CAMELOT.get(major_root)
    if number is None:
        return None
    return number, "A" if key.mode == "minor" else "B"


def camelot_label(key: KeyEstimate) -> str | None:
    code = camelot_code(key)
    return f"{code[0]}{code[1]}" if code else None


def key_relation(source: KeyEstimate, target: KeyEstimate) -> str:
    """Name the harmonic move between two keys using Camelot wheel rules."""
    source_code = camelot_code(source)
    target_code = camelot_code(target)
    if not source_code or not target_code:
        return "unknown"
    step = (target_code[0] - source_code[0]) % 12
    same_letter = source_code[1] == target_code[1]
    if step == 0:
        return "same" if same_letter else "relative"
    if step in (1, 11):
        return "adjacent" if same_letter else "diagonal"
    if step == 2 and same_letter:
        return "energy_boost"
    if step == 7 and same_letter:
        return "semitone_lift"
    return "clash"


_KEY_RELATION_SCORES = {
    "same": 1.0,
    "relative": 0.92,
    "adjacent": 0.88,
    "energy_boost": 0.72,
    "diagonal": 0.66,
    "semitone_lift": 0.58,
    "clash": 0.3,
}


def key_score(source: KeyEstimate, target: KeyEstimate) -> float:
    relation = key_relation(source, target)
    if relation == "unknown":
        return 0.45
    raw = _KEY_RELATION_SCORES[relation]
    # Key detection is an estimate. When either side is unsure, lean toward neutral
    # so a shaky key reading cannot dominate song choice.
    certainty = min(source.confidence, target.confidence)
    trust = 0.55 + 0.45 * _clamp(certainty / 0.6)
    return _clamp(0.5 + (raw - 0.5) * trust)


def genre_family(genre: str | None) -> str | None:
    text = (genre or "").lower()
    if not text or "open format" in text:
        return None
    for family, words in GENRE_FAMILIES.items():
        if any(word in text for word in words):
            return family
    return None


def genre_score(source_genre: str | None, target_genre: str | None) -> float:
    source_text = (source_genre or "").strip().lower()
    target_text = (target_genre or "").strip().lower()
    if source_text and source_text == target_text and source_text != "open format":
        return 1.0
    source_family = genre_family(source_text)
    target_family = genre_family(target_text)
    if source_family is None or target_family is None:
        return 0.65
    if source_family == target_family:
        return 0.85
    if frozenset((source_family, target_family)) in _NEIGHBOR_FAMILIES:
        return 0.6
    return 0.35


def _energy_score(source_energy: float, target_energy: float) -> float:
    high = max(source_energy, target_energy, 1e-9)
    diff_ratio = abs(source_energy - target_energy) / high
    return _clamp(1.0 - diff_ratio)


def _structure_score(source: TrackAnalysis, target: TrackAnalysis) -> float:
    score = 0.25
    if source.beats.beat_count >= 4 and target.beats.beat_count >= 4:
        score += 0.25
    if len(source.beats.approximate_bars) >= 2 and len(target.beats.approximate_bars) >= 2:
        score += 0.25
    if source.duration_seconds >= 10 and target.duration_seconds >= 10:
        score += 0.15
    if source.energy_curve and target.energy_curve:
        score += 0.1
    return _clamp(score)


def _pitch_index(root: str) -> int | None:
    try:
        return PITCH_CLASSES.index(root)
    except ValueError:
        return None


def _clamp(value: float) -> float:
    return float(min(1.0, max(0.0, value)))

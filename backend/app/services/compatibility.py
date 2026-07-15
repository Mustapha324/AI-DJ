from __future__ import annotations

from app.analyzer.key_detector import PITCH_CLASSES
from app.models.track import CompatibilityBreakdown, TrackAnalysis, TrackCompatibility


class CompatibilityService:
    def compare(self, source: TrackAnalysis, target: TrackAnalysis) -> TrackCompatibility:
        tempo = _tempo_score(source.estimated_bpm, target.estimated_bpm)
        key = _key_score(source, target)
        energy = _energy_score(source.overall_rms_energy, target.overall_rms_energy)
        structure = _structure_score(source, target)

        overall = (tempo * 0.35) + (key * 0.3) + (energy * 0.2) + (structure * 0.15)
        return TrackCompatibility(
            source_track_id=source.track_id,
            target_track_id=target.track_id,
            target_title=target.title,
            target_file_name=target.file_name,
            compatibility_score=round(float(_clamp(overall)), 3),
            score_breakdown=CompatibilityBreakdown(
                tempo=round(float(tempo), 3),
                key=round(float(key), 3),
                energy=round(float(energy), 3),
                structure=round(float(structure), 3),
            ),
        )


def _tempo_score(source_bpm: float | None, target_bpm: float | None) -> float:
    if not source_bpm or not target_bpm:
        return 0.45
    diff = abs(source_bpm - target_bpm)
    if diff <= 1:
        return 1.0
    if diff <= 4:
        return 0.95
    if diff <= 8:
        return 0.8
    if diff <= 12:
        return 0.6
    return max(0.0, 1.0 - (diff / 40.0))


def _key_score(source: TrackAnalysis, target: TrackAnalysis) -> float:
    source_index = _pitch_index(source.key.root)
    target_index = _pitch_index(target.key.root)
    if source_index is None or target_index is None:
        return 0.45

    distance = min((source_index - target_index) % 12, (target_index - source_index) % 12)
    same_mode = source.key.mode == target.key.mode

    if distance == 0 and same_mode:
        return 1.0
    if _relative_major_minor(source, target):
        return 0.92
    if distance == 7 or distance == 5:
        return 0.85 if same_mode else 0.75
    if distance <= 2:
        return 0.7 if same_mode else 0.58
    if distance <= 4:
        return 0.55 if same_mode else 0.45
    return 0.3


def _energy_score(source_energy: float, target_energy: float) -> float:
    high = max(source_energy, target_energy, 1e-9)
    diff_ratio = abs(source_energy - target_energy) / high
    return _clamp(1.0 - diff_ratio)


def _structure_score(source: TrackAnalysis, target: TrackAnalysis) -> float:
    source_has_beats = source.beats.beat_count >= 4
    target_has_beats = target.beats.beat_count >= 4
    source_has_bars = len(source.beats.approximate_bars) >= 2
    target_has_bars = len(target.beats.approximate_bars) >= 2
    duration_ok = source.duration_seconds >= 10 and target.duration_seconds >= 10

    score = 0.25
    if source_has_beats and target_has_beats:
        score += 0.25
    if source_has_bars and target_has_bars:
        score += 0.25
    if duration_ok:
        score += 0.15
    if source.energy_curve and target.energy_curve:
        score += 0.1
    return _clamp(score)


def _relative_major_minor(source: TrackAnalysis, target: TrackAnalysis) -> bool:
    source_index = _pitch_index(source.key.root)
    target_index = _pitch_index(target.key.root)
    if source_index is None or target_index is None or source.key.mode == target.key.mode:
        return False
    if source.key.mode == "major":
        return target_index == (source_index - 3) % 12
    return target_index == (source_index + 3) % 12


def _pitch_index(root: str) -> int | None:
    try:
        return PITCH_CLASSES.index(root)
    except ValueError:
        return None


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))

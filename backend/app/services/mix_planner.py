from __future__ import annotations

import math
from datetime import datetime, timezone

from app.models.mix import MixableTrack, MixPlan, MixPlanRequest, MixTrackPlacement, MixTransition
from app.models.track import TrackAnalysis
from app.services.compatibility import CompatibilityService


class MixPlanningError(Exception):
    """Raised when a mix plan cannot be created from the requested tracks."""


class MixPlanner:
    def __init__(self, compatibility_service: CompatibilityService | None = None) -> None:
        self.compatibility_service = compatibility_service or CompatibilityService()

    def create_plan(
        self,
        request: MixPlanRequest,
        analyses: list[TrackAnalysis],
        mix_id: str,
    ) -> MixPlan:
        if len(set(request.track_ids)) != len(request.track_ids):
            raise MixPlanningError("Track IDs must be unique for a mix plan.")

        analysis_by_id = {analysis.track_id: analysis for analysis in analyses}
        missing_ids = [track_id for track_id in request.track_ids if track_id not in analysis_by_id]
        if missing_ids:
            raise MixPlanningError(f"Track(s) were not found: {', '.join(missing_ids)}.")

        ordered_ids = (
            self._auto_order([analysis_by_id[track_id] for track_id in request.track_ids])
            if request.auto_order
            else request.track_ids
        )
        tracks = [_to_mixable_track(analysis_by_id[track_id]) for track_id in ordered_ids]

        target_seconds = request.target_duration_minutes * 60 if request.target_duration_minutes else None
        target_limit = (target_seconds / len(tracks)) if target_seconds else None
        per_track_limit = _per_track_limit(target_limit, request.max_play_seconds_per_track)

        placements: list[MixTrackPlacement] = []
        transitions: list[MixTransition] = []
        timeline_start = 0.0

        transition_bars = _direction_adjusted_transition_bars(request.transition_bars, request.mix_direction)
        transition_sfx = _sfx_for_direction(request.mix_direction, request.use_transition_sfx)

        source_starts = [0.0] + [_choose_track_start(track) for track in tracks[1:]]

        for index, track in enumerate(tracks):
            source_start = source_starts[index]
            source_end = _choose_track_end(track, source_start, per_track_limit)
            transition_duration = 0.0

            if index < len(tracks) - 1:
                next_track = tracks[index + 1]
                transition_duration = _transition_duration_seconds(track, next_track, transition_bars)
                source_end = _choose_transition_end(track, source_start, source_end, transition_duration)

            timeline_end = round(timeline_start + max(0.0, source_end - source_start), 3)
            placements.append(
                MixTrackPlacement(
                    track_id=track.track_id,
                    file_name=track.file_name,
                    title=track.title,
                    source_start_time=round(source_start, 3),
                    source_end_time=round(source_end, 3),
                    timeline_start_time=round(timeline_start, 3),
                    timeline_end_time=timeline_end,
                    bpm=track.bpm,
                    key=track.key.display_name,
                )
            )

            if index < len(tracks) - 1:
                next_track = tracks[index + 1]
                transition_start = round(max(source_start, source_end - transition_duration), 3)
                transition_end = round(source_end, 3)
                compatibility = self.compatibility_service.compare(
                    analysis_by_id[track.track_id],
                    analysis_by_id[next_track.track_id],
                )
                bpm_adjustment = _bpm_adjustment_percent(track.bpm, next_track.bpm)
                target_start = source_starts[index + 1]
                transitions.append(
                    MixTransition(
                        source_track_id=track.track_id,
                        target_track_id=next_track.track_id,
                        source_transition_start=transition_start,
                        source_transition_end=transition_end,
                        target_transition_start=round(target_start, 3),
                        target_transition_end=round(target_start + transition_duration, 3),
                        timeline_start_time=round(timeline_end - transition_duration, 3),
                        timeline_end_time=timeline_end,
                        duration_seconds=round(transition_duration, 3),
                        bpm_adjustment_percent=bpm_adjustment,
                        gain_adjustment_db=_gain_adjustment_db(track.overall_energy, next_track.overall_energy),
                        crossfade_curve="equal_power",
                        transition_type="crossfade",
                        compatibility_score=compatibility.compatibility_score,
                        sfx=transition_sfx,
                    )
                )
                timeline_start = round(timeline_end - transition_duration, 3)

        estimated_duration = placements[-1].timeline_end_time if placements else 0.0
        return MixPlan(
            mix_id=mix_id,
            mix_name=request.mix_name,
            mix_direction=request.mix_direction,
            use_transition_sfx=request.use_transition_sfx,
            max_play_seconds_per_track=request.max_play_seconds_per_track,
            track_order=[track.track_id for track in tracks],
            placements=placements,
            transitions=transitions,
            estimated_duration_seconds=round(estimated_duration, 3),
            created_at=datetime.now(timezone.utc),
        )

    def _auto_order(self, analyses: list[TrackAnalysis]) -> list[str]:
        remaining = sorted(analyses, key=lambda item: (item.estimated_bpm or 0.0, item.overall_rms_energy))
        ordered = [remaining.pop(0)]

        while remaining:
            source = ordered[-1]
            best = max(
                remaining,
                key=lambda candidate: (
                    self.compatibility_service.compare(source, candidate).compatibility_score,
                    candidate.overall_rms_energy,
                ),
            )
            ordered.append(best)
            remaining.remove(best)

        return [analysis.track_id for analysis in ordered]


def _to_mixable_track(analysis: TrackAnalysis) -> MixableTrack:
    return MixableTrack(
        track_id=analysis.track_id,
        file_name=analysis.file_name,
        title=analysis.title,
        duration_seconds=analysis.duration_seconds,
        bpm=analysis.estimated_bpm,
        key=analysis.key,
        overall_energy=analysis.overall_rms_energy,
        beat_timestamps=analysis.beats.beat_timestamps,
        approximate_bars=analysis.beats.approximate_bars,
        energy_curve=analysis.energy_curve,
    )


def _transition_duration_seconds(source: MixableTrack, target: MixableTrack, transition_bars: int) -> float:
    bpm = source.bpm or target.bpm or 120.0
    requested = transition_bars * 4 * (60.0 / bpm)
    upper_bound = min(source.duration_seconds * 0.4, target.duration_seconds * 0.4, 45.0)
    if upper_bound <= 0:
        return 0.0
    return round(max(min(requested, upper_bound), min(1.0, upper_bound)), 3)


def _per_track_limit(target_limit: float | None, max_play_seconds: float | None) -> float | None:
    limits = [limit for limit in (target_limit, max_play_seconds) if limit is not None]
    return min(limits) if limits else None


def _direction_adjusted_transition_bars(base_bars: int, mix_direction: str | None) -> int:
    if not mix_direction:
        return base_bars

    direction = mix_direction.lower()
    if any(word in direction for word in ("quick", "fast cut", "hip hop", "rap", "pop")):
        return min(base_bars, 4)
    if any(word in direction for word in ("ambient", "chill", "lounge", "smooth", "long blend")):
        return max(base_bars, 12)
    if any(word in direction for word in ("house", "techno", "edm", "trance", "dance")):
        return max(base_bars, 8)
    return base_bars


def _sfx_for_direction(mix_direction: str | None, enabled: bool) -> list[str]:
    if not enabled:
        return []

    direction = (mix_direction or "").lower()
    if any(word in direction for word in ("hip hop", "rap", "pop", "quick")):
        return ["impact"]
    if any(word in direction for word in ("house", "techno", "edm", "trance", "dance", "club")):
        return ["noise_sweep", "impact"]
    if any(word in direction for word in ("ambient", "chill", "lounge", "smooth")):
        return ["soft_sweep"]
    return ["noise_sweep", "impact"]


def _choose_track_start(track: MixableTrack) -> float:
    bar_candidates = [
        bar.start_time
        for bar in track.approximate_bars
        if 0.25 <= bar.start_time <= min(24.0, track.duration_seconds * 0.2)
    ]
    if bar_candidates:
        return round(bar_candidates[0], 3)

    beat_candidates = [
        beat_time
        for beat_time in track.beat_timestamps
        if 0.25 <= beat_time <= min(16.0, track.duration_seconds * 0.15)
    ]
    if beat_candidates:
        return round(beat_candidates[0], 3)

    return 0.0


def _choose_track_end(track: MixableTrack, source_start: float, per_track_limit: float | None) -> float:
    raw_end = min(track.duration_seconds, source_start + per_track_limit) if per_track_limit else track.duration_seconds
    if raw_end <= source_start:
        return 0.0
    return _nearest_bar_before(track, raw_end) or round(raw_end, 3)


def _choose_transition_end(
    track: MixableTrack,
    source_start: float,
    current_end: float,
    transition_duration: float,
) -> float:
    minimum_end = min(track.duration_seconds, source_start + transition_duration + 1.0)
    latest_end = min(track.duration_seconds, max(current_end, minimum_end))
    candidates = [
        bar.start_time
        for bar in track.approximate_bars
        if minimum_end <= bar.start_time <= latest_end
    ]

    if candidates:
        segment_length = max(latest_end - source_start, 1.0)

        def score(candidate: float) -> float:
            transition_start = max(source_start, candidate - transition_duration)
            energy = _energy_at_time(track, transition_start)
            progress = (candidate - source_start) / segment_length
            phrase_weight = 1.0 if _is_phrase_boundary(track, candidate) else 0.8
            return ((1.0 - energy) * 0.45) + (progress * 0.4) + (phrase_weight * 0.15)

        return round(max(candidates, key=score), 3)

    boundary = _nearest_bar_before(track, latest_end)
    if boundary and boundary >= minimum_end:
        return boundary
    return round(latest_end, 3)


def _nearest_bar_before(track: MixableTrack, time_seconds: float) -> float | None:
    candidates = [bar.start_time for bar in track.approximate_bars if 0 < bar.start_time <= time_seconds]
    if not candidates:
        return None
    return round(max(candidates), 3)


def _energy_at_time(track: MixableTrack, time_seconds: float) -> float:
    if not track.energy_curve:
        return 0.5
    return min(track.energy_curve, key=lambda point: abs(point.time - time_seconds)).energy


def _is_phrase_boundary(track: MixableTrack, time_seconds: float) -> bool:
    for bar in track.approximate_bars:
        if abs(bar.start_time - time_seconds) <= 0.05:
            return (bar.bar_number - 1) % 4 == 0
    return False


def _bpm_adjustment_percent(source_bpm: float | None, target_bpm: float | None) -> float:
    if not source_bpm or not target_bpm:
        return 0.0
    ratio = source_bpm / target_bpm
    if 0.92 <= ratio <= 1.08:
        return round((ratio - 1.0) * 100.0, 3)
    return 0.0


def _gain_adjustment_db(source_energy: float, target_energy: float) -> float:
    if source_energy <= 1e-9 or target_energy <= 1e-9:
        return 0.0
    ratio = source_energy / target_energy
    return round(max(-6.0, min(6.0, 20.0 * math.log10(ratio))), 3)

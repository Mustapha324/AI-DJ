from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from app.models.mix import MixableTrack, MixPlan, MixPlanRequest, MixTrackPlacement, MixTransition
from app.models.style_profile import DJStyleProfile
from app.models.track import TrackAnalysis
from app.services.compatibility import CompatibilityService, effective_tempo_ratio, key_score
from app.services.song_research_service import recommend_play_window
from app.services.transition_selector import TECHNIQUES, TransitionHistory, choose_technique
from app.services.vibe import energy_arc_target, energy_flow_fit

# Arc weight vs. pair cost when ordering a set. Pair cost (1 - compatibility)
# dominates so blends stay smooth; the arc only breaks ties toward a good flow.
ARC_WEIGHT = 0.22
SHORT_BLEND_CAP_SECONDS = 6.0
LONG_BLEND_CAP_SECONDS = 16.0
SAFE_TEMPO_RATIO = (0.94, 1.06)


class MixPlanningError(Exception):
    """Raised when a mix plan cannot be created from the requested tracks."""


class MixPlanner:
    def __init__(
        self,
        compatibility_service: CompatibilityService | None = None,
        style_profile: DJStyleProfile | None = None,
    ) -> None:
        self.compatibility_service = compatibility_service or CompatibilityService()
        self.style_profile = style_profile

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
            self._auto_order(
                [analysis_by_id[track_id] for track_id in request.track_ids],
                request.mix_direction,
                locked=min(request.locked_track_count, len(request.track_ids)),
            )
            if request.auto_order
            else request.track_ids
        )
        tracks = [to_mixable_track(analysis_by_id[track_id]) for track_id in ordered_ids]

        target_seconds = request.target_duration_minutes * 60 if request.target_duration_minutes else None
        target_limit = (target_seconds / len(tracks)) if target_seconds else None
        per_track_limit = _per_track_limit(target_limit, request.max_play_seconds_per_track)
        play_windows = {
            track_id: recommend_play_window(analysis_by_id[track_id])
            for track_id in ordered_ids
        }

        placements: list[MixTrackPlacement] = []
        transitions: list[MixTransition] = []
        timeline_start = 0.0

        requested_transition_bars = (
            self.style_profile.default_transition_bars
            if request.use_trained_style and self.style_profile and request.transition_bars == 4
            else request.transition_bars
        )
        transition_bars = _direction_adjusted_transition_bars(requested_transition_bars, request.mix_direction)
        active_style_profile = self.style_profile if request.use_trained_style else None

        source_starts = [
            play_windows[track.track_id].start_seconds
            if per_track_limit is None
            else _choose_track_start(track, active_style_profile)
            for track in tracks
        ]

        pair_decisions = []
        history = TransitionHistory()
        for pair_index, (source_track, target_track) in enumerate(zip(tracks, tracks[1:], strict=False)):
            compatibility = self.compatibility_service.compare(
                analysis_by_id[source_track.track_id],
                analysis_by_id[target_track.track_id],
            )
            technique = choose_technique(
                source_track,
                target_track,
                compatibility.compatibility_score,
                request.mix_direction,
                history,
                set_position=(pair_index + 1) / len(tracks),
                long_blend_ok=_long_blend_pair_ok(
                    source_track, target_track, compatibility.compatibility_score, request.mix_direction
                ),
            )
            duration = _transition_duration_seconds(
                source_track,
                target_track,
                transition_bars,
                self.style_profile if request.use_trained_style else None,
                compatibility.compatibility_score,
                technique,
                request.mix_direction,
            )
            pair_decisions.append((compatibility, technique, duration))
            history.add(technique)

        for index, track in enumerate(tracks):
            source_start = source_starts[index]
            source_end = (
                play_windows[track.track_id].end_seconds
                if per_track_limit is None
                else _choose_track_end(track, source_start, per_track_limit)
            )
            transition_duration = 0.0

            if index < len(tracks) - 1:
                transition_duration = pair_decisions[index][2]
                source_end = _choose_transition_end(track, source_start, source_end, transition_duration, active_style_profile)
                if per_track_limit is None:
                    play_window = play_windows[track.track_id]
                    minimum_end_after_peak = min(
                        play_window.end_seconds,
                        play_window.peak_seconds + transition_duration + 4.0,
                    )
                    if source_end < minimum_end_after_peak:
                        boundary = _nearest_bar_after(track, minimum_end_after_peak)
                        source_end = min(
                            play_window.end_seconds,
                            boundary or minimum_end_after_peak,
                        )

            timeline_end = round(timeline_start + max(0.0, source_end - source_start), 3)
            placements.append(
                MixTrackPlacement(
                    track_id=track.track_id,
                    file_name=track.file_name,
                    title=track.title,
                    genre=track.genre,
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
                compatibility, technique, _ = pair_decisions[index]
                bpm_adjustment = (
                    0.0
                    if technique == "tempo_handoff"
                    else _bpm_adjustment_percent(track.bpm, next_track.bpm)
                )
                source_tempo_adjustment = (
                    _source_tempo_adjustment_percent(track.bpm, next_track.bpm)
                    if technique == "tempo_handoff"
                    else 0.0
                )
                target_start = source_starts[index + 1]
                loop_beats = _outgoing_loop_beats(technique, transition_duration, track.bpm)
                effects = _technique_effects(
                    _sfx_for_transition(
                        track,
                        next_track,
                        request.mix_direction,
                        request.use_transition_sfx,
                        active_style_profile,
                        compatibility.compatibility_score,
                    ),
                    technique,
                    request.use_transition_sfx,
                )
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
                        source_tempo_adjustment_percent=source_tempo_adjustment,
                        gain_adjustment_db=_gain_adjustment_db(track.overall_energy, next_track.overall_energy),
                        crossfade_curve="equal_power",
                        transition_type="crossfade",
                        technique=technique,
                        phrase_aligned=_is_phrase_boundary(track, transition_start),
                        outgoing_loop_beats=loop_beats,
                        outgoing_loop_seconds=_loop_seconds(loop_beats, track.bpm),
                        background_tail_seconds=_background_tail_seconds(technique, transition_duration),
                        bass_swap_position=_bass_swap_position(technique),
                        incoming_entry_position=TECHNIQUES[technique].incoming_entry,
                        beat_seconds=round(60.0 / (track.bpm or 120.0), 4),
                        compatibility_score=compatibility.compatibility_score,
                        sfx=effects,
                    )
                )
                timeline_start = round(timeline_end - transition_duration, 3)

        estimated_duration = placements[-1].timeline_end_time if placements else 0.0
        return MixPlan(
            mix_id=mix_id,
            mix_name=request.mix_name,
            mix_direction=request.mix_direction,
            use_transition_sfx=request.use_transition_sfx,
            max_play_seconds_per_track=per_track_limit,
            track_order=[track.track_id for track in tracks],
            placements=placements,
            transitions=transitions,
            estimated_duration_seconds=round(estimated_duration, 3),
            created_at=datetime.now(timezone.utc),
        )

    def _auto_order(
        self,
        analyses: list[TrackAnalysis],
        mix_direction: str | None = None,
        *,
        locked: int = 0,
    ) -> list[str]:
        """Order songs for the smoothest set that also follows the requested energy arc.

        Builds a pair-cost matrix from compatibility and energy flow, seeds candidate
        orders greedily from several starting songs, then polishes the best with
        2-opt segment reversals and single-song moves. The first ``locked`` songs stay put.
        """
        count = len(analyses)
        if locked >= count - 1:
            return [item.track_id for item in analyses]
        if count <= 2:
            return [item.track_id for item in sorted(analyses, key=lambda item: item.overall_rms_energy)]

        pair_cost = [[0.0] * count for _ in range(count)]
        for i, source in enumerate(analyses):
            for j, target in enumerate(analyses):
                if i == j:
                    continue
                compatibility = self.compatibility_service.compare(source, target).compatibility_score
                flow = energy_flow_fit(source.overall_rms_energy, target.overall_rms_energy, mix_direction)
                pair_cost[i][j] = (1.0 - compatibility) + (1.0 - flow) * 0.12

        energy_rank = _energy_ranks([item.overall_rms_energy for item in analyses])
        arc = [energy_arc_target(position / (count - 1), mix_direction) for position in range(count)]

        def total_cost(order: list[int]) -> float:
            transitions = sum(pair_cost[a][b] for a, b in zip(order, order[1:], strict=False))
            shape = sum(abs(energy_rank[index] - arc[position]) for position, index in enumerate(order))
            return transitions + ARC_WEIGHT * shape

        if locked:
            seeds = [list(range(locked))]
        else:
            by_fit = sorted(range(count), key=lambda index: abs(energy_rank[index] - arc[0]))
            seeds = [[start] for start in by_fit[: min(count, 6)]]

        best_order: list[int] | None = None
        best_cost = math.inf
        for seed in seeds:
            order = list(seed)
            remaining = set(range(count)) - set(seed)
            while remaining:
                position = len(order)
                current = order[-1]
                choice = min(
                    remaining,
                    key=lambda index: (
                        pair_cost[current][index] + ARC_WEIGHT * abs(energy_rank[index] - arc[position]),
                        index,
                    ),
                )
                order.append(choice)
                remaining.remove(choice)
            cost = total_cost(order)
            if cost < best_cost - 1e-9:
                best_order, best_cost = order, cost

        assert best_order is not None
        best_order, best_cost = _polish_order(best_order, best_cost, total_cost, fixed_prefix=locked)
        return [analyses[index].track_id for index in best_order]


def _polish_order(
    order,
    cost,
    total_cost,
    *,
    fixed_prefix: int = 0,
    max_rounds: int = 12,
    time_budget_seconds: float = 1.5,
):
    """Local search: reverse segments (2-opt) and move single songs while it helps.

    Stops early on a time budget so very large queues never stall a live re-plan.
    """
    count = len(order)
    deadline = time.monotonic() + time_budget_seconds
    for _ in range(max_rounds):
        if time.monotonic() > deadline:
            break
        improved = False
        for i in range(fixed_prefix, count - 1):
            for j in range(i + 1, count):
                candidate = order[:i] + order[i : j + 1][::-1] + order[j + 1 :]
                candidate_cost = total_cost(candidate)
                if candidate_cost < cost - 1e-9:
                    order, cost, improved = candidate, candidate_cost, True
        for i in range(fixed_prefix, count):
            for j in range(fixed_prefix, count):
                if i == j:
                    continue
                candidate = order[:i] + order[i + 1 :]
                candidate.insert(j, order[i])
                candidate_cost = total_cost(candidate)
                if candidate_cost < cost - 1e-9:
                    order, cost, improved = candidate, candidate_cost, True
        if not improved:
            break
    return order, cost


def _energy_ranks(energies: list[float]) -> list[float]:
    if len(energies) <= 1:
        return [0.5 for _ in energies]
    order = sorted(range(len(energies)), key=lambda index: (energies[index], index))
    ranks = [0.0] * len(energies)
    for rank, index in enumerate(order):
        ranks[index] = rank / (len(energies) - 1)
    return ranks


def to_mixable_track(analysis: TrackAnalysis) -> MixableTrack:
    return MixableTrack(
        track_id=analysis.track_id,
        file_name=analysis.file_name,
        title=analysis.title,
        genre=analysis.genre,
        duration_seconds=analysis.duration_seconds,
        bpm=analysis.estimated_bpm,
        key=analysis.key,
        overall_energy=analysis.overall_rms_energy,
        beat_timestamps=analysis.beats.beat_timestamps,
        approximate_bars=analysis.beats.approximate_bars,
        energy_curve=analysis.energy_curve,
    )


def select_transition_technique(
    source: MixableTrack,
    target: MixableTrack,
    compatibility_score: float,
    mix_direction: str | None,
) -> str:
    """Best single move for one pair (no set history), e.g. for recommendations."""
    return choose_technique(
        source,
        target,
        compatibility_score,
        mix_direction,
        long_blend_ok=_long_blend_pair_ok(source, target, compatibility_score, mix_direction),
    )


def _outgoing_loop_beats(technique: str, transition_duration: float, bpm: float | None) -> int:
    if technique != "loop_echo_out" or transition_duration < 2.0:
        return 0
    beat_seconds = 60.0 / (bpm or 120.0)
    return 4 if transition_duration >= beat_seconds * 6 else 2


def _loop_seconds(loop_beats: int, bpm: float | None) -> float:
    if loop_beats <= 0:
        return 0.0
    return round(loop_beats * (60.0 / (bpm or 120.0)), 3)


def _background_tail_seconds(technique: str, transition_duration: float) -> float:
    ratios = {
        "eq_blend": 0.7,
        "reverb_wash": 0.5,
        "roll_build": 0.0,
        "kill_cut": 0.0,
        "spinback": 0.0,
        "power_down": 0.0,
        "phrase_blend": 0.68,
        "echo_fade": 0.52,
        "filter_blend": 0.6,
        "tempo_handoff": 0.62,
        "bass_swap": 0.55,
        "loop_echo_out": 0.78,
        "drop_swap": 0.42,
        "quick_cut": 0.2,
    }
    return round(min(12.0, transition_duration * ratios.get(technique, 0.55)), 3)


def _bass_swap_position(technique: str) -> float:
    return {
        "eq_blend": 0.5,
        "reverb_wash": 0.5,
        "roll_build": 0.85,
        "kill_cut": 0.85,
        "spinback": 0.85,
        "power_down": 0.85,
        "phrase_blend": 0.58,
        "echo_fade": 0.52,
        "filter_blend": 0.57,
        "tempo_handoff": 0.58,
        "bass_swap": 0.62,
        "loop_echo_out": 0.56,
        "drop_swap": 0.46,
        "quick_cut": 0.38,
    }.get(technique, 0.5)


def _technique_effects(effects: list[str], technique: str, enabled: bool) -> list[str]:
    if not enabled:
        return []
    additions = {
        "eq_blend": [],
        "reverb_wash": [],
        "roll_build": ["reverb_riser"],
        "kill_cut": [],
        "spinback": [],
        "power_down": [],
        "phrase_blend": ["soft_sweep"],
        "echo_fade": ["echo_tail", "soft_sweep"],
        "filter_blend": ["filter_sweep"],
        "tempo_handoff": ["soft_sweep"],
        "bass_swap": ["filter_sweep"],
        "loop_echo_out": ["loop_roll", "echo_tail"],
        "drop_swap": ["reverse_swell", "impact"],
        "quick_cut": ["echo_freeze", "brake_cut"],
    }.get(technique, [])
    allowed = {
        "eq_blend": {"soft_sweep"},
        "reverb_wash": {"soft_sweep"},
        "roll_build": {"reverb_riser", "filter_sweep", "impact"},
        "kill_cut": {"impact"},
        "spinback": {"impact"},
        "power_down": {"impact"},
        "phrase_blend": {"soft_sweep", "filter_sweep"},
        "echo_fade": {"echo_tail", "soft_sweep"},
        "filter_blend": {"filter_sweep", "soft_sweep"},
        "tempo_handoff": {"soft_sweep", "echo_tail"},
        "bass_swap": {"filter_sweep", "soft_sweep"},
        "loop_echo_out": {"loop_roll", "echo_tail", "soft_sweep"},
        "drop_swap": {"reverse_swell", "reverb_riser", "impact"},
        "quick_cut": {"echo_freeze", "brake_cut"},
    }.get(technique, set())
    return [effect for effect in _unique_effects([*additions, *effects]) if effect in allowed][:3]


def _transition_duration_seconds(
    source: MixableTrack,
    target: MixableTrack,
    transition_bars: int,
    style_profile: DJStyleProfile | None = None,
    compatibility_score: float = 0.75,
    technique: str = "phrase_blend",
    mix_direction: str | None = None,
) -> float:
    bpm = source.bpm or target.bpm or 120.0
    beat_seconds = 60.0 / bpm
    bar_seconds = 4.0 * beat_seconds
    upper_limit = min(source.duration_seconds * 0.4, target.duration_seconds * 0.4)
    if upper_limit <= 0:
        return 0.0

    fixed_bars = TECHNIQUES[technique].fixed_bars if technique in TECHNIQUES else None
    if fixed_bars:
        # Moves that live on the last bar(s) of a phrase: exact bar length so the
        # next song lands on the "1". Two-bar moves drop to one bar at slow tempos.
        bars = fixed_bars if fixed_bars * bar_seconds <= 6.0 else max(1.0, fixed_bars / 2)
        return round(min(bars * bar_seconds, upper_limit), 3)

    phrase_request = (
        style_profile.transition_duration_seconds
        if style_profile
        else transition_bars * bar_seconds
    )
    tempo_delta = abs(effective_tempo_ratio(source.bpm, target.bpm) - 1.0) * bpm
    adaptive_target = _adaptive_transition_target(
        compatibility_score,
        tempo_delta,
        _energy_delta(source, target),
        technique,
        mix_direction,
    )
    requested = (phrase_request * 0.28) + (adaptive_target * 0.72)

    cap = SHORT_BLEND_CAP_SECONDS
    if _long_blend_ok(source, target, compatibility_score, technique, mix_direction):
        # Locked tempo and key: let the songs ride together like a real DJ blend.
        # A full EQ blend takes 8 bars when it fits; other blends take 4.
        cap = LONG_BLEND_CAP_SECONDS
        bars = 8 if technique == "eq_blend" and 8 * bar_seconds <= cap else 4
        requested = max(requested, min(cap, bars * bar_seconds))

    upper_bound = min(upper_limit, cap)
    minimum = min(2.5 if technique == "quick_cut" else 3.5, upper_bound)
    duration = max(min(requested, upper_bound), minimum)
    return round(_snap_to_grid(duration, bar_seconds, beat_seconds, minimum, upper_bound), 3)


def _long_blend_ok(
    source: MixableTrack,
    target: MixableTrack,
    compatibility_score: float,
    technique: str,
    mix_direction: str | None,
) -> bool:
    if technique not in {"eq_blend", "phrase_blend", "bass_swap", "filter_blend"}:
        return False
    return _long_blend_pair_ok(source, target, compatibility_score, mix_direction)


def _long_blend_pair_ok(
    source: MixableTrack,
    target: MixableTrack,
    compatibility_score: float,
    mix_direction: str | None,
) -> bool:
    """Tempo and key are locked tightly enough for the two songs to ride together."""
    if compatibility_score < 0.82:
        return False
    if not source.bpm or not target.bpm:
        return False
    if not 0.97 <= effective_tempo_ratio(source.bpm, target.bpm) <= 1.03:
        return False
    if key_score(source.key, target.key) < 0.85:
        return False
    direction = (mix_direction or "").lower()
    return not any(word in direction for word in ("quick", "fast cut", "short blend", "hip hop", "rap"))


def _snap_to_grid(duration: float, bar_seconds: float, beat_seconds: float, minimum: float, maximum: float) -> float:
    """Snap a blend length to whole bars (or whole beats) so it starts and ends on the grid."""
    for unit in (bar_seconds, beat_seconds):
        if unit <= 0:
            continue
        options = [math.floor(duration / unit) * unit, math.ceil(duration / unit) * unit]
        valid = [value for value in options if minimum - 1e-6 <= value <= maximum + 1e-6 and value > 0]
        if valid:
            return min(valid, key=lambda value: abs(value - duration))
    return duration


def _energy_delta(source: MixableTrack, target: MixableTrack) -> float:
    return abs(source.overall_energy - target.overall_energy) / max(source.overall_energy, target.overall_energy, 1e-9)


def _adaptive_transition_target(
    compatibility_score: float,
    tempo_delta: float,
    energy_delta: float,
    technique: str,
    mix_direction: str | None,
) -> float:
    technique_target = {
        "eq_blend": 6.0,
        "phrase_blend": 5.5,
        "echo_fade": 3.75,
        "filter_blend": 4.75,
        "tempo_handoff": 5.25,
        "bass_swap": 5.0,
        "loop_echo_out": 4.0,
        "drop_swap": 3.5,
        "quick_cut": 2.75,
    }.get(technique, 4.5)
    duration = technique_target
    if compatibility_score >= 0.86 and tempo_delta <= 2.5 and energy_delta <= 0.24:
        duration += 0.5
    elif compatibility_score < 0.68:
        duration -= 0.75
    if tempo_delta >= 7.0:
        duration = min(duration, 4.0)
    elif tempo_delta >= 4.5:
        duration = min(duration, 5.0)
    if energy_delta >= 0.42:
        duration = min(duration, 4.5)

    direction = (mix_direction or "").lower()
    if any(word in direction for word in ("quick", "fast cut", "short blend")):
        duration -= 0.75
    elif any(word in direction for word in ("smooth", "chill", "lounge")) and compatibility_score >= 0.76:
        duration += 0.25
    minimum = 2.5 if technique == "quick_cut" else 3.5
    return float(max(minimum, min(6.0, duration)))


def _per_track_limit(target_limit: float | None, max_play_seconds: float | None) -> float | None:
    limits = [limit for limit in (target_limit, max_play_seconds) if limit is not None]
    return min(limits) if limits else None


def _direction_adjusted_transition_bars(base_bars: int, mix_direction: str | None) -> int:
    if not mix_direction:
        return base_bars

    direction = mix_direction.lower()
    if any(word in direction for word in ("quick", "fast cut", "hip hop", "rap", "pop")):
        return min(base_bars, 2)
    if any(word in direction for word in ("ambient", "chill", "lounge", "smooth", "long blend")):
        return min(base_bars, 4)
    if any(word in direction for word in ("house", "techno", "edm", "trance", "dance")):
        return min(base_bars, 4)
    return base_bars


def _sfx_for_transition(
    source: MixableTrack,
    target: MixableTrack,
    mix_direction: str | None,
    enabled: bool,
    style_profile: DJStyleProfile | None = None,
    compatibility_score: float = 0.75,
) -> list[str]:
    if not enabled:
        return []

    if style_profile and style_profile.sfx_density < 0.22:
        return []

    profile_effects = style_profile.transition_effects if style_profile else []
    direction_effects = _direction_effect_palette(mix_direction)
    palette = _unique_effects([*profile_effects, *direction_effects])
    intensity = style_profile.effect_intensity if style_profile else 0.56
    energy_delta = _energy_delta(source, target)
    tempo_delta = abs(effective_tempo_ratio(source.bpm, target.bpm) - 1.0) * (source.bpm or 120.0)

    effects: list[str] = []
    direction = (mix_direction or "").lower()
    smooth_direction = any(word in direction for word in ("ambient", "chill", "lounge", "smooth"))

    if "filter_sweep" in palette:
        effects.append("soft_sweep" if smooth_direction and intensity < 0.5 else "filter_sweep")
    if "echo_tail" in palette and (intensity >= 0.28 or compatibility_score < 0.82 or tempo_delta >= 4):
        effects.append("echo_tail")
    if "echo_freeze" in palette and (compatibility_score < 0.76 or tempo_delta >= 5 or intensity >= 0.6):
        effects.append("echo_freeze")
    if "reverb_riser" in palette and (intensity >= 0.48 or energy_delta >= 0.22):
        effects.append("reverb_riser")
    if "reverse_swell" in palette and (intensity >= 0.5 or energy_delta >= 0.2):
        effects.append("reverse_swell")
    if "loop_roll" in palette and (intensity >= 0.42 or any(word in direction for word in ("hip hop", "rap", "quick", "cut"))):
        effects.append("loop_roll")
    if "brake_cut" in palette and not smooth_direction and any(word in direction for word in ("hip hop", "rap", "quick", "cut")):
        effects.append("brake_cut")
    if "impact" in palette and not smooth_direction and (intensity >= 0.45 or energy_delta >= 0.18 or compatibility_score < 0.68):
        effects.append("impact")

    if not effects:
        return ["soft_sweep"] if smooth_direction else ["filter_sweep"]
    return _unique_effects(effects)[:5]


def _direction_effect_palette(mix_direction: str | None) -> list[str]:
    direction = (mix_direction or "").lower()
    if any(word in direction for word in ("hip hop", "rap", "pop", "quick", "cut")):
        return ["loop_roll", "echo_tail", "echo_freeze", "brake_cut", "impact", "filter_sweep"]
    if any(word in direction for word in ("house", "techno", "edm", "trance", "dance", "club")):
        return ["filter_sweep", "echo_tail", "reverb_riser", "reverse_swell", "impact"]
    if any(word in direction for word in ("ambient", "chill", "lounge", "smooth")):
        return ["filter_sweep", "echo_tail", "reverb_riser", "reverse_swell"]
    return ["filter_sweep", "echo_tail", "reverse_swell", "impact"]


def _unique_effects(effects: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for effect in effects:
        if effect in seen:
            continue
        seen.add(effect)
        unique.append(effect)
    return unique


def _choose_track_start(track: MixableTrack, style_profile: DJStyleProfile | None = None) -> float:
    phrase_bars = style_profile.phrase_bars if style_profile else 4
    bar_candidates = [
        bar.start_time
        for bar in track.approximate_bars
        if 0.25 <= bar.start_time <= min(36.0, track.duration_seconds * 0.28)
    ]
    if bar_candidates:
        latest = max(bar_candidates)

        def score(candidate: float) -> float:
            energy = _energy_at_time(track, candidate)
            phrase_score = 1.0 if _is_phrase_boundary(track, candidate, phrase_bars) else 0.62
            energy_score = 1.0 - min(abs(energy - 0.58) / 0.58, 1.0)
            early_score = 1.0 - min(candidate / max(latest, 1.0), 1.0)
            change_score = _energy_change_near(track, candidate)
            return (phrase_score * 0.36) + (energy_score * 0.26) + (early_score * 0.23) + (change_score * 0.15)

        return round(max(bar_candidates, key=score), 3)

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
    style_profile: DJStyleProfile | None = None,
) -> float:
    phrase_bars = style_profile.phrase_bars if style_profile else 4
    cue_sensitivity = style_profile.cue_point_sensitivity if style_profile else 0.55
    minimum_end = min(track.duration_seconds, source_start + transition_duration + 1.0)
    latest_end = min(track.duration_seconds, max(current_end, minimum_end))
    earliest_start = min(latest_end, source_start + max(transition_duration, 8.0))
    latest_start = max(source_start, latest_end - transition_duration)
    start_candidates = [
        bar.start_time
        for bar in track.approximate_bars
        if earliest_start <= bar.start_time <= latest_start
    ]

    if start_candidates:
        segment_length = max(latest_end - source_start, 1.0)

        def start_score(candidate: float) -> float:
            energy = _energy_at_time(track, candidate)
            phrase_weight = 1.0 if _is_phrase_boundary(track, candidate, phrase_bars) else 0.58
            progress = (candidate - source_start) / segment_length
            change = _energy_change_near(track, candidate)
            low_energy = 1.0 - energy
            return (
                (phrase_weight * 0.34)
                + (low_energy * 0.22)
                + (progress * 0.18)
                + (change * cue_sensitivity * 0.2)
                + (_energy_drop_after(track, candidate, transition_duration) * 0.06)
            )

        best_start = max(start_candidates, key=start_score)
        return round(min(track.duration_seconds, best_start + transition_duration), 3)

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
            phrase_weight = 1.0 if _is_phrase_boundary(track, transition_start, phrase_bars) else 0.8
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


def _nearest_bar_after(track: MixableTrack, time_seconds: float) -> float | None:
    candidates = [
        bar.start_time
        for bar in track.approximate_bars
        if time_seconds <= bar.start_time <= track.duration_seconds
    ]
    if not candidates:
        return None
    return round(min(candidates), 3)


def _energy_at_time(track: MixableTrack, time_seconds: float) -> float:
    if not track.energy_curve:
        return 0.5
    return min(track.energy_curve, key=lambda point: abs(point.time - time_seconds)).energy


def _is_phrase_boundary(track: MixableTrack, time_seconds: float, phrase_bars: int = 4) -> bool:
    for bar in track.approximate_bars:
        if abs(bar.start_time - time_seconds) <= 0.05:
            return (bar.bar_number - 1) % max(1, phrase_bars) == 0
    return False


def _energy_change_near(track: MixableTrack, time_seconds: float) -> float:
    if len(track.energy_curve) < 2:
        return 0.0
    before = [point.energy for point in track.energy_curve if time_seconds - 4.0 <= point.time <= time_seconds]
    after = [point.energy for point in track.energy_curve if time_seconds < point.time <= time_seconds + 4.0]
    if not before or not after:
        return 0.0
    return min(1.0, abs((sum(after) / len(after)) - (sum(before) / len(before))) * 2.5)


def _energy_drop_after(track: MixableTrack, time_seconds: float, duration_seconds: float) -> float:
    start_energy = _energy_at_time(track, time_seconds)
    end_energy = _energy_at_time(track, min(track.duration_seconds, time_seconds + duration_seconds))
    return max(0.0, start_energy - end_energy)


def _bpm_adjustment_percent(source_bpm: float | None, target_bpm: float | None) -> float:
    """Stretch for the incoming song so it plays at the outgoing song's tempo."""
    if not source_bpm or not target_bpm:
        return 0.0
    return _safe_tempo_percent(1.0 / effective_tempo_ratio(source_bpm, target_bpm))


def _source_tempo_adjustment_percent(source_bpm: float | None, target_bpm: float | None) -> float:
    """Speed change for the outgoing song so it arrives at the incoming song's tempo."""
    if not source_bpm or not target_bpm:
        return 0.0
    return _safe_tempo_percent(effective_tempo_ratio(source_bpm, target_bpm))


def _safe_tempo_percent(ratio: float) -> float:
    if SAFE_TEMPO_RATIO[0] <= ratio <= SAFE_TEMPO_RATIO[1]:
        return round((ratio - 1.0) * 100.0, 3)
    return 0.0


def _gain_adjustment_db(source_energy: float, target_energy: float) -> float:
    if source_energy <= 1e-9 or target_energy <= 1e-9:
        return 0.0
    ratio = source_energy / target_energy
    return round(max(-6.0, min(6.0, 20.0 * math.log10(ratio))), 3)

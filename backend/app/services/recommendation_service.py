"""Rank which saved songs should play after the current one."""

from __future__ import annotations

from app.models.mix import NextTrackRecommendation, NextTrackRequest
from app.models.track import TrackAnalysis
from app.services.compatibility import (
    CompatibilityService,
    camelot_label,
    effective_tempo_ratio,
    key_relation,
)
from app.services.mix_planner import select_transition_technique, to_mixable_track
from app.services.vibe import energy_flow_fit, genre_matches_direction

_KEY_REASONS = {
    "same": "Same key {target}",
    "relative": "Relative key {source} -> {target}",
    "adjacent": "Harmonic neighbor {source} -> {target}",
    "energy_boost": "Key lift {source} -> {target}",
    "diagonal": "Mood shift {source} -> {target}",
    "semitone_lift": "Semitone key lift {source} -> {target}",
}

# Recently played genres get a small penalty so Auto DJ does not lock into one lane.
_REPEAT_GENRE_WINDOW = 4


class RecommendationService:
    def __init__(self, compatibility_service: CompatibilityService | None = None) -> None:
        self.compatibility_service = compatibility_service or CompatibilityService()

    def recommend_next(
        self,
        request: NextTrackRequest,
        current: TrackAnalysis,
        library: list[TrackAnalysis],
    ) -> list[NextTrackRecommendation]:
        played = set(request.played_track_ids)
        queued = set(request.queued_track_ids)
        by_id = {track.track_id: track for track in library}
        recent_genres = [
            by_id[track_id].genre.lower()
            for track_id in request.played_track_ids[-_REPEAT_GENRE_WINDOW:]
            if track_id in by_id
        ]

        results: list[NextTrackRecommendation] = []
        for candidate in library:
            if candidate.track_id == current.track_id or candidate.track_id in played:
                continue
            is_queued = candidate.track_id in queued
            if is_queued and not request.include_queued:
                continue
            results.append(self._score(current, candidate, request, recent_genres, is_queued))

        results.sort(key=lambda item: (-item.score, item.title.lower(), item.track_id))
        return results[: request.limit]

    def _score(
        self,
        current: TrackAnalysis,
        candidate: TrackAnalysis,
        request: NextTrackRequest,
        recent_genres: list[str],
        is_queued: bool,
    ) -> NextTrackRecommendation:
        compatibility = self.compatibility_service.compare(current, candidate)
        flow = energy_flow_fit(current.overall_rms_energy, candidate.overall_rms_energy, request.mix_direction)
        direction_match = genre_matches_direction(candidate.genre, request.mix_direction)

        score = compatibility.compatibility_score * 0.7 + flow * 0.2 + (0.1 if direction_match else 0.04)
        repeats = recent_genres.count(candidate.genre.lower())
        if repeats >= 3 and not direction_match:
            score -= 0.04
        score = max(0.0, min(1.0, score))

        source_mix = to_mixable_track(current)
        target_mix = to_mixable_track(candidate)
        technique = select_transition_technique(
            source_mix,
            target_mix,
            compatibility.compatibility_score,
            request.mix_direction,
        )
        relation = key_relation(current.key, candidate.key)
        energy_change = (candidate.overall_rms_energy - current.overall_rms_energy) / max(
            current.overall_rms_energy, 1e-9
        )
        return NextTrackRecommendation(
            track_id=candidate.track_id,
            title=candidate.title,
            file_name=candidate.file_name,
            genre=candidate.genre,
            bpm=candidate.estimated_bpm,
            key=candidate.key.display_name,
            camelot=camelot_label(candidate.key),
            score=round(score, 3),
            compatibility_score=compatibility.compatibility_score,
            energy_change_percent=round(max(-999.0, min(999.0, energy_change * 100.0)), 1),
            key_relation=relation,
            suggested_technique=technique,
            already_queued=is_queued,
            reasons=_reasons(current, candidate, relation, energy_change, direction_match),
        )


def _reasons(
    current: TrackAnalysis,
    candidate: TrackAnalysis,
    relation: str,
    energy_change: float,
    direction_match: bool,
) -> list[str]:
    reasons: list[str] = []
    if current.estimated_bpm and candidate.estimated_bpm:
        diff = candidate.estimated_bpm - current.estimated_bpm
        ratio = effective_tempo_ratio(current.estimated_bpm, candidate.estimated_bpm)
        folded = abs(diff) > abs(ratio - 1.0) * current.estimated_bpm + 1.0
        if folded and abs(ratio - 1.0) <= 0.06:
            reasons.append("Half/double-time tempo match")
        elif abs(diff) <= 1.0:
            reasons.append("Locked tempo")
        elif abs(diff) <= 6.0:
            reasons.append(f"{diff:+.0f} BPM")
        else:
            reasons.append(f"Tempo jump {diff:+.0f} BPM")

    source_camelot = camelot_label(current.key)
    target_camelot = camelot_label(candidate.key)
    template = _KEY_REASONS.get(relation)
    if template and source_camelot and target_camelot:
        reasons.append(template.format(source=source_camelot, target=target_camelot))
    elif relation == "clash":
        reasons.append("Key clash - short blend")

    if energy_change >= 0.12:
        reasons.append("Energy lift")
    elif energy_change <= -0.12:
        reasons.append("Energy drop")
    else:
        reasons.append("Steady energy")

    if direction_match:
        reasons.append(f"Fits the {candidate.genre} vibe")
    elif candidate.genre and candidate.genre == current.genre and candidate.genre != "Open Format":
        reasons.append(f"Stays in {candidate.genre}")
    return reasons

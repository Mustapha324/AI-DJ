from __future__ import annotations

import json
from datetime import datetime, timezone

from app.config import Settings, ensure_storage_dirs
from app.models.song_research import (
    ExternalResearchNote,
    MusicSourceRecommendation,
    RecommendedTransition,
    SongCue,
    SongPlayWindow,
    SongResearchRecord,
    TransitionStyle,
)
from app.models.track import ApproximateBar, EnergyPoint, TrackAnalysis
from app.services.compatibility import CompatibilityService


class SongResearchService:
    def __init__(
        self,
        settings: Settings,
        compatibility_service: CompatibilityService | None = None,
    ) -> None:
        self.settings = settings
        self.compatibility_service = compatibility_service or CompatibilityService()
        ensure_storage_dirs(settings)

    def build_track_research(
        self,
        track: TrackAnalysis,
        library: list[TrackAnalysis],
        *,
        save: bool = True,
    ) -> SongResearchRecord:
        mix_in_cues = _mix_in_cues(track)
        mix_out_cues = _mix_out_cues(track)
        play_window = recommend_play_window(track)
        record = SongResearchRecord(
            track_id=track.track_id,
            title=track.title,
            file_name=track.file_name,
            bpm=track.estimated_bpm,
            key=track.key.display_name,
            energy=round(track.overall_rms_energy, 5),
            likely_genres=_likely_genres(track),
            play_window=play_window,
            mix_in_cues=mix_in_cues,
            mix_out_cues=mix_out_cues,
            recommended_transitions=self._recommended_transitions(track, library, mix_out_cues, mix_in_cues),
            external_notes=_external_notes(track),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        if save:
            self.save(record)
        return record

    def save(self, record: SongResearchRecord) -> None:
        path = self.settings.song_research_dir / f"{record.track_id}.json"
        with path.open("w", encoding="utf-8") as output_file:
            json.dump(record.model_dump(mode="json"), output_file, indent=2)

    def get(self, track_id: str) -> SongResearchRecord | None:
        path = self.settings.song_research_dir / f"{track_id}.json"
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as input_file:
                return SongResearchRecord.model_validate(json.load(input_file))
        except (OSError, json.JSONDecodeError, ValueError):
            return None

    def legal_music_sources(self) -> list[MusicSourceRecommendation]:
        return [
            MusicSourceRecommendation(
                name="MassiveMusic / 7digital API",
                url="https://docs.massivemusic.com/docs/building-a-content-delivery-service",
                genres=["pop", "club", "house", "mainstream"],
                license_note="B2B catalog route with territory, usage-reporting, takedown, download, and streaming controls under contract.",
                import_note="Use only after a signed content-delivery agreement that allows app storage/playback and any analysis features.",
            ),
            MusicSourceRecommendation(
                name="Epidemic Sound Connect API",
                url="https://developers.epidemicsound.com/docs/getting-started/",
                genres=["pop", "club", "electronic", "background"],
                license_note="Commercial app integration requires appropriate paid/partner terms.",
                import_note="Use API-provided MP3 links only under the active integration license and rights ledger.",
            ),
            MusicSourceRecommendation(
                name="Jamendo",
                url="https://developer.jamendo.com/v3.0/tracks",
                genres=["pop", "club", "house", "electronic"],
                license_note="Tracks expose license fields and an audiodownload_allowed flag; obey each track license.",
                import_note="Use the API to filter by genre/tags, then import only tracks with allowed downloads.",
            ),
            MusicSourceRecommendation(
                name="Internet Archive",
                url="https://archive.org/details/audio",
                genres=["electronic", "dance", "live sets", "public domain"],
                license_note="Items have per-record license metadata; verify before import or redistribution.",
                import_note="Use direct MP3/WAV file links from items whose license allows your intended use.",
            ),
            MusicSourceRecommendation(
                name="Free Music Archive",
                url="https://freemusicarchive.org/",
                genres=["electronic", "pop", "dance"],
                license_note="Tracks use specific licenses shown per item; verify commercial/remix rights.",
                import_note="Import downloadable files only when the item license and download terms allow it.",
            ),
            MusicSourceRecommendation(
                name="Jamendo Licensing",
                url="https://licensing.jamendo.com/",
                genres=["pop", "club", "house", "background"],
                license_note="Paid royalty-free licensing with proof/certificate for covered uses.",
                import_note="Import purchased/licensed MP3/WAV files or authorized customer download links.",
            ),
            MusicSourceRecommendation(
                name="Beatport / Traxsource user library",
                url="https://support.beatport.com/hc/en-us/articles/4414997837716-Terms-and-Conditions",
                genres=["club", "house", "electronic"],
                license_note="Strong DJ catalog fit, but normal purchases are generally for personal/private use and not app redistribution.",
                import_note="Support user-owned local-library import; do not redistribute or bulk-download without separate rights.",
            ),
            MusicSourceRecommendation(
                name="DJ record pools",
                url="https://bpmmusic.io/terms",
                genres=["pop", "club", "open-format", "DJ edits"],
                license_note="Useful for pro DJs, usually with promotional/pool restrictions and no redistribution/sublicensing.",
                import_note="Allow manual user file import only; do not automate pool downloads.",
            ),
            MusicSourceRecommendation(
                name="Bandcamp",
                url="https://get.bandcamp.help/en/articles/15263234-in-which-formats-can-i-download-my-purchases",
                genres=["independent pop", "club", "house"],
                license_note="Downloads can be MP3/WAV/FLAC/AIFF, but app/commercial use needs artist/license permission.",
                import_note="Import user-owned files or artist-authorized direct links; store attribution/license evidence.",
            ),
            MusicSourceRecommendation(
                name="ccMixter / Freesound",
                url="https://ccmixter.org/about",
                genres=["remix", "samples", "loops", "electronic"],
                license_note="Per-item Creative Commons terms vary; prefer CC0/CC BY for broad use.",
                import_note="Import only items whose license allows DJ remixing, analysis, and the intended use.",
            ),
        ]

    def _recommended_transitions(
        self,
        source: TrackAnalysis,
        library: list[TrackAnalysis],
        source_cues: list[SongCue],
        fallback_target_cues: list[SongCue],
    ) -> list[RecommendedTransition]:
        recommendations: list[RecommendedTransition] = []
        source_cue = source_cues[0] if source_cues else _fallback_cue(source, "mix_out")

        for target in library:
            if target.track_id == source.track_id:
                continue
            compatibility = self.compatibility_service.compare(source, target)
            target_cues = _mix_in_cues(target)
            target_cue = target_cues[0] if target_cues else fallback_target_cues[0] if fallback_target_cues else _fallback_cue(target, "mix_in")
            style = _transition_style(source, target, compatibility.score_breakdown.tempo, compatibility.score_breakdown.key)
            recommendations.append(
                RecommendedTransition(
                    target_track_id=target.track_id,
                    target_title=target.title,
                    target_file_name=target.file_name,
                    compatibility_score=compatibility.compatibility_score,
                    suggested_style=style,
                    source_cue_seconds=source_cue.time_seconds,
                    target_cue_seconds=target_cue.time_seconds,
                    expected_sound=_expected_sound(style, source, target),
                    reason=_transition_reason(compatibility.score_breakdown.tempo, compatibility.score_breakdown.key, source, target),
                )
            )

        return sorted(recommendations, key=lambda item: item.compatibility_score, reverse=True)[:8]


def recommend_play_window(track: TrackAnalysis) -> SongPlayWindow:
    duration = max(0.0, track.duration_seconds)
    peak_seconds = _hype_point(track)
    genres = _likely_genres(track)
    is_club_track = any(genre in {"club/house", "dance"} for genre in genres)
    is_pop_track = "pop" in genres

    if duration <= 75.0:
        return SongPlayWindow(
            start_seconds=0.0,
            peak_seconds=round(peak_seconds, 3),
            end_seconds=round(duration, 3),
            play_seconds=round(duration, 3),
            reason="Short track: keep the full arrangement so its main section is not skipped.",
        )

    lead_seconds = 58.0 if is_club_track else 46.0 if is_pop_track else 52.0
    release_seconds = 42.0 if is_club_track else 34.0 if is_pop_track else 38.0
    minimum_play = 92.0 if is_club_track else 74.0 if is_pop_track else 82.0
    maximum_play = 160.0 if is_club_track else 132.0 if is_pop_track else 145.0

    desired_start = max(0.0, peak_seconds - lead_seconds)
    start_seconds = _phrase_boundary_near(track, desired_start, prefer_before=True)
    desired_end = max(peak_seconds + release_seconds, start_seconds + minimum_play)
    desired_end = min(duration, start_seconds + maximum_play, desired_end)
    end_seconds = _phrase_boundary_near(track, desired_end, prefer_before=False)
    end_seconds = min(duration, max(end_seconds, peak_seconds + 12.0, start_seconds + 45.0))

    if duration >= minimum_play and end_seconds - start_seconds < minimum_play:
        earlier_start = max(0.0, end_seconds - minimum_play)
        start_seconds = _phrase_boundary_near(track, earlier_start, prefer_before=True)
    if end_seconds - start_seconds > maximum_play:
        end_seconds = _phrase_boundary_near(track, start_seconds + maximum_play, prefer_before=True)
    if end_seconds <= start_seconds:
        start_seconds = 0.0
        end_seconds = duration

    label = "club/house" if is_club_track else "pop" if is_pop_track else "open-format"
    return SongPlayWindow(
        start_seconds=round(start_seconds, 3),
        peak_seconds=round(min(peak_seconds, duration), 3),
        end_seconds=round(end_seconds, 3),
        play_seconds=round(end_seconds - start_seconds, 3),
        reason=(
            f"Auto timing for {label}: enter before the strongest sustained section, "
            "let it land, then leave on a later phrase boundary."
        ),
    )


def _mix_in_cues(track: TrackAnalysis) -> list[SongCue]:
    bars = [
        bar
        for bar in track.beats.approximate_bars
        if 0.25 <= bar.start_time <= min(40.0, track.duration_seconds * 0.28)
    ]
    scored = sorted(((bar, _mix_in_score(track, bar)) for bar in bars), key=lambda item: item[1], reverse=True)
    return [_cue(track, bar, "mix_in", score, "Clean phrase-in point for bringing this song under the current track.") for bar, score in scored[:3]]


def _mix_out_cues(track: TrackAnalysis) -> list[SongCue]:
    earliest = min(track.duration_seconds * 0.35, 60.0)
    latest = max(earliest, track.duration_seconds - 8.0)
    bars = [bar for bar in track.beats.approximate_bars if earliest <= bar.start_time <= latest]
    scored = sorted(((bar, _mix_out_score(track, bar)) for bar in bars), key=lambda item: item[1], reverse=True)
    cues = [_cue(track, bar, "mix_out", score, "Phrase-safe exit point where the next track can become dominant.") for bar, score in scored[:4]]
    return cues or [_fallback_cue(track, "mix_out")]


def _mix_in_score(track: TrackAnalysis, bar: ApproximateBar) -> float:
    phrase = 1.0 if _is_phrase_boundary(bar, 4) else 0.55
    energy = _energy_at(track, bar.start_time)
    energy_fit = 1.0 - min(abs(energy - 0.55) / 0.55, 1.0)
    early = 1.0 - min(bar.start_time / max(min(track.duration_seconds * 0.28, 40.0), 1.0), 1.0)
    change = _energy_change_near(track, bar.start_time)
    return _clamp((phrase * 0.36) + (energy_fit * 0.25) + (early * 0.25) + (change * 0.14))


def _mix_out_score(track: TrackAnalysis, bar: ApproximateBar) -> float:
    phrase = 1.0 if _is_phrase_boundary(bar, 4) else 0.54
    energy = _energy_at(track, bar.start_time)
    low_energy = 1.0 - energy
    progress = min(bar.start_time / max(track.duration_seconds, 1.0), 1.0)
    change = _energy_change_near(track, bar.start_time)
    drop = max(0.0, energy - _energy_at(track, min(track.duration_seconds, bar.start_time + 8.0)))
    return _clamp((phrase * 0.34) + (low_energy * 0.22) + (progress * 0.18) + (change * 0.18) + (drop * 0.08))


def _cue(track: TrackAnalysis, bar: ApproximateBar, cue_type: str, score: float, notes: str) -> SongCue:
    return SongCue(
        cue_type=cue_type,
        time_seconds=round(bar.start_time, 3),
        confidence=round(score, 3),
        phrase_bar=bar.bar_number,
        energy=round(_energy_at(track, bar.start_time), 3),
        notes=notes,
    )


def _fallback_cue(track: TrackAnalysis, cue_type: str) -> SongCue:
    time_seconds = min(max(track.duration_seconds * (0.72 if cue_type == "mix_out" else 0.08), 0.0), track.duration_seconds)
    return SongCue(
        cue_type=cue_type,
        time_seconds=round(time_seconds, 3),
        confidence=0.32,
        phrase_bar=None,
        energy=round(_energy_at(track, time_seconds), 3),
        notes="Fallback cue because beat/bar detection did not provide enough phrase markers.",
    )


def _transition_style(source: TrackAnalysis, target: TrackAnalysis, tempo_score: float, key_score: float) -> TransitionStyle:
    energy_delta = _energy_delta(source, target)
    source_genres = _likely_genres(source)
    target_genres = _likely_genres(target)
    pop_pair = "pop" in source_genres or "pop" in target_genres
    dance_pair = any(genre in {"club/house", "dance"} for genre in [*source_genres, *target_genres])
    if tempo_score >= 0.9 and key_score >= 0.75 and dance_pair and energy_delta <= 0.3:
        return "long_eq_blend"
    if tempo_score >= 0.82 and energy_delta <= 0.25 and not pop_pair:
        return "bass_swap"
    if target.overall_rms_energy > source.overall_rms_energy * 1.18:
        return "drop_swap"
    if tempo_score < 0.65 or key_score < 0.5 or pop_pair:
        return "echo_cut"
    return "quick_cut"


def _expected_sound(style: TransitionStyle, source: TrackAnalysis, target: TrackAnalysis) -> str:
    if style == "long_eq_blend":
        return "Smooth extended overlap with gradual EQ movement and a clean bass handoff."
    if style == "bass_swap":
        return "Tight club blend where the low end changes on the phrase boundary."
    if style == "drop_swap":
        return "Energy lift: outgoing phrase releases into the incoming hook or drop."
    if style == "echo_cut":
        return "Shorter transition with an echo tail to hide tempo/key tension."
    return "Fast phrase-locked cut that keeps momentum without a long overlap."


def _transition_reason(tempo_score: float, key_score: float, source: TrackAnalysis, target: TrackAnalysis) -> str:
    parts: list[str] = []
    parts.append("tempo is close" if tempo_score >= 0.82 else "tempo needs help")
    parts.append("key is compatible" if key_score >= 0.7 else "key may clash")
    if target.overall_rms_energy > source.overall_rms_energy * 1.18:
        parts.append("target brings more energy")
    elif source.overall_rms_energy > target.overall_rms_energy * 1.18:
        parts.append("target cools the room down")
    else:
        parts.append("energy is similar")
    return ", ".join(parts) + "."


def _likely_genres(track: TrackAnalysis) -> list[str]:
    bpm = track.estimated_bpm or 0.0
    title = f"{track.title} {track.file_name}".lower()
    genres: list[str] = []
    if 118 <= bpm <= 132:
        genres.append("club/house")
    if 100 <= bpm < 118 or any(word in title for word in ("pop", "radio", "top")):
        genres.append("pop")
    if any(word in title for word in ("house", "club", "dance", "edm")):
        genres.append("dance")
    return genres or ["open-format"]


def _external_notes(track: TrackAnalysis) -> list[ExternalResearchNote]:
    query = "+".join(part for part in [track.title, "DJ transition"] if part)
    return [
        ExternalResearchNote(
            source_name="Manual/public tracklist research",
            source_url=f"https://www.google.com/search?q={query}",
            note="Use this as a metadata research trail only. Do not download or copy copyrighted audio without authorization.",
        )
    ]


def _hype_point(track: TrackAnalysis) -> float:
    if not track.energy_curve:
        return min(track.duration_seconds * 0.62, track.duration_seconds)

    lower = min(18.0, track.duration_seconds * 0.12)
    upper = max(lower, track.duration_seconds * 0.9)
    candidates = [point for point in track.energy_curve if lower <= point.time <= upper]
    if not candidates:
        candidates = track.energy_curve

    def score(point: EnergyPoint) -> float:
        sustained = _average_energy(
            candidate
            for candidate in track.energy_curve
            if abs(candidate.time - point.time) <= 5.0
        )
        rise = max(0.0, point.energy - _energy_at(track, max(0.0, point.time - 8.0)))
        arrangement_position = 1.0 - min(abs((point.time / max(track.duration_seconds, 1.0)) - 0.58), 0.58)
        return (point.energy * 0.62) + ((sustained or point.energy) * 0.23) + (rise * 0.1) + (arrangement_position * 0.05)

    return max(candidates, key=score).time


def _phrase_boundary_near(track: TrackAnalysis, target: float, *, prefer_before: bool) -> float:
    phrase_bars = [
        bar.start_time
        for bar in track.beats.approximate_bars
        if _is_phrase_boundary(bar, 4)
    ]
    if not phrase_bars:
        return max(0.0, min(target, track.duration_seconds))

    primary = [
        value
        for value in phrase_bars
        if (value <= target if prefer_before else value >= target)
    ]
    if primary:
        chosen = max(primary) if prefer_before else min(primary)
        if abs(chosen - target) <= 24.0:
            return chosen
    return min(phrase_bars, key=lambda value: abs(value - target))


def _is_phrase_boundary(bar: ApproximateBar, phrase_bars: int) -> bool:
    return (bar.bar_number - 1) % max(1, phrase_bars) == 0


def _energy_at(track: TrackAnalysis, time_seconds: float) -> float:
    if not track.energy_curve:
        return 0.5
    return min(track.energy_curve, key=lambda point: abs(point.time - time_seconds)).energy


def _energy_change_near(track: TrackAnalysis, time_seconds: float) -> float:
    if len(track.energy_curve) < 2:
        return 0.0
    before = _average_energy(point for point in track.energy_curve if time_seconds - 4.0 <= point.time <= time_seconds)
    after = _average_energy(point for point in track.energy_curve if time_seconds < point.time <= time_seconds + 4.0)
    if before is None or after is None:
        return 0.0
    return min(1.0, abs(after - before) * 2.5)


def _average_energy(points: object) -> float | None:
    energies = [point.energy for point in points if isinstance(point, EnergyPoint)]
    if not energies:
        return None
    return sum(energies) / len(energies)


def _house_tempo(track: TrackAnalysis) -> bool:
    return bool(track.estimated_bpm and 118 <= track.estimated_bpm <= 132)


def _energy_delta(source: TrackAnalysis, target: TrackAnalysis) -> float:
    high = max(source.overall_rms_energy, target.overall_rms_energy, 1e-9)
    return abs(source.overall_rms_energy - target.overall_rms_energy) / high


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))

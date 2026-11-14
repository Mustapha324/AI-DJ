from __future__ import annotations

import pytest

from app.models.track import ApproximateBar, BeatInfo, EnergyPoint, KeyEstimate, TrackAnalysis
from app.services.compatibility import (
    CompatibilityService,
    camelot_label,
    effective_tempo_ratio,
    key_relation,
    tempo_score,
)
from app.services.mix_planner import MixPlanner, _snap_to_grid, _transition_duration_seconds, to_mixable_track
from app.services.vibe import energy_arc_target, energy_goal, genre_matches_direction


def _key(root: str, mode: str = "minor", confidence: float = 0.9) -> KeyEstimate:
    return KeyEstimate(root=root, mode=mode, display_name=f"{root} {mode}", confidence=confidence)


def _track(
    track_id: str,
    *,
    bpm: float = 124.0,
    key: KeyEstimate | None = None,
    energy: float = 0.1,
    genre: str = "House",
    duration: float = 240.0,
) -> TrackAnalysis:
    beat = 60.0 / bpm
    beats = [round(index * beat, 3) for index in range(int(duration / beat))]
    bars = [
        ApproximateBar(
            bar_number=index + 1,
            start_beat=index * 4 + 1,
            end_beat=index * 4 + 4,
            start_time=beats[index * 4],
            end_time=beats[index * 4 + 4],
        )
        for index in range(len(beats) // 4 - 1)
    ]
    return TrackAnalysis(
        track_id=track_id,
        file_name=f"{track_id}.mp3",
        title=track_id,
        genre=genre,
        duration_seconds=duration,
        sample_rate=22050,
        estimated_bpm=bpm,
        beats=BeatInfo(beat_count=len(beats), beat_timestamps=beats, approximate_bars=bars),
        key=key or _key("A"),
        overall_rms_energy=energy,
        energy_curve=[EnergyPoint(time=float(t), energy=0.5) for t in range(0, int(duration), 4)],
        estimated_loudness_db=-12.0,
        zero_crossing_rate=0.05,
        spectral_centroid=1800.0,
        chroma_features={},
    )


def test_camelot_wheel_labels_and_relations():
    assert camelot_label(_key("A", "minor")) == "8A"
    assert camelot_label(_key("C", "major")) == "8B"
    assert camelot_label(_key("E", "minor")) == "9A"
    assert key_relation(_key("A", "minor"), _key("C", "major")) == "relative"
    assert key_relation(_key("A", "minor"), _key("E", "minor")) == "adjacent"
    assert key_relation(_key("A", "minor"), _key("B", "minor")) == "energy_boost"
    assert key_relation(_key("A", "minor"), _key("D#", "minor")) == "clash"


def test_half_and_double_time_tempos_count_as_matches():
    assert tempo_score(70.0, 140.0) > 0.85
    assert tempo_score(70.0, 100.0) < 0.5
    assert effective_tempo_ratio(70.0, 140.0) == pytest.approx(1.0)


def test_low_key_confidence_softens_key_penalties():
    service = CompatibilityService()
    sure = service.compare(_track("a", key=_key("A")), _track("b", key=_key("D#")))
    unsure = service.compare(
        _track("a", key=_key("A", confidence=0.05)),
        _track("b", key=_key("D#", confidence=0.05)),
    )
    assert unsure.score_breakdown.key > sure.score_breakdown.key


def test_vibe_reads_energy_goals():
    assert energy_goal("build it up to peak time") == 1
    assert energy_goal("chill lounge wind down") == -1
    assert energy_goal("smooth house") == 0
    assert energy_arc_target(0.75, None) == pytest.approx(1.0)
    assert energy_arc_target(0.0, None) < energy_arc_target(0.5, None)


def test_auto_order_keeps_harmonic_neighbors_together_and_builds_energy():
    tracks = [
        _track("peak", bpm=126, key=_key("B"), energy=0.2),
        _track("clash", bpm=100, key=_key("D#", "major"), energy=0.12, genre="Rock"),
        _track("warm", bpm=124, key=_key("A"), energy=0.06),
        _track("mid", bpm=125, key=_key("E"), energy=0.13),
    ]
    order = MixPlanner()._auto_order(tracks, "build the energy")

    # The misfit goes to an edge; the three harmonic house songs run back to back, building up.
    assert order[0] == "clash" or order[-1] == "clash"
    core = [track_id for track_id in order if track_id != "clash"]
    assert core == ["warm", "mid", "peak"]
    assert abs(order.index("warm") - order.index("peak")) == 2


def test_auto_order_can_lock_the_song_already_playing():
    tracks = [
        _track("playing", bpm=128, key=_key("A"), energy=0.3),
        _track("b", bpm=124, key=_key("E"), energy=0.05),
        _track("c", bpm=125, key=_key("A"), energy=0.1),
    ]
    order = MixPlanner()._auto_order(tracks, None, locked=1)

    assert order[0] == "playing"
    assert sorted(order) == ["b", "c", "playing"]


def test_locked_tempo_and_key_get_a_long_bar_aligned_blend():
    source = to_mixable_track(_track("a", bpm=128, key=_key("A")))
    target = to_mixable_track(_track("b", bpm=128, key=_key("A")))
    duration = _transition_duration_seconds(source, target, 4, None, 0.95, "bass_swap", "smooth house")
    bar = 4 * 60.0 / 128

    assert duration > 6.0
    assert duration <= 16.0
    assert (duration / bar) == pytest.approx(round(duration / bar), abs=1e-3)


def test_clashing_pairs_stay_short():
    source = to_mixable_track(_track("a", bpm=128, key=_key("A")))
    target = to_mixable_track(_track("b", bpm=128, key=_key("D#")))
    assert _transition_duration_seconds(source, target, 4, None, 0.7, "echo_fade", None) <= 6.0


def test_snap_to_grid_prefers_whole_bars():
    assert _snap_to_grid(5.9, 1.875, 0.46875, 3.5, 6.0) == pytest.approx(5.625)


def test_recommend_next_endpoint_ranks_and_excludes(client, make_synthetic_wav_bytes):
    uploads = [
        ("one.mp3", make_synthetic_wav_bytes(330.0, duration_seconds=6.0), "audio/mpeg"),
        ("two.mp3", make_synthetic_wav_bytes(440.0, duration_seconds=6.0), "audio/mpeg"),
        ("three.mp3", make_synthetic_wav_bytes(550.0, duration_seconds=6.0, pulse_period=0.4), "audio/mpeg"),
        ("four.mp3", make_synthetic_wav_bytes(660.0, duration_seconds=6.0, pulse_period=0.6), "audio/mpeg"),
    ]
    response = client.post("/api/tracks/analyze-batch", files=[("files", upload) for upload in uploads])
    ids = [track["track_id"] for track in response.json()["tracks"]]

    response = client.post(
        "/api/mixes/recommend-next",
        json={
            "current_track_id": ids[0],
            "played_track_ids": [ids[1]],
            "queued_track_ids": [ids[2]],
            "limit": 5,
        },
    )

    assert response.status_code == 200
    picks = response.json()
    assert [pick["track_id"] for pick in picks] == [ids[3]]
    assert picks[0]["reasons"]
    assert picks[0]["suggested_technique"]

    response = client.post(
        "/api/mixes/recommend-next",
        json={"current_track_id": ids[0], "queued_track_ids": [ids[2]], "include_queued": True},
    )
    picks = response.json()
    assert len(picks) == 3
    assert picks == sorted(picks, key=lambda pick: -pick["score"])
    assert any(pick["already_queued"] for pick in picks)


def test_recommend_next_unknown_track_is_404(client):
    response = client.post("/api/mixes/recommend-next", json={"current_track_id": "missing"})
    assert response.status_code == 404


def test_plan_keeps_locked_leading_tracks(client, synthetic_mp3_named_uploads):
    response = client.post(
        "/api/tracks/analyze-batch",
        files=[("files", upload) for upload in synthetic_mp3_named_uploads],
    )
    ids = [track["track_id"] for track in response.json()["tracks"]]
    for first in ids:
        plan = client.post(
            "/api/mixes/plan",
            json={"track_ids": [first, *[i for i in ids if i != first]], "auto_order": True, "locked_track_count": 1},
        ).json()
        assert plan["track_order"][0] == first


def test_auto_order_respects_a_locked_prefix():
    tracks = [_track(name, bpm=120 + index, energy=0.05 * (index + 1)) for index, name in enumerate("abcde")]
    order = MixPlanner()._auto_order(list(reversed(tracks)), None, locked=2)
    assert order[:2] == ["e", "d"]
    assert sorted(order) == list("abcde")


def test_vibe_genre_hints_match_library_tags():
    assert genre_matches_direction("Techno", "club energy all night")
    assert genre_matches_direction("Hip-Hop / Rap", "more hip hop cuts")
    assert not genre_matches_direction("Rock", "smooth house")
    assert not genre_matches_direction("House", None)

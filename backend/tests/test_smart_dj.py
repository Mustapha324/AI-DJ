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


def _music(seconds: float, bpm: float = 124.0, freq: float = 220.0, sr: int = 22050):
    import numpy as np

    t = np.arange(int(seconds * sr)) / sr
    phase = t % (60.0 / bpm)
    kick = np.sin(2 * np.pi * 55 * phase) * np.exp(-phase * 20) * 0.5
    return (kick + 0.2 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


@pytest.mark.parametrize(
    "technique",
    ["eq_blend", "kill_cut", "spinback", "power_down", "roll_build", "reverb_wash", "quick_cut", "bass_swap"],
)
def test_every_move_renders_cleanly(technique):
    import numpy as np

    from app.models.mix import MixTransition
    from app.services.mix_renderer import _append_with_crossfade
    from app.services.transition_selector import TECHNIQUES

    sr = 22050
    beat = 60.0 / 124.0
    bars = TECHNIQUES[technique].fixed_bars or 4
    duration = bars * 4 * beat
    transition = MixTransition(
        source_track_id="a",
        target_track_id="b",
        source_transition_start=10.0,
        source_transition_end=10.0 + duration,
        target_transition_start=0.0,
        target_transition_end=duration,
        timeline_start_time=10.0,
        timeline_end_time=10.0 + duration,
        duration_seconds=duration,
        bpm_adjustment_percent=0.0,
        gain_adjustment_db=0.0,
        crossfade_curve="equal_power",
        transition_type="crossfade",
        technique=technique,
        beat_seconds=beat,
        incoming_entry_position=TECHNIQUES[technique].incoming_entry,
        compatibility_score=0.8,
        sfx=["impact"],
    )
    current = _music(20.0)
    incoming = _music(20.0, freq=330.0)
    fade = int(duration * sr)
    mixed = _append_with_crossfade(current, incoming, fade, sr, transition)

    assert len(mixed) == len(current) + len(incoming) - fade
    assert np.isfinite(mixed).all()
    assert float(np.max(np.abs(mixed))) <= 1.0
    if TECHNIQUES[technique].incoming_entry >= 0.99:
        overlap_end = len(current)
        # Silence-ish right before the "1", then the new song at full level on it.
        assert float(np.max(np.abs(mixed[overlap_end - 40 : overlap_end]))) < 0.25
        assert float(np.max(np.abs(mixed[overlap_end : overlap_end + sr // 4]))) > 0.3


def test_party_set_uses_varied_moves_without_repeats():
    tracks = [
        _track("h1", bpm=124, key=_key("A"), energy=0.08, genre="House"),
        _track("h2", bpm=125, key=_key("E"), energy=0.1, genre="House"),
        _track("r1", bpm=92, key=_key("C", "major"), energy=0.12, genre="Hip-Hop / Rap"),
        _track("p1", bpm=118, key=_key("G", "major"), energy=0.2, genre="Pop"),
        _track("r2", bpm=96, key=_key("F#"), energy=0.15, genre="Hip-Hop / Rap"),
        _track("t1", bpm=128, key=_key("D"), energy=0.25, genre="Techno"),
        _track("l1", bpm=100, key=_key("B", "major"), energy=0.18, genre="Latin"),
    ]
    from app.models.mix import MixPlanRequest

    plan = MixPlanner().create_plan(
        MixPlanRequest(track_ids=[t.track_id for t in tracks], mix_direction="open format party", use_trained_style=False),
        tracks,
        "mix",
    )
    techniques = [transition.technique for transition in plan.transitions]
    assert all(a != b for a, b in zip(techniques, techniques[1:]))
    assert len(set(techniques)) >= 4
    gimmicks = [name for name in techniques if name in {"spinback", "power_down"}]
    assert len(gimmicks) <= 2


def test_smooth_vibe_avoids_hard_cuts():
    tracks = [
        _track(f"s{index}", bpm=122 + index * 0.5, key=_key(root), energy=0.08 + index * 0.01, genre="House")
        for index, root in enumerate(["A", "E", "B", "F#", "C#"])
    ]
    from app.models.mix import MixPlanRequest

    plan = MixPlanner().create_plan(
        MixPlanRequest(track_ids=[t.track_id for t in tracks], mix_direction="smooth deep house", use_trained_style=False),
        tracks,
        "mix",
    )
    hard = {"kill_cut", "spinback", "power_down", "quick_cut", "roll_build"}
    assert not hard & {transition.technique for transition in plan.transitions}


@pytest.mark.parametrize(
    ("direction", "expected"),
    [("throw in a spinback", "spinback"), ("power down the record", "power_down"), ("reverb wash out", "reverb_wash"),
     ("loop roll build up", "roll_build"), ("slam it on the one", "kill_cut")],
)
def test_new_moves_can_be_requested(direction, expected):
    from app.models.mix import MixPlanRequest

    tracks = [_track("a", bpm=124, key=_key("A")), _track("b", bpm=124, key=_key("E"))]
    plan = MixPlanner().create_plan(
        MixPlanRequest(track_ids=["a", "b"], auto_order=False, mix_direction=direction, use_trained_style=False),
        tracks,
        "mix",
    )
    assert plan.transitions[0].technique == expected

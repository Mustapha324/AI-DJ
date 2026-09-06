from __future__ import annotations

import numpy as np
import pytest

from app.services.mix_planner import _adaptive_transition_target, _source_tempo_adjustment_percent
from app.services.mix_renderer import _repeat_with_crossfade, _tempo_ramp_outgoing


def _analyze_three_tracks(client, synthetic_mp3_named_uploads) -> list[str]:
    response = client.post(
        "/api/tracks/analyze-batch",
        files=[("files", upload) for upload in synthetic_mp3_named_uploads],
    )
    assert response.status_code == 201
    return [track["track_id"] for track in response.json()["tracks"]]


def test_repeated_transition_loop_crossfades_its_seams():
    snippet = np.linspace(-0.8, 0.8, 240, dtype=np.float32)
    repeated = _repeat_with_crossfade(snippet, 1200, 36)

    assert len(repeated) == 1200
    assert float(np.max(np.abs(np.diff(repeated)))) < 0.2


def test_tempo_handoff_adjusts_song_one_only_within_a_safe_range():
    adjustment = _source_tempo_adjustment_percent(120.0, 125.0)

    assert adjustment == pytest.approx(4.1667, abs=0.001)
    assert _source_tempo_adjustment_percent(100.0, 140.0) == 0.0


def test_rendered_tempo_handoff_uses_a_gradual_speed_curve():
    audio = np.sin(np.linspace(0.0, 24.0 * np.pi, 2400, dtype=np.float32))
    ramped = _tempo_ramp_outgoing(audio, 4.0)

    assert len(ramped) == len(audio)
    assert np.isfinite(ramped).all()
    assert not np.allclose(ramped, audio)


def test_transition_time_adapts_to_the_song_pair():
    close_match = _adaptive_transition_target(0.92, 1.0, 0.08, "phrase_blend", "smooth and clean")
    difficult_match = _adaptive_transition_target(0.58, 10.0, 0.55, "loop_echo_out", None)
    quick_match = _adaptive_transition_target(0.82, 2.0, 0.12, "quick_cut", "short blend")

    assert 5.0 <= close_match <= 6.0
    assert 2.5 <= difficult_match <= 4.0
    assert quick_match < close_match


@pytest.mark.parametrize(
    ("direction", "expected_technique"),
    [
        ("repeat the ending", "loop_echo_out"),
        ("clean fade", "phrase_blend"),
        ("echo out", "echo_fade"),
        ("filter blend", "filter_blend"),
        ("bass swap", "bass_swap"),
        ("drop into the next song", "drop_swap"),
        ("quick cut", "quick_cut"),
        ("speed up song one to match song two", "tempo_handoff"),
    ],
)
def test_requested_transition_families_remain_available(
    client,
    synthetic_mp3_named_uploads,
    direction,
    expected_technique,
):
    track_ids = _analyze_three_tracks(client, synthetic_mp3_named_uploads)
    response = client.post(
        "/api/mixes/plan",
        json={
            "track_ids": track_ids[:2],
            "mix_name": f"{expected_technique} test",
            "auto_order": False,
            "mix_direction": direction,
        },
    )

    assert response.status_code == 201
    assert response.json()["transitions"][0]["technique"] == expected_technique


def test_mix_plan_creation_and_transition_timing(client, synthetic_mp3_named_uploads):
    track_ids = _analyze_three_tracks(client, synthetic_mp3_named_uploads)

    response = client.post(
        "/api/mixes/plan",
        json={
            "track_ids": track_ids,
            "mix_name": "First AI Mix",
            "transition_bars": 1,
            "max_play_seconds_per_track": 45,
            "auto_order": True,
            "mix_direction": "smooth house with club energy",
            "use_transition_sfx": True,
        },
    )

    assert response.status_code == 201
    plan = response.json()
    assert plan["mix_name"] == "First AI Mix"
    assert sorted(plan["track_order"]) == sorted(track_ids)
    assert plan["mix_direction"] == "smooth house with club energy"
    assert plan["use_transition_sfx"] is True
    assert plan["max_play_seconds_per_track"] == 45
    assert len(plan["placements"]) == 3
    assert len(plan["transitions"]) == 2
    techniques = [transition["technique"] for transition in plan["transitions"]]
    assert len(set(techniques)) == len(techniques)
    for transition in plan["transitions"]:
        assert transition["source_transition_start"] < transition["source_transition_end"]
        assert transition["timeline_start_time"] < transition["timeline_end_time"]
        assert transition["target_transition_start"] >= 0.0
        assert transition["target_transition_end"] > transition["target_transition_start"]
        assert transition["duration_seconds"] > 0
        assert transition["duration_seconds"] <= 6
        assert transition["technique"] in {
            "phrase_blend",
            "echo_fade",
            "filter_blend",
            "bass_swap",
            "loop_echo_out",
            "drop_swap",
            "quick_cut",
            "tempo_handoff",
        }
        assert 0.15 <= transition["bass_swap_position"] <= 0.85
        assert transition["background_tail_seconds"] >= 0
        if transition["technique"] == "loop_echo_out":
            assert transition["outgoing_loop_beats"] in {2, 4}
            assert transition["outgoing_loop_seconds"] > 0
        assert len(transition["sfx"]) <= 3
        if transition["technique"] == "bass_swap":
            assert "filter_sweep" in transition["sfx"]
        if transition["technique"] == "phrase_blend":
            assert "soft_sweep" in transition["sfx"]
    for placement in plan["placements"]:
        assert placement["source_end_time"] - placement["source_start_time"] <= 45


def test_render_mix_creates_nonempty_audio_and_streams_it(client, synthetic_mp3_named_uploads):
    track_ids = _analyze_three_tracks(client, synthetic_mp3_named_uploads)
    plan_response = client.post(
        "/api/mixes/plan",
        json={
            "track_ids": track_ids[:2],
            "mix_name": "Rendered Test Mix",
            "transition_bars": 1,
            "auto_order": False,
        },
    )
    mix_id = plan_response.json()["mix_id"]

    render_response = client.post("/api/mixes/render", json={"mix_id": mix_id})

    assert render_response.status_code == 201
    record = render_response.json()
    assert record["status"] == "completed"
    assert record["output_filename"].endswith(".wav")
    assert record["duration_seconds"] > 0

    audio_response = client.get(f"/api/mixes/{mix_id}/audio")

    assert audio_response.status_code == 200
    assert len(audio_response.content) > 44
    assert audio_response.headers["content-type"].startswith("audio/wav")


def test_render_mix_failure_is_reported(client, synthetic_mp3_named_uploads):
    track_ids = _analyze_three_tracks(client, synthetic_mp3_named_uploads)
    plan_response = client.post(
        "/api/mixes/plan",
        json={
            "track_ids": track_ids[:2],
            "mix_name": "Broken Render",
            "transition_bars": 1,
            "auto_order": False,
        },
    )
    plan = plan_response.json()
    plan["placements"][0]["track_id"] = "f" * 32

    render_response = client.post("/api/mixes/render", json={"plan": plan})

    assert render_response.status_code == 422
    assert "was not found" in render_response.json()["detail"]


def test_mix_and_job_records_can_be_retrieved(client, synthetic_mp3_named_uploads):
    track_ids = _analyze_three_tracks(client, synthetic_mp3_named_uploads)
    plan_response = client.post(
        "/api/mixes/plan",
        json={
            "track_ids": track_ids[:2],
            "mix_name": "Record Test Mix",
            "transition_bars": 1,
        },
    )
    mix_id = plan_response.json()["mix_id"]

    render_response = client.post("/api/mixes/render", json={"mix_id": mix_id})
    record = render_response.json()
    mix_response = client.get(f"/api/mixes/{mix_id}")
    job_response = client.get(f"/api/jobs/{record['job_id']}")

    assert mix_response.status_code == 200
    assert mix_response.json()["status"] == "completed"
    assert job_response.status_code == 200
    assert job_response.json()["status"] == "completed"


def test_train_style_profile_from_reference_mix(client, synthetic_reference_mix_bytes):
    response = client.post(
        "/api/style-profiles/train",
        data={"name": "Test Reference Style"},
        files=[("files", ("reference-set.mp3", synthetic_reference_mix_bytes, "audio/mpeg"))],
    )

    assert response.status_code == 201
    profile = response.json()
    assert profile["profile_id"] == "default"
    assert profile["name"] == "Test Reference Style"
    assert profile["reference_count"] == 1
    assert profile["max_play_seconds_per_track"] >= 15
    assert profile["default_transition_bars"] in {4, 8, 12, 16}
    assert profile["effect_intensity"] > 0
    assert "filter_sweep" in profile["transition_effects"]
    assert profile["transition_start_strategy"] in {"phrase_boundary_low_energy", "energy_change_cue"}
    assert 0 <= profile["cue_point_sensitivity"] <= 1

    default_response = client.get("/api/style-profiles/default")

    assert default_response.status_code == 200
    assert default_response.json()["reference_count"] == 1


def test_mix_plan_uses_trained_style_defaults(client, synthetic_mp3_named_uploads, synthetic_reference_mix_bytes):
    train_response = client.post(
        "/api/style-profiles/train",
        data={"name": "Learned Style"},
        files=[("files", ("reference-set.mp3", synthetic_reference_mix_bytes, "audio/mpeg"))],
    )
    assert train_response.json()["max_play_seconds_per_track"] >= 15
    track_ids = _analyze_three_tracks(client, synthetic_mp3_named_uploads)

    response = client.post(
        "/api/mixes/plan",
        json={
            "track_ids": track_ids[:2],
            "mix_name": "Styled Mix",
            "auto_order": False,
            "use_trained_style": True,
        },
    )

    assert response.status_code == 201
    plan = response.json()
    assert plan["max_play_seconds_per_track"] is None
    for placement in plan["placements"]:
        assert placement["source_end_time"] > placement["source_start_time"]

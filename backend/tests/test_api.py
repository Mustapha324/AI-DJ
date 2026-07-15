from __future__ import annotations


def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_easy_mode_page_loads(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "Easy Mode" in response.text
    assert "/docs" in response.text


def test_invalid_file_type(client):
    response = client.post(
        "/api/tracks/analyze",
        files={"file": ("notes.txt", b"not audio", "text/plain")},
    )

    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_analyze_track_and_retrieve_saved_track(client, synthetic_wav_bytes):
    upload_response = client.post(
        "/api/tracks/analyze",
        files={"file": ("test_song.wav", synthetic_wav_bytes, "audio/wav")},
    )

    assert upload_response.status_code == 201
    analysis = upload_response.json()
    track_id = analysis["track_id"]
    assert analysis["file_name"] == "test_song.wav"
    assert analysis["title"] == "test song"
    assert analysis["duration_seconds"] > 0
    assert analysis["energy_curve"]
    assert analysis["beats"]["beat_count"] == len(analysis["beats"]["beat_timestamps"])

    get_response = client.get(f"/api/tracks/{track_id}")

    assert get_response.status_code == 200
    assert get_response.json()["track_id"] == track_id


def test_list_tracks_returns_saved_analysis(client, synthetic_wav_bytes):
    client.post(
        "/api/tracks/analyze",
        files={"file": ("listed_song.wav", synthetic_wav_bytes, "audio/wav")},
    )

    response = client.get("/api/tracks")

    assert response.status_code == 200
    tracks = response.json()
    assert len(tracks) == 1
    assert tracks[0]["title"] == "listed song"


def test_missing_track_id(client):
    response = client.get("/api/tracks/00000000000000000000000000000000")

    assert response.status_code == 404
    assert "was not found" in response.json()["detail"]


def test_batch_upload_multiple_valid_mp3_files(client, synthetic_mp3_named_uploads):
    response = client.post(
        "/api/tracks/analyze-batch",
        files=[("files", upload) for upload in synthetic_mp3_named_uploads],
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["total_files"] == 3
    assert payload["successful"] == 3
    assert payload["failed"] == 0
    assert payload["duplicates"] == 0
    assert len(payload["tracks"]) == 3
    assert all(track["status"] == "analyzed" for track in payload["tracks"])
    assert payload["job_id"]


def test_batch_upload_continues_when_some_files_fail(client, synthetic_mp3_named_uploads, test_settings):
    response = client.post(
        "/api/tracks/analyze-batch",
        files=[
            ("files", synthetic_mp3_named_uploads[0]),
            ("files", ("notes.txt", b"not audio", "text/plain")),
            ("files", ("broken.mp3", b"not actually audio", "audio/mpeg")),
        ],
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["successful"] == 1
    assert payload["failed"] == 2
    assert payload["duplicates"] == 0
    assert len(payload["tracks"]) == 1
    assert {error["file_name"] for error in payload["errors"]} == {"notes.txt", "broken.mp3"}
    assert len(list(test_settings.uploads_dir.glob("*"))) == 1


def test_batch_upload_detects_duplicates(client, make_synthetic_wav_bytes):
    audio = make_synthetic_wav_bytes(440.0)
    response = client.post(
        "/api/tracks/analyze-batch",
        files=[
            ("files", ("copy-one.mp3", audio, "audio/mpeg")),
            ("files", ("copy-two.mp3", audio, "audio/mpeg")),
        ],
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["successful"] == 1
    assert payload["duplicates"] == 1
    assert payload["tracks"][0]["track_id"] == payload["tracks"][1]["track_id"]


def test_batch_upload_rejects_unsupported_format(client, synthetic_wav_bytes):
    response = client.post(
        "/api/tracks/analyze-batch",
        files=[("files", ("song.wav", synthetic_wav_bytes, "audio/wav"))],
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["successful"] == 0
    assert payload["failed"] == 1
    assert "Unsupported file type" in payload["errors"][0]["error"]


def test_compatible_tracks_are_returned_in_score_order(client, synthetic_mp3_named_uploads):
    upload_response = client.post(
        "/api/tracks/analyze-batch",
        files=[("files", upload) for upload in synthetic_mp3_named_uploads],
    )
    track_id = upload_response.json()["tracks"][0]["track_id"]

    response = client.get(f"/api/tracks/{track_id}/compatible")

    assert response.status_code == 200
    matches = response.json()
    assert len(matches) == 2
    assert matches[0]["compatibility_score"] >= matches[1]["compatibility_score"]
    assert set(matches[0]["score_breakdown"]) == {"tempo", "key", "energy", "structure"}


def test_search_tracks_returns_saved_library_matches(client, synthetic_mp3_named_uploads):
    client.post(
        "/api/tracks/analyze-batch",
        files=[("files", upload) for upload in synthetic_mp3_named_uploads],
    )

    response = client.get("/api/tracks/search", params={"query": "alpha"})

    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["file_name"] == "alpha.mp3"


def test_saved_track_audio_can_be_retrieved(client, synthetic_mp3_named_uploads):
    upload_response = client.post(
        "/api/tracks/analyze-batch",
        files=[("files", synthetic_mp3_named_uploads[0])],
    )
    track_id = upload_response.json()["tracks"][0]["track_id"]

    response = client.get(f"/api/tracks/{track_id}/audio")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert len(response.content) > 44

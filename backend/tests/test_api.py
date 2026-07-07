from __future__ import annotations


def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


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

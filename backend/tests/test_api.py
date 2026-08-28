from __future__ import annotations


def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_party_mode_page_loads(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "Party Mode" in response.text
    assert "Studio Mode" in response.text
    assert 'class="turntable-visual"' in response.text
    assert 'id="genreFilter"' in response.text
    assert 'id="transitionSeconds" type="number" min="2" max="12" step="1" value="6"' in response.text
    assert "/docs" in response.text


def test_live_deck_effects_cannot_break_the_transition(client):
    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert "function scheduleBrowserImpact(context, impactTime)" in response.text
    assert "scheduleBrowserImpact(context, transitionStart + transitionSeconds - 0.04)" in response.text
    assert 'console.warn("A live DJ effect was skipped so the transition could continue."' in response.text
    assert "function scheduleOutgoingLoopBed(track, transitionStart, transitionSeconds, planned)" in response.text
    assert "function scheduleBassHandoff(gainParam, startTime, duration, swapPosition, incoming)" in response.text
    assert "function scheduleTechniqueFilters(outgoingChannel, incomingChannel" in response.text
    assert 'echo_fade: "echo fade"' in response.text
    assert 'filter_blend: "filter blend"' in response.text
    assert "gainParam.setValueCurveAtTime(curve" in response.text
    assert "oldSource.stop(now + transition" in response.text
    assert "Math.min(0.45, transition * 0.18)" not in response.text
    assert "transition_bars: 4" in response.text


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
    assert analysis["genre"]
    assert analysis["genre_source"] in {"embedded", "filename", "audio_profile", "fallback"}
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


def test_single_upload_does_not_duplicate_existing_library_track(client, make_synthetic_wav_bytes, test_settings):
    audio = make_synthetic_wav_bytes(440.0)
    first_response = client.post(
        "/api/tracks/analyze",
        files={"file": ("original.mp3", audio, "audio/mpeg")},
    )
    duplicate_response = client.post(
        "/api/tracks/analyze",
        files={"file": ("renamed-copy.mp3", audio, "audio/mpeg")},
    )

    assert first_response.status_code == 201
    assert duplicate_response.status_code == 201
    assert duplicate_response.json()["track_id"] == first_response.json()["track_id"]
    assert len(client.get("/api/tracks").json()) == 1
    assert len(list(test_settings.uploads_dir.glob("*"))) == 1


def test_batch_upload_detects_same_audio_with_different_file_bytes(client, make_synthetic_wav_bytes):
    audio = make_synthetic_wav_bytes(440.0)
    response = client.post(
        "/api/tracks/analyze-batch",
        files=[
            ("files", ("club-track.mp3", audio, "audio/mpeg")),
            ("files", ("club-track-copy.mp3", audio + b"\x00\x00metadata-padding", "audio/mpeg")),
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


def test_import_url_rejects_youtube_links(client):
    response = client.post(
        "/api/tracks/import-url",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    )

    assert response.status_code == 400
    assert "YouTube links cannot be imported" in response.json()["detail"]


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


def test_library_can_filter_tracks_by_automatic_genre(client, make_synthetic_wav_bytes):
    uploads = [
        ("deep-house-groove.mp3", make_synthetic_wav_bytes(330.0), "audio/mpeg"),
        ("late-night-jazz.mp3", make_synthetic_wav_bytes(550.0), "audio/mpeg"),
    ]
    upload_response = client.post(
        "/api/tracks/analyze-batch",
        files=[("files", upload) for upload in uploads],
    )
    assert upload_response.status_code == 201

    response = client.get("/api/tracks/search", params={"genre": "House"})

    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["genre"] == "House"
    assert results[0]["genre_source"] == "filename"


def test_library_genre_can_be_corrected_and_filtered(client, make_synthetic_wav_bytes):
    upload_response = client.post(
        "/api/tracks/analyze",
        files={"file": ("uncertain-track.mp3", make_synthetic_wav_bytes(440.0), "audio/mpeg")},
    )
    track_id = upload_response.json()["track_id"]

    update_response = client.patch(f"/api/tracks/{track_id}/genre", json={"genre": "Alternative R&B"})

    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["genre"] == "Alternative R&B"
    assert updated["genre_source"] == "manual"
    assert updated["genre_confidence"] == 1.0
    filtered = client.get("/api/tracks/search", params={"genre": "Alternative R&B"}).json()
    assert [track["track_id"] for track in filtered] == [track_id]


def test_song_research_returns_cues_and_pairings(client, synthetic_mp3_named_uploads):
    upload_response = client.post(
        "/api/tracks/analyze-batch",
        files=[("files", upload) for upload in synthetic_mp3_named_uploads],
    )
    track_id = upload_response.json()["tracks"][0]["track_id"]

    response = client.get(f"/api/tracks/{track_id}/research")

    assert response.status_code == 200
    research = response.json()
    assert research["track_id"] == track_id
    assert research["mix_in_cues"]
    assert research["mix_out_cues"]
    assert research["recommended_transitions"]
    assert research["external_notes"]
    assert research["play_window"]["start_seconds"] <= research["play_window"]["peak_seconds"]
    assert research["play_window"]["peak_seconds"] <= research["play_window"]["end_seconds"]
    assert research["play_window"]["play_seconds"] > 0


def test_batch_import_automatically_saves_song_research(client, synthetic_mp3_named_uploads, test_settings):
    response = client.post(
        "/api/tracks/analyze-batch",
        files=[("files", synthetic_mp3_named_uploads[0])],
    )

    assert response.status_code == 201
    track_id = response.json()["tracks"][0]["track_id"]
    research_path = test_settings.song_research_dir / f"{track_id}.json"
    assert research_path.exists()


def test_legal_music_sources_endpoint(client):
    response = client.get("/api/tracks/music-sources")

    assert response.status_code == 200
    sources = response.json()
    assert sources
    assert any(source["name"] == "Jamendo" for source in sources)


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

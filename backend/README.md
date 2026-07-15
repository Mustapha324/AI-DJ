# AI DJ Backend

This backend analyzes uploaded tracks, compares musical compatibility, creates a deterministic DJ mix plan, and renders a playable WAV mix with beat-aware crossfades.

The original single-track analysis endpoint is still supported.

## Current MVP

- FastAPI backend
- Easy Mode browser interface at `/`
- Advanced Mode Swagger documentation at `/docs`
- Search for already analyzed tracks by title, file name, BPM, or key
- Single WAV/MP3 analysis through `POST /api/tracks/analyze`
- Batch MP3 analysis through `POST /api/tracks/analyze-batch`
- Duplicate upload detection using content hashes
- JSON storage for track analysis, mix records, and job status
- Compatibility scoring by tempo, key, energy, and structure
- Automatic mix planning for two or more tracks with an optional genre/vibe direction
- Browser-side live deck with a draggable queue, Play Next, Transition Now, and Stop Live controls
- Excerpt-based mixing so long songs or full DJ sets do not have to play end to end
- Real WAV rendering with phrase-aware cue points, bass-swap crossfades, gain normalization, fade-in/fade-out, and clipping prevention
- Procedural transition SFX such as sweeps and downbeat impacts
- Mix audio streaming through `GET /api/mixes/{mix_id}/audio`

## Folder Structure

```text
backend/
|-- app/
|   |-- api/
|   |   |-- jobs.py
|   |   |-- mixes.py
|   |   `-- tracks.py
|   |-- analyzer/
|   |-- models/
|   |   |-- job.py
|   |   |-- mix.py
|   |   `-- track.py
|   |-- services/
|   |   |-- batch_analyzer.py
|   |   |-- compatibility.py
|   |   |-- job_service.py
|   |   |-- mix_planner.py
|   |   |-- mix_renderer.py
|   |   |-- mix_storage.py
|   |   `-- track_service.py
|   |-- static/
|   |   |-- app.js
|   |   |-- index.html
|   |   `-- styles.css
|   |-- config.py
|   `-- main.py
|-- uploads/
|-- analysis_output/
|-- mixes/
|-- jobs/
|-- tests/
|-- requirements.txt
`-- README.md
```

Generated files in `uploads`, `analysis_output`, `mixes`, and `jobs` are local working files and are ignored by Git.

## Setup

From PowerShell:

```powershell
cd C:\Users\musta\OneDrive\Documents\GitHub\AI-DJ
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
```

No new Python dependency is required for this MVP beyond the existing `requirements.txt`. The first renderer exports WAV files using `librosa`, `numpy`, and `soundfile`.

## Configuration

Optional environment variables:

```powershell
$env:AI_DJ_MAX_BATCH_FILES="25"
$env:AI_DJ_MAX_UPLOAD_MB="100"
$env:AI_DJ_RENDER_SAMPLE_RATE="44100"
$env:AI_DJ_UPLOADS_DIR="C:\Path\To\uploads"
$env:AI_DJ_ANALYSIS_OUTPUT_DIR="C:\Path\To\analysis_output"
$env:AI_DJ_MIXES_DIR="C:\Path\To\mixes"
$env:AI_DJ_JOBS_DIR="C:\Path\To\jobs"
```

## Run The Backend

```powershell
cd C:\Users\musta\OneDrive\Documents\GitHub\AI-DJ\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Open Easy Mode:

```text
http://127.0.0.1:8000/
```

Open Advanced Mode:

```text
http://127.0.0.1:8000/docs
```

## Easy Mode

1. Open `http://127.0.0.1:8000/`.
2. Search saved tracks with **Search Music**, or click **Show Library** to list analyzed tracks.
3. Add saved tracks to the mix, or drop MP3 files onto the page, choose multiple MP3s, or use **Choose Folder**.
4. Optional: type a direction such as `smooth house`, `club energy`, `more hip-hop cuts`, or `chill lounge`.
5. Use the **Live Queue** to drag songs into order.
6. Click **Play Next** on a queued song to put it after the currently playing track.
7. Set **Sec/song** to control how much of each track plays before transitioning.
8. Set **Blend** to control crossfade length.
9. Keep **Auto order** on for rendered mixes unless you want the selected order.
10. Keep **DJ transition SFX** on for sweeps and downbeat impacts.
11. Click **Make Live Mix** to start browser-side playback after local decoding. Use **Transition Now** to force the next blend.
12. Click **Render Download** when you only want the final WAV output.

Folder selection uses browser folder-upload support. Dragging a whole folder also works in browsers that expose dropped folder entries, such as current Chromium-based browsers.

Online song search is not wired to a commercial music provider yet. To search full online catalogs legally, connect a licensed provider such as a store, streaming, or royalty-free catalog API and render only audio that the app is authorized to access.

Full DJ mixes can be used as source/reference audio, but the app does not retrain an AI model from them yet. The next practical step is a style-profile analyzer that extracts transition spacing, average excerpt length, energy arc, and SFX density from reference DJ sets.

## Swagger: Upload Multiple Songs

1. Open `POST /api/tracks/analyze-batch`.
2. Click **Try it out**.
3. In the `files` field, select multiple `.mp3` files.
4. Click **Execute**.
5. Check the response:
   - `successful` shows analyzed tracks.
   - `failed` shows files that could not be analyzed.
   - `duplicates` shows files that matched an already analyzed upload.
   - `tracks[*].track_id` contains the IDs used for compatibility and mixing.
6. Optional: open `GET /api/jobs/{job_id}` using the returned `job_id`.

The batch endpoint continues after individual file failures. Broken files should appear in `errors` instead of crashing the whole request.

## Swagger: Find Compatible Tracks

1. Copy a `track_id` from a batch or single upload response.
2. Open `GET /api/tracks/{track_id}/compatible`.
3. Click **Try it out**.
4. Paste the track ID.
5. Click **Execute**.

The response is ordered from best match to weakest match and includes a score breakdown for tempo, key, energy, and structure.

## Swagger: Search Saved Tracks

Use:

```text
GET /api/tracks/search?query=alpha
```

This searches tracks that have already been analyzed and saved locally.

## Swagger: Create And Render A Mix

Create a plan first:

1. Open `POST /api/mixes/plan`.
2. Click **Try it out**.
3. Use a request like:

```json
{
  "track_ids": ["TRACK_ID_1", "TRACK_ID_2", "TRACK_ID_3"],
  "mix_name": "First AI Mix",
  "transition_bars": 8,
  "target_duration_minutes": 10,
  "max_play_seconds_per_track": 75,
  "auto_order": true,
  "mix_direction": "smooth house with club energy",
  "use_transition_sfx": true
}
```

4. Click **Execute**.
5. Copy the returned `mix_id`.

Render the audio:

1. Open `POST /api/mixes/render`.
2. Click **Try it out**.
3. Use:

```json
{
  "mix_id": "MIX_ID_HERE",
  "output_format": "wav"
}
```

4. Click **Execute**.
5. Confirm the response status is `completed` and `output_filename` ends in `.wav`.

Play or download the rendered mix:

1. Open `GET /api/mixes/{mix_id}/audio`.
2. Paste the same `mix_id`.
3. Click **Execute**.

You can also inspect saved mix records with:

- `GET /api/mixes`
- `GET /api/mixes/{mix_id}`

## Run Tests

From the `backend` folder:

```powershell
..\.venv\Scripts\python.exe -m pytest
```

The tests generate synthetic audio and do not require copyrighted music.

## Known Limitations

- Batch upload intentionally accepts `.mp3` files only for now.
- The renderer currently exports WAV only. MP3 export should be added with FFmpeg or a configured encoder.
- Easy Mode's "Live Mix" starts browser-side playback from selected files or saved tracks after local audio decoding. The final downloadable render still happens on the backend.
- The live deck plays excerpts by default. Very long MP3s still need to be decoded by the browser before live playback starts.
- Online song search requires a licensed provider integration before full external songs can be selected without local files.
- Reference DJ mixes are not true model training yet; they can be analyzed in a future style-profile workflow.
- The mix direction steers ordering, transition length, and SFX style. It does not transform the source songs into a new genre.
- Rendering runs in-process in this MVP. Job records exist, but Redis/Celery/RQ are not wired in yet.
- Beat tracking, key detection, and section labels are estimates.
- BPM matching is conservative and only stretches within a safe range.
- The mix planner uses deterministic rules, not machine learning.
- The renderer uses mono audio internally for reliability in this first pass.

## Recommended Next Step

Add a reference-mix style profiler for full DJ sets, then add waveform previews and editable transition points in Easy Mode. After that, add FFmpeg-backed MP3 export and move long analysis/render work into a real background queue.

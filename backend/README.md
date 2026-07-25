# AI DJ Backend

This backend analyzes uploaded tracks, compares musical compatibility, creates a deterministic DJ mix plan, and renders a playable WAV mix with beat-aware crossfades.

The original single-track analysis endpoint is still supported.

## Current MVP

- FastAPI backend
- Party Mode browser interface at `/`
- Studio Mode Swagger documentation at `/docs`
- Search for already analyzed tracks by title, file name, BPM, or key
- Train a local DJ style profile from reference DJ mixes without adding them to the song queue
- Single WAV/MP3 analysis through `POST /api/tracks/analyze`
- Batch MP3 analysis through `POST /api/tracks/analyze-batch`
- Duplicate upload detection using content hashes
- JSON storage for track analysis, mix records, and job status
- Compatibility scoring by tempo, key, energy, and structure
- Automatic mix planning for two or more tracks with an optional genre/vibe direction
- Learned style defaults for excerpt length, transition length, phrase behavior, and SFX density
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
|-- style_profiles/
|-- tests/
|-- requirements.txt
`-- README.md
```

Generated files in `uploads`, `analysis_output`, `mixes`, `jobs`, and `style_profiles` are local working files and are ignored by Git.

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
$env:AI_DJ_STYLE_PROFILES_DIR="C:\Path\To\style_profiles"
```

## Run The Backend

```powershell
cd C:\Users\musta\OneDrive\Documents\GitHub\AI-DJ\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Open Party Mode:

```text
http://127.0.0.1:8000/
```

Open Studio Mode:

```text
http://127.0.0.1:8000/docs
```

## Party Mode

1. Open `http://127.0.0.1:8000/`.
2. Click **Add MP3s**, choose a whole folder, or drag MP3 files onto the drop zone.
3. Wait for automatic audio analysis and DJ research; imported songs are saved to the library and added to the live queue.
4. Search the saved library by title, BPM, or key and add any other songs you want.
5. Optional: type a direction such as `smooth house`, `club energy`, `more hip-hop cuts`, or `chill lounge`.
6. Keep song timing on **Auto** to use a different researched play window for every song. Auto timing keeps the detected hype section before the outgoing blend.
7. Switch song timing to **Manual** only when you want to set the same seconds-per-song cap yourself. Leave **Mix minutes** empty for an automatic total length.
8. Use the **Live Queue** to drag songs into order, or click **Play Next** to cue a song after the current track.
9. Keep **Trained style**, **AI song order**, and **DJ effects** on for the full automatic mix.
10. Use **DJ Research** to inspect each song's auto play window, hype point, mix-in/mix-out cues, and transition matches.
11. Click **Start Live Mix** to line up and start the browser deck. Use **Mix Next Now** to force the next blend.
12. Click **Render Download** when you only want the final WAV output.

Folder selection uses browser folder-upload support. Dragging a whole folder also works in browsers that expose dropped folder entries, such as current Chromium-based browsers.

Online song search is not wired to a commercial music provider yet. The link importer accepts direct MP3/WAV links from sources you are authorized to download. YouTube-to-MP3 ripping is intentionally blocked; to use YouTube content, use official YouTube download features, your own exported content, or a licensed source with rights-holder permission.

Full DJ mixes can be used as reference audio. The app analyzes them for transition spacing, average excerpt length, phrase timing, phrase-boundary strength, energy-change behavior, spectral motion, SFX density, effect intensity, cue-point sensitivity, and preferred transition effects. Reference mixes are not added to the song library or live queue.

## DJ Research

The research endpoints turn analyzed songs into DJ-ready metadata:

- likely mix-in cue points near clean phrase starts
- likely mix-out cue points near phrase-safe exits, lower-energy moments, or energy changes
- a per-song automatic play window with an entry point, detected hype point, and phrase-safe exit
- local song pairings with suggested styles such as long EQ blend, bass swap, echo cut, drop swap, or quick cut
- notes for future public metadata evidence, without downloading copyrighted audio

Research is generated automatically when a local MP3 or authorized direct audio link is imported. `GET /api/tracks/research` rebuilds the entire library when all transition pairings need to be refreshed.

Use:

```text
GET /api/tracks/{track_id}/research
GET /api/tracks/research
GET /api/tracks/music-sources
```

For wider song background intelligence, use legal metadata/evidence sources such as MusicBrainz, ListenBrainz, Mixcloud tracklists, Beatport metadata with approved access, licensed tracklists, or user-provided cue sheets. Do not scrape or download copyrighted audio.

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

## Swagger: Import An Authorized Audio Link

Use:

```text
POST /api/tracks/import-url
```

Example:

```json
{
  "url": "https://example.com/authorized-track.mp3"
}
```

The endpoint downloads and analyzes direct MP3/WAV links only. YouTube links are rejected because YouTube restricts downloading content unless YouTube and the rights holder expressly allow it.

## Swagger: Train DJ Style

Use:

```text
POST /api/style-profiles/train
```

Upload one or more MP3/WAV DJ reference mixes in the `files` field. The response stores a default style profile used by future mix plans when `use_trained_style` is `true`. The profile includes learned transition timing plus an effect palette for smoother filter, echo, riser, roll, and impact choices.

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
  "use_transition_sfx": true,
  "use_trained_style": true
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
- Party Mode's "Live Mix" starts browser-side playback from selected files or saved tracks after local audio decoding. The final downloadable render still happens on the backend.
- The live deck plays excerpts by default. Very long MP3s still need to be decoded by the browser before live playback starts.
- Online song search requires a licensed provider integration before full external songs can be selected without local files.
- Reference DJ mixes train a deterministic local style profile, not a neural model. It learns usable transition defaults from the audio patterns.
- The mix direction steers ordering, transition length, and SFX style. It does not transform the source songs into a new genre.
- Rendering runs in-process in this MVP. Job records exist, but Redis/Celery/RQ are not wired in yet.
- Beat tracking, key detection, and section labels are estimates.
- BPM matching is conservative and only stretches within a safe range.
- The mix planner uses deterministic rules, not machine learning.
- The renderer uses mono audio internally for reliability in this first pass.

## Recommended Next Step

Add waveform previews and editable transition points in Party Mode, then evolve the deterministic style profile into a scored transition model. After that, add FFmpeg-backed MP3 export and move long analysis/render work into a real background queue.

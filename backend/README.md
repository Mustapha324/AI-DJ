# AI DJ Track Analyzer

This project is the first foundation milestone for an AI DJ application. The current backend accepts one local WAV or MP3 file, analyzes core musical/audio features, saves the result as JSON, and lets you retrieve previous analyses.

It does not mix songs, play audio in real time, separate stems, detect verses/choruses/drops, or call any LLM API yet.

## Current Milestone

- FastAPI backend
- Local upload handling for WAV and MP3 files
- JSON storage for track analysis
- Beat, tempo, energy, loudness, chroma, and basic key estimation
- Placeholder section structures for future song arrangement features
- Tests that generate synthetic WAV audio

## Folder Structure

```text
ai-dj/
|-- backend/
|   |-- app/
|   |   |-- main.py
|   |   |-- config.py
|   |   |-- api/
|   |   |   `-- tracks.py
|   |   |-- analyzer/
|   |   |   |-- track_analyzer.py
|   |   |   |-- beat_detector.py
|   |   |   |-- key_detector.py
|   |   |   `-- energy_analyzer.py
|   |   |-- models/
|   |   |   `-- track.py
|   |   |-- services/
|   |   |   `-- track_service.py
|   |   `-- storage/
|   |-- uploads/
|   |-- analysis_output/
|   |-- tests/
|   |-- requirements.txt
|   `-- README.md
|-- music/
|-- output/
`-- .gitignore
```

`backend/uploads`, `backend/analysis_output`, `music`, and `output` are local working folders. Their generated contents are ignored by Git.

## Windows Setup

From PowerShell, move into the repository:

```powershell
cd C:\Users\musta\OneDrive\Documents\GitHub\AI-DJ
```

Create and activate a virtual environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
```

## Start FastAPI

Run the backend from the `backend` folder:

```powershell
cd C:\Users\musta\OneDrive\Documents\GitHub\AI-DJ\backend
python -m uvicorn app.main:app --reload
```

Open Swagger documentation:

```text
http://127.0.0.1:8000/docs
```

## Analyze A Song

Use Swagger at `/docs`, open `POST /api/tracks/analyze`, choose a WAV or MP3 file that you have permission to use, and execute the request.

You can also use PowerShell with `curl.exe`:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/tracks/analyze" -F "file=@C:\Path\To\Your\Song.wav"
```

List analyzed tracks:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/tracks" -Method Get
```

Get one analysis:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/tracks/TRACK_ID_HERE" -Method Get
```

## Run Tests

From the `backend` folder:

```powershell
python -m pytest
```

The tests generate a short synthetic WAV signal and do not require copyrighted music.

## Example JSON Response

```json
{
  "track_id": "2fb88dc5c3cc4dbb9d89ce1f6ef75631",
  "file_name": "my_song.wav",
  "title": "my song",
  "duration_seconds": 184.32,
  "sample_rate": 44100,
  "estimated_bpm": 124.0,
  "beats": {
    "tempo_bpm": 124.0,
    "beat_timestamps": [0.47, 0.95, 1.43],
    "beat_count": 382,
    "approximate_bars": [
      {
        "bar_number": 1,
        "start_beat": 1,
        "end_beat": 4,
        "start_time": 0.47,
        "end_time": 1.91
      }
    ]
  },
  "key": {
    "root": "A",
    "mode": "minor",
    "display_name": "A minor",
    "confidence": 0.72
  },
  "overall_rms_energy": 0.18,
  "energy_curve": [
    { "time": 1.0, "energy": 0.54 },
    { "time": 2.0, "energy": 0.61 }
  ],
  "estimated_loudness_db": -14.89,
  "zero_crossing_rate": 0.057,
  "spectral_centroid": 2350.42,
  "chroma_features": {
    "C": 0.04,
    "C#": 0.02,
    "D": 0.06,
    "D#": 0.03,
    "E": 0.11,
    "F": 0.02,
    "F#": 0.04,
    "G": 0.05,
    "G#": 0.07,
    "A": 0.28,
    "A#": 0.04,
    "B": 0.24
  },
  "sections": [
    {
      "section_type": "unknown",
      "start_time": 0.0,
      "end_time": 184.32,
      "start_beat": 1,
      "end_beat": 382,
      "energy": 0.57,
      "confidence": 0.25,
      "manually_labeled": false
    }
  ],
  "possible_high_energy_sections": [],
  "possible_low_energy_sections": []
}
```

## Key Estimate Limitation

The key detector uses chroma features and major/minor key profiles. This is a basic estimate and may be wrong, especially for tracks with modulation, unusual tuning, dense percussion, short clips, or ambiguous harmony.

## Known Limitations

- Section labels are only `unknown`, `high_energy`, or `low_energy` for now.
- Beat tracking and BPM are estimates.
- Loudness is an approximate dB value based on RMS energy, not a full LUFS measurement.
- MP3 decoding depends on the local audio backend available to `librosa`.
- Storage is JSON files, not a database.

## Planned Next Milestone

Add manual section labeling and editing so a user can correct intro, verse, chorus, drop, and outro boundaries before any automatic mixing work begins.

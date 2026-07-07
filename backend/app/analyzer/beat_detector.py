from __future__ import annotations

import numpy as np
import librosa

from app.models.track import ApproximateBar, BeatInfo


def detect_beats(audio: np.ndarray, sample_rate: int) -> BeatInfo:
    tempo, beat_frames = librosa.beat.beat_track(y=audio, sr=sample_rate, units="frames")
    tempo_value = float(np.asarray(tempo).reshape(-1)[0]) if np.size(tempo) else 0.0
    beat_timestamps = librosa.frames_to_time(beat_frames, sr=sample_rate)
    rounded_beats = [round(float(time), 4) for time in beat_timestamps]

    bars: list[ApproximateBar] = []
    for bar_index, first_beat_index in enumerate(range(0, len(rounded_beats), 4), start=1):
        bar_beats = rounded_beats[first_beat_index : first_beat_index + 4]
        if not bar_beats:
            continue
        bars.append(
            ApproximateBar(
                bar_number=bar_index,
                start_beat=first_beat_index + 1,
                end_beat=first_beat_index + len(bar_beats),
                start_time=bar_beats[0],
                end_time=bar_beats[-1],
            )
        )

    return BeatInfo(
        tempo_bpm=round(tempo_value, 2) if tempo_value > 0 else None,
        beat_timestamps=rounded_beats,
        beat_count=len(rounded_beats),
        approximate_bars=bars,
    )

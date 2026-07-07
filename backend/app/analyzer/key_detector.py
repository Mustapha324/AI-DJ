from __future__ import annotations

import numpy as np
import librosa

from app.models.track import KeyEstimate


PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

# Krumhansl-Schmuckler key profiles. This is a useful first estimate, not a
# source of truth; real songs can modulate or emphasize notes outside one key.
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def estimate_key(audio: np.ndarray, sample_rate: int) -> tuple[KeyEstimate, dict[str, float]]:
    chroma = librosa.feature.chroma_stft(y=audio, sr=sample_rate)
    chroma_average = np.maximum(np.mean(chroma, axis=1), 0.0)

    if not np.any(chroma_average):
        empty_chroma = {pitch: 0.0 for pitch in PITCH_CLASSES}
        return KeyEstimate(root="C", mode="major", display_name="C major", confidence=0.0), empty_chroma

    normalized_chroma = chroma_average / np.sum(chroma_average)
    scores: list[tuple[float, str, str]] = []

    for root_index, root_name in enumerate(PITCH_CLASSES):
        scores.append((_cosine_similarity(normalized_chroma, np.roll(MAJOR_PROFILE, root_index)), root_name, "major"))
        scores.append((_cosine_similarity(normalized_chroma, np.roll(MINOR_PROFILE, root_index)), root_name, "minor"))

    scores.sort(reverse=True, key=lambda item: item[0])
    best_score, root, mode = scores[0]
    second_score = scores[1][0] if len(scores) > 1 else 0.0
    margin_confidence = min(1.0, max(0.0, (best_score - second_score) * 5.0))
    absolute_confidence = min(1.0, max(0.0, best_score))
    confidence = round((margin_confidence * 0.6) + (absolute_confidence * 0.4), 3)

    chroma_features = {
        pitch: round(float(value), 5)
        for pitch, value in zip(PITCH_CLASSES, normalized_chroma, strict=True)
    }

    return (
        KeyEstimate(
            root=root,
            mode=mode,
            display_name=f"{root} {mode}",
            confidence=confidence,
        ),
        chroma_features,
    )


def _cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    normalized_right = right / np.sum(right)
    denominator = np.linalg.norm(left) * np.linalg.norm(normalized_right)
    if denominator == 0:
        return 0.0
    return float(np.dot(left, normalized_right) / denominator)

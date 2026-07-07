from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np

from app.analyzer.beat_detector import detect_beats
from app.analyzer.energy_analyzer import (
    build_unknown_section,
    calculate_energy_curve,
    identify_energy_sections,
)
from app.analyzer.key_detector import estimate_key
from app.models.track import TrackAnalysis


class AudioAnalysisError(Exception):
    """Raised when an uploaded audio file cannot be decoded or analyzed."""


class TrackAnalyzer:
    def analyze(self, audio_path: Path, track_id: str, original_file_name: str) -> TrackAnalysis:
        try:
            audio, sample_rate = librosa.load(audio_path, sr=None, mono=True)
        except Exception as exc:  # librosa can raise different backend-specific errors.
            raise AudioAnalysisError("The uploaded file could not be decoded as audio.") from exc

        if len(audio) == 0 or sample_rate <= 0:
            raise AudioAnalysisError("The uploaded file does not contain usable audio.")

        try:
            duration_seconds = float(librosa.get_duration(y=audio, sr=sample_rate))
            beat_info = detect_beats(audio, sample_rate)
            key_estimate, chroma_features = estimate_key(audio, sample_rate)
            energy_curve = calculate_energy_curve(audio, sample_rate)

            overall_rms = float(np.sqrt(np.mean(np.square(audio))))
            estimated_loudness_db = 20 * np.log10(overall_rms + 1e-12)
            zero_crossing_rate = float(np.mean(librosa.feature.zero_crossing_rate(y=audio)))
            spectral_centroid = float(np.mean(librosa.feature.spectral_centroid(y=audio, sr=sample_rate)))

            high_energy_sections = identify_energy_sections(
                energy_curve,
                beat_info.beat_timestamps,
                duration_seconds,
                section_type="high_energy",
                threshold=0.7,
                above_threshold=True,
            )
            low_energy_sections = identify_energy_sections(
                energy_curve,
                beat_info.beat_timestamps,
                duration_seconds,
                section_type="low_energy",
                threshold=0.25,
                above_threshold=False,
            )

            average_normalized_energy = (
                float(np.mean([point.energy for point in energy_curve])) if energy_curve else 0.0
            )
            sections = high_energy_sections + low_energy_sections
            if not sections:
                sections = [
                    build_unknown_section(
                        duration_seconds=duration_seconds,
                        beat_timestamps=beat_info.beat_timestamps,
                        energy=average_normalized_energy,
                    )
                ]

            return TrackAnalysis(
                track_id=track_id,
                file_name=original_file_name,
                title=_title_from_file_name(original_file_name),
                duration_seconds=round(duration_seconds, 3),
                sample_rate=sample_rate,
                estimated_bpm=beat_info.tempo_bpm,
                beats=beat_info,
                key=key_estimate,
                overall_rms_energy=round(overall_rms, 6),
                energy_curve=energy_curve,
                estimated_loudness_db=round(float(estimated_loudness_db), 3),
                zero_crossing_rate=round(zero_crossing_rate, 6),
                spectral_centroid=round(spectral_centroid, 3),
                chroma_features=chroma_features,
                sections=sections,
                possible_high_energy_sections=high_energy_sections,
                possible_low_energy_sections=low_energy_sections,
            )
        except AudioAnalysisError:
            raise
        except Exception as exc:
            raise AudioAnalysisError("The uploaded file could not be analyzed.") from exc


def _title_from_file_name(file_name: str) -> str:
    stem = Path(file_name).stem
    title = stem.replace("_", " ").replace("-", " ").strip()
    return " ".join(title.split()) or "Untitled Track"

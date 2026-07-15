from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.config import Settings, ensure_storage_dirs
from app.models.mix import MixRecord, MixSummary


class MixNotFoundError(Exception):
    """Raised when a mix record does not exist."""


class MixStorage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        ensure_storage_dirs(settings)

    def generate_mix_id(self) -> str:
        return uuid.uuid4().hex

    def save_record(self, record: MixRecord) -> Path:
        path = self._record_path(record.mix_id)
        with path.open("w", encoding="utf-8") as output_file:
            json.dump(record.model_dump(mode="json"), output_file, indent=2)
        return path

    def get_record(self, mix_id: str) -> MixRecord:
        path = self._record_path(mix_id)
        if not path.exists():
            raise MixNotFoundError(f"Mix '{mix_id}' was not found.")
        with path.open("r", encoding="utf-8") as input_file:
            return MixRecord.model_validate(json.load(input_file))

    def list_records(self) -> list[MixSummary]:
        summaries: list[MixSummary] = []
        for record_path in sorted(self.settings.mixes_dir.glob("*.json")):
            try:
                with record_path.open("r", encoding="utf-8") as input_file:
                    record = MixRecord.model_validate(json.load(input_file))
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            summaries.append(
                MixSummary(
                    mix_id=record.mix_id,
                    mix_name=record.mix_name,
                    status=record.status,
                    track_order=record.track_order,
                    output_filename=record.output_filename,
                    duration_seconds=record.duration_seconds,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
            )
        return summaries

    def output_path(self, mix_id: str, output_format: str = "wav") -> Path:
        return self.settings.mixes_dir / f"{mix_id}.{output_format}"

    def _record_path(self, mix_id: str) -> Path:
        return self.settings.mixes_dir / f"{mix_id}.json"

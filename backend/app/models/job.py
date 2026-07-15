from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


JobState = Literal["queued", "analyzing", "planning", "rendering", "completed", "failed"]


class JobRecord(BaseModel):
    job_id: str
    status: JobState
    progress: int = Field(..., ge=0, le=100)
    message: str
    created_at: datetime
    updated_at: datetime
    error: str | None = None

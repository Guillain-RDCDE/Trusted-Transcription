"""Job model and queue for the transcription pipeline.

Design: each audio file is a Job. A job passes through stages:
QUEUED -> TRANSCRIBING -> DETECTING -> REPAIRING -> SCORING -> DONE

Jobs are idempotent: re-running a completed job returns the cached
result. Failed jobs retry with exponential backoff up to max_retries.

Cost is tracked per job (API calls, compute time) so the operator
can answer "how much does it cost to process one hour of audio?"
at any time.
"""

from __future__ import annotations

import hashlib
import json
import time
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    TRANSCRIBING = "transcribing"
    DETECTING = "detecting"
    REPAIRING = "repairing"
    SCORING = "scoring"
    DONE = "done"
    FAILED = "failed"


class Job(BaseModel):
    job_id: str
    audio_path: str
    status: JobStatus = JobStatus.QUEUED
    attempt: int = 0
    max_retries: int = 3
    cost_usd: float = 0.0
    created_at: float = Field(default_factory=time.time)
    completed_at: Optional[float] = None
    error: Optional[str] = None
    result_path: Optional[str] = None

    @classmethod
    def from_audio(cls, audio_path: str | Path, max_retries: int = 3) -> Job:
        path = Path(audio_path)
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        job_id = f"{path.stem}_{content_hash}"
        return cls(job_id=job_id, audio_path=str(path), max_retries=max_retries)

    @property
    def can_retry(self) -> bool:
        return self.status == JobStatus.FAILED and self.attempt < self.max_retries


class JobQueue:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def enqueue(self, job: Job) -> Job:
        existing = self._load(job.job_id)
        if existing and existing.status == JobStatus.DONE:
            return existing
        self._save(job)
        return job

    def next_job(self) -> Optional[Job]:
        for path in sorted(self.state_dir.glob("*.json")):
            job = Job.model_validate_json(path.read_text())
            if job.status == JobStatus.QUEUED:
                return job
            if job.can_retry:
                job.status = JobStatus.QUEUED
                job.attempt += 1
                self._save(job)
                return job
        return None

    def update(self, job: Job) -> None:
        self._save(job)

    def stats(self) -> dict:
        jobs = [
            Job.model_validate_json(p.read_text())
            for p in self.state_dir.glob("*.json")
        ]
        by_status = {}
        total_cost = 0.0
        for j in jobs:
            by_status[j.status.value] = by_status.get(j.status.value, 0) + 1
            total_cost += j.cost_usd
        return {
            "total": len(jobs),
            "by_status": by_status,
            "total_cost_usd": round(total_cost, 4),
        }

    def _save(self, job: Job) -> None:
        path = self.state_dir / f"{job.job_id}.json"
        path.write_text(job.model_dump_json(indent=2))

    def _load(self, job_id: str) -> Optional[Job]:
        path = self.state_dir / f"{job_id}.json"
        if path.exists():
            return Job.model_validate_json(path.read_text())
        return None

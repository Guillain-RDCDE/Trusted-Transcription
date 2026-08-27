"""Data models shared across the pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class Segment(BaseModel):
    start: float = Field(description="Start time in seconds")
    end: float = Field(description="End time in seconds")
    text: str
    confidence: Optional[float] = None
    language: Optional[str] = None


class HallucinationFlag(BaseModel):
    detector: str = Field(description="Which detector fired")
    severity: Severity
    segment_index: int
    reason: str
    evidence: dict = Field(default_factory=dict)


class TranscriptResult(BaseModel):
    segments: list[Segment]
    flags: list[HallucinationFlag] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class RepairAction(BaseModel):
    segment_index: int
    original_text: str
    repaired_text: str
    action: str = Field(description="delete | replace | keep")
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class RepairResult(BaseModel):
    actions: list[RepairAction]
    cost_usd: float = 0.0
    model: str = ""
    declined: bool = Field(
        default=False,
        description="True if the LLM decided the transcript is better left untouched",
    )


class PipelineReport(BaseModel):
    transcript: TranscriptResult
    repairs: Optional[RepairResult] = None
    scores: dict = Field(default_factory=dict)
    cost_usd: float = 0.0
    duration_sec: float = 0.0

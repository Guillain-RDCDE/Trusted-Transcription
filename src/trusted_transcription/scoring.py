"""Scoring — the metrics that matter in production.

Standard WER/CER are necessary but not sufficient. In production
transcription, the questions that matter are:
- How many hallucinations slipped through? (hallucination rate)
- How many real segments were wrongly flagged? (false positive rate)
- How much did this cost? (cost per audio hour)
- How long did it take? (latency)
"""

from __future__ import annotations

from typing import Optional

from trusted_transcription.models import Severity, TranscriptResult


def compute_scores(
    transcript: TranscriptResult,
    reference_text: Optional[str] = None,
) -> dict:
    scores: dict = {}

    total_segments = len(transcript.segments)
    critical_flags = [f for f in transcript.flags if f.severity == Severity.CRITICAL]
    warning_flags = [f for f in transcript.flags if f.severity == Severity.WARNING]

    scores["total_segments"] = total_segments
    scores["critical_flags"] = len(critical_flags)
    scores["warning_flags"] = len(warning_flags)

    if total_segments > 0:
        scores["hallucination_rate"] = round(
            len(critical_flags) / total_segments, 4
        )
    else:
        scores["hallucination_rate"] = 0.0

    if reference_text is not None:
        try:
            from jiwer import wer, cer

            hypothesis = " ".join(seg.text for seg in transcript.segments)
            scores["wer"] = round(wer(reference_text, hypothesis), 4)
            scores["cer"] = round(cer(reference_text, hypothesis), 4)
        except ImportError:
            scores["wer"] = None
            scores["cer"] = None

    audio_duration = transcript.metadata.get("audio_duration_sec", 0)
    if audio_duration:
        scores["audio_duration_sec"] = audio_duration
        total_words = sum(len(seg.text.split()) for seg in transcript.segments)
        scores["total_words"] = total_words
        scores["words_per_minute"] = round(total_words / (audio_duration / 60), 1)

    return scores

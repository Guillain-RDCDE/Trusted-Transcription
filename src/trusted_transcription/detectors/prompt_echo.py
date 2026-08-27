"""Detect prompt echo — the model returns its own instructions.

When Whisper (or a downstream LLM) fails on a segment, it sometimes
returns the system prompt, the initial_prompt, or fragments of its
own reasoning chain instead of a transcription. This is silent and
confident: the output looks like text, parses fine, and has high
token probabilities.

In production this is catastrophic: the prompt leaks into a legal
document.

Detection: compare each segment against known prompt fragments and
structural markers that never appear in natural speech.
"""

from __future__ import annotations

import re

from trusted_transcription.models import (
    HallucinationFlag,
    Severity,
    TranscriptResult,
)

PROMPT_MARKERS = [
    re.compile(r"(?i)\bsystem\s*:\s*you\s+are\b"),
    re.compile(r"(?i)\bassistant\s*:\s*"),
    re.compile(r"(?i)\buser\s*:\s*"),
    re.compile(r"(?i)\b(transcribe|translate)\s+the\s+following\s+audio\b"),
    re.compile(r"(?i)\breturn\s+(only\s+)?the\s+transcription\b"),
    re.compile(r"(?i)\bdo\s+not\s+(add|include|invent)\b"),
    re.compile(r"(?i)\bjson\s*\{"),
    re.compile(r"(?i)\b(step\s+\d+|instruction\s*:)\b"),
    re.compile(r"\[\[.*?\]\]"),
    re.compile(r"<\|.*?\|>"),
]

REASONING_MARKERS = [
    re.compile(r"(?i)\blet me (think|analyze|consider)\b"),
    re.compile(r"(?i)\bI (need to|should|will)\b"),
    re.compile(r"(?i)\bthe (transcription|audio) (shows|contains|appears)\b"),
    re.compile(r"(?i)\bhere is the (corrected|final)\b"),
]


class PromptEchoDetector:
    name = "prompt_echo"

    def detect(self, transcript: TranscriptResult) -> list[HallucinationFlag]:
        flags: list[HallucinationFlag] = []

        for i, seg in enumerate(transcript.segments):
            text = seg.text.strip()
            if not text:
                continue

            for marker in PROMPT_MARKERS:
                if marker.search(text):
                    flags.append(
                        HallucinationFlag(
                            detector=self.name,
                            severity=Severity.CRITICAL,
                            segment_index=i,
                            reason=f"Prompt fragment detected in transcript segment",
                            evidence={"pattern": marker.pattern, "text": text[:200]},
                        )
                    )
                    break

            for marker in REASONING_MARKERS:
                if marker.search(text):
                    flags.append(
                        HallucinationFlag(
                            detector=self.name,
                            severity=Severity.WARNING,
                            segment_index=i,
                            reason=f"LLM reasoning chain leaked into transcript",
                            evidence={"pattern": marker.pattern, "text": text[:200]},
                        )
                    )
                    break

        return flags

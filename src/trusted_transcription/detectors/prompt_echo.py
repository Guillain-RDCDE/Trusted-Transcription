"""Detect prompt echo — the model returns its own instructions.

Two very different things get echoed, and they need two detectors.

**The vocabulary prompt.** Production pipelines pass the engine an
``initial_prompt`` listing domain vocabulary ("skirting boards,
ceiling, partition, door frames, casements, lintel…"). On difficult
audio the engine sometimes returns *that list*, word for word, instead
of a transcription. Nothing sees it: the output is not empty, so the
empty-chunk guard is blind; the completeness check compares the input
and output of the repair stage, which faithfully preserves the
truncated text; and tag counts are reinjected afterwards, so they
always match. Measured in production, a heavy tail of dictations
silently lost a fifth or more of their words this way, and a draft
that lost that much was closer to half wrong than three-quarters
right.

Detection is deterministic and needs no reference: when a segment's
content words are mostly words from the prompt, the segment is an
echo. Give the detector the prompt, or put it in
``transcript.metadata["initial_prompt"]``.

**Instruction markers.** A downstream LLM can leak its system prompt
or reasoning chain ("system: you are…", "let me think…"). These never
appear in natural speech and are caught by pattern.
"""

from __future__ import annotations

import re
import unicodedata

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

ECHO_RATIO = 0.70
"""Share of a segment's content words that must come from the prompt."""

MIN_CONTENT_WORDS = 5
"""A segment with fewer content words cannot be judged: one vocabulary
word in a short sentence is normal speech."""

MIN_CONTENT_LENGTH = 4
"""Tokens shorter than this are function words in most languages
(le, la, de, the, and…) and carry no signal either way."""

_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)


def _fold(token: str) -> str:
    """Lower-case and strip accents so 'Élément' and 'element' match."""
    nfkd = unicodedata.normalize("NFKD", token.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def content_words(text: str, min_length: int = MIN_CONTENT_LENGTH) -> list[str]:
    """Folded alphabetic tokens long enough to carry meaning."""
    return [_fold(t) for t in _TOKEN.findall(text) if len(t) >= min_length]


def echo_ratio(text: str, prompt_vocabulary: set[str]) -> tuple[float, int]:
    """Share of the text's content words found in the prompt, and their count."""
    words = content_words(text)
    if not words:
        return 0.0, 0
    hits = sum(1 for w in words if w in prompt_vocabulary)
    return hits / len(words), len(words)


class PromptEchoDetector:
    name = "prompt_echo"

    def __init__(
        self,
        prompt: str | None = None,
        echo_ratio: float = ECHO_RATIO,
        min_content_words: int = MIN_CONTENT_WORDS,
    ):
        self.prompt = prompt
        self.echo_ratio = echo_ratio
        self.min_content_words = min_content_words

    def detect(self, transcript: TranscriptResult) -> list[HallucinationFlag]:
        flags: list[HallucinationFlag] = []
        prompt = self.prompt or transcript.metadata.get("initial_prompt")
        vocabulary = set(content_words(prompt)) if prompt else set()

        for i, seg in enumerate(transcript.segments):
            text = seg.text.strip()
            if not text:
                continue

            if vocabulary:
                ratio, count = echo_ratio(text, vocabulary)
                if count >= self.min_content_words and ratio >= self.echo_ratio:
                    flags.append(
                        HallucinationFlag(
                            detector=self.name,
                            severity=Severity.CRITICAL,
                            segment_index=i,
                            reason=(
                                f"Vocabulary prompt echoed: {ratio:.0%} of content words "
                                f"come from the prompt"
                            ),
                            evidence={
                                "type": "vocabulary_echo",
                                "echo_ratio": round(ratio, 3),
                                "content_words": count,
                                "text": text[:200],
                            },
                        )
                    )
                    continue

            for marker in PROMPT_MARKERS:
                if marker.search(text):
                    flags.append(
                        HallucinationFlag(
                            detector=self.name,
                            severity=Severity.CRITICAL,
                            segment_index=i,
                            reason="Prompt fragment detected in transcript segment",
                            evidence={
                                "type": "instruction_marker",
                                "pattern": marker.pattern,
                                "text": text[:200],
                            },
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
                            reason="LLM reasoning chain leaked into transcript",
                            evidence={
                                "type": "reasoning_marker",
                                "pattern": marker.pattern,
                                "text": text[:200],
                            },
                        )
                    )
                    break

        return flags

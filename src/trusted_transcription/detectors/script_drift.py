"""Detect script drift — the decoder left the language.

On long audio the engine sometimes derails at one point: a short
sentence comes back with characters from other writing systems mixed
into the expected one —

    "Je crois que témoign限 la gamine. Carinória a 많이 dureивать ou
     des Bre Marchessoft lorsque vous êtes là bullet."

— and after it the text "recovers" into something fluent and
plausible **that no longer matches the audio**. The reviewer types
along for forty minutes, then hears one thing and reads another. The
visible garbage is one line; the real damage is everything after it.

That makes the drift point the most useful thing to report: the
remedy is to **re-transcribe from there to the end** as a fresh file
(the decoder's state restarts clean), and to keep everything before
it — including what a human already corrected.

Detection: for a language written in one script, a segment mixing
that script with letters from another is a drift. Pure foreign-script
segments are left to ``language_switch``; the signature here is the
*mix inside one segment*, which no speaker produces.
"""

from __future__ import annotations

import unicodedata

from trusted_transcription.models import (
    HallucinationFlag,
    Severity,
    TranscriptResult,
)

SCRIPT_PREFIXES = (
    "LATIN", "CYRILLIC", "GREEK", "ARABIC", "HEBREW", "DEVANAGARI", "THAI",
    "HANGUL", "HIRAGANA", "KATAKANA", "CJK",
)

EXPECTED_SCRIPT = {
    "fr": "LATIN", "en": "LATIN", "de": "LATIN", "es": "LATIN", "it": "LATIN",
    "pt": "LATIN", "nl": "LATIN", "pl": "LATIN", "sv": "LATIN", "da": "LATIN",
    "ru": "CYRILLIC", "uk": "CYRILLIC", "bg": "CYRILLIC",
    "el": "GREEK", "ar": "ARABIC", "he": "HEBREW", "hi": "DEVANAGARI", "th": "THAI",
    "ko": "HANGUL",
}


def script_of(char: str) -> str | None:
    """The writing system of a letter, or None for non-letters."""
    if not char.isalpha():
        return None
    try:
        name = unicodedata.name(char)
    except ValueError:
        return None
    for prefix in SCRIPT_PREFIXES:
        if name.startswith(prefix):
            return prefix
    return "OTHER"


def foreign_letters(text: str, expected: str) -> list[str]:
    """Letters of ``text`` that belong to another script than ``expected``."""
    return [c for c in text if (s := script_of(c)) is not None and s != expected]


def first_drift_time(transcript: TranscriptResult, language: str | None = None) -> float | None:
    """Start time of the first drifted segment, or None."""
    flags = ScriptDriftDetector(language).detect(transcript)
    if not flags:
        return None
    return transcript.segments[flags[0].segment_index].start


class ScriptDriftDetector:
    name = "script_drift"

    def __init__(self, language: str | None = None):
        self.language = language

    def detect(self, transcript: TranscriptResult) -> list[HallucinationFlag]:
        language = self.language or transcript.metadata.get("language")
        expected = EXPECTED_SCRIPT.get(language or "")
        if expected is None:
            return []  # unknown or multi-script language: nothing to assert

        flags: list[HallucinationFlag] = []
        duration = transcript.metadata.get("audio_duration_sec")
        for i, seg in enumerate(transcript.segments):
            foreign = foreign_letters(seg.text, expected)
            if not foreign:
                continue
            native = [c for c in seg.text if script_of(c) == expected]
            if not native:
                continue  # a whole segment in another script: language_switch's job
            first = not flags
            evidence = {
                "foreign_letters": "".join(foreign)[:40],
                "scripts": sorted({script_of(c) or "" for c in foreign}),
                "text": seg.text[:200],
            }
            if first:
                # Everything from here on is suspect, even if it reads well.
                evidence["regenerate_from_s"] = seg.start
                if duration:
                    evidence["regenerate_to_s"] = duration
            flags.append(
                HallucinationFlag(
                    detector=self.name,
                    severity=Severity.CRITICAL,
                    segment_index=i,
                    reason=(
                        f"Letters from another script mixed into {expected.title()} text"
                        + (
                            f" — re-transcribe from {seg.start:.0f}s to the end"
                            if first
                            else ""
                        )
                    ),
                    evidence=evidence,
                )
            )
        return flags

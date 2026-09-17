"""Detect spelled-out words left in the transcript.

A speaker who spells a name is telling you the engine got it wrong.
The letters in the draft are the symptom; the misheard word next to
them is the defect. This detector flags every spelled-out sequence
with what the deterministic pass would do about it (see
``repair.spellings``): correct the word before, erase the letters,
or abstain and leave it to a reviewer with the audio.
"""

from __future__ import annotations

from trusted_transcription.models import (
    HallucinationFlag,
    Severity,
    TranscriptResult,
)
from trusted_transcription.repair.spellings import resolve


class SpelledOutDetector:
    name = "spelled_out"

    def detect(self, transcript: TranscriptResult) -> list[HallucinationFlag]:
        flags: list[HallucinationFlag] = []
        for i, seg in enumerate(transcript.segments):
            for fix in resolve(seg.text):
                if fix.action == "correct":
                    severity = Severity.WARNING
                    reason = (
                        f"Spelled out '{fix.spelling.word}': the dictated "
                        f"'{fix.dictated}' was misheard"
                    )
                elif fix.action == "erase":
                    severity = Severity.INFO
                    reason = f"Spelled out '{fix.spelling.word}': dictated word already right"
                else:
                    severity = Severity.WARNING
                    reason = f"Spelled out '{fix.spelling.word}': needs a reviewer ({fix.reason})"
                flags.append(
                    HallucinationFlag(
                        detector=self.name,
                        severity=severity,
                        segment_index=i,
                        reason=reason,
                        evidence={
                            "letters": fix.spelling.word,
                            "kind": fix.spelling.kind,
                            "action": fix.action,
                            "dictated": fix.dictated,
                            "replacement": fix.replacement,
                            "similarity": fix.similarity,
                        },
                    )
                )
        return flags

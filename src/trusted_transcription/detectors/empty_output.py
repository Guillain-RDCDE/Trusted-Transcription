"""Detect empty output — minutes of audible speech, zero text.

The engine processed the file, took its usual time, returned a
well-formed answer — and no words. In production this happened on a
perfectly audible eleven-minute dictation, twice in a row. The audio
was not the problem: the **same audio re-encoded** came back with
every sentence. One container/codec combination made the engine
return nothing, silently.

Two lessons, both encoded here:

* an empty answer on real audio is a failure, not a result — and the
  coverage check of ``completeness`` cannot see it, because it has no
  segment to measure;
* **re-encode before blaming the audio**. The cheapest retry is a
  different encoding of the same sound
  (``prevention.reencode.ffmpeg_reencode_for_upload``).

A second signature of the same failure: segments that exist but are
hollow — no text, or zero duration, carrying only downstream anchors.
"""

from __future__ import annotations

from trusted_transcription.detectors.reference_deficit import word_count
from trusted_transcription.models import (
    HallucinationFlag,
    Severity,
    TranscriptResult,
)

MIN_AUDIO_S = 30.0
"""Under this, silence is plausible and an empty answer proves nothing."""

MAX_WORDS_PER_MINUTE = 2.0
"""At or under this rate over the whole file, the answer is empty in
practice: a few stray tokens do not make a transcription."""


class EmptyOutputDetector:
    name = "empty_output"

    def __init__(
        self,
        min_audio_s: float = MIN_AUDIO_S,
        max_words_per_minute: float = MAX_WORDS_PER_MINUTE,
    ):
        self.min_audio_s = min_audio_s
        self.max_words_per_minute = max_words_per_minute

    def detect(self, transcript: TranscriptResult) -> list[HallucinationFlag]:
        duration = transcript.metadata.get("audio_duration_sec")
        if not duration or duration < self.min_audio_s:
            return []

        words = sum(word_count(seg.text) for seg in transcript.segments)
        rate = words / (duration / 60.0)
        if rate > self.max_words_per_minute:
            return []

        hollow = sum(
            1 for seg in transcript.segments if not seg.text.strip() or seg.end <= seg.start
        )
        return [
            HallucinationFlag(
                detector=self.name,
                severity=Severity.CRITICAL,
                segment_index=0,
                reason=(
                    f"{words} words for {duration / 60:.1f} min of audio — "
                    "re-encode and retry before blaming the audio"
                ),
                evidence={
                    "words": words,
                    "audio_sec": duration,
                    "words_per_minute": round(rate, 2),
                    "segments": len(transcript.segments),
                    "hollow_segments": hollow,
                },
            )
        ]

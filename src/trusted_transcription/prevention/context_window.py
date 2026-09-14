"""Context window for short segments — the fix for starved audio.

Production pipelines rarely feed Whisper one long file. They cut the
audio at points that matter to *them*: photo timestamps in a legal
report, speaker turns, chapter marks, silence. Those cuts are correct
for the business and catastrophic for the model: a 1-5 second slice
with no context is exactly the input on which Whisper fills the void
with "Thank you for watching" or "Sous-titrage Societe Radio-Canada".

Measured on a production corpus (ADR 0005): forced short segments
hallucinated about nineteen times more often than the rest, and almost
every phantom phrase sat on one of them.

The fix is not to stop cutting — the cuts guarantee full audio
coverage and anchor downstream data. The fix is to give the model
*more audio than the segment* and keep *only the words that belong to
the segment*:

1. For every segment shorter than ``short_threshold_s``, widen the
   audio window by ``context_s`` on each side (clamped to the file).
2. Transcribe the widened window with word timestamps.
3. Keep the words whose **midpoint** falls inside the original
   segment. Boundaries never move.

Everything else — the cut points, the coverage, the anchors — stays
byte-identical to the unpadded path. The segment above the threshold
goes through the original path untouched.

This module has no dependency on any ASR engine. It plans the windows
and filters the words; the caller supplies a ``transcribe_fn``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from trusted_transcription.models import Segment

SHORT_THRESHOLD_S = 10.0
"""Segments strictly shorter than this get context. Nearly all
phantom phrases in the production measurement sat under ten seconds;
above it the rate falls to the noise floor."""

CONTEXT_S = 10.0
"""Seconds of audio added on each side of a short segment."""


@dataclass(frozen=True)
class Window:
    """What the model will hear for one segment.

    ``start``/``end`` are the segment boundaries and never change.
    ``padded_start``/``padded_end`` are what is actually sent to the
    model. ``padded`` is True when context was added.
    """

    segment_index: int
    start: float
    end: float
    padded_start: float
    padded_end: float

    @property
    def padded(self) -> bool:
        return self.padded_start < self.start or self.padded_end > self.end

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def padded_duration(self) -> float:
        return self.padded_end - self.padded_start

    @property
    def offset(self) -> float:
        """Seconds between the padded window start and the segment start."""
        return self.start - self.padded_start


@dataclass(frozen=True)
class Word:
    """A word with timestamps **relative to the audio the model heard**.

    Engines that return word timestamps (faster-whisper, whisper.cpp,
    the OpenAI API with ``timestamp_granularities=["word"]``) all
    report times from the start of the audio they were given. When the
    audio was a padded window, ``start``/``end`` are therefore
    relative to ``Window.padded_start``.
    """

    start: float
    end: float
    text: str

    @property
    def midpoint(self) -> float:
        return (self.start + self.end) / 2.0


class ContextWindowPolicy:
    """Decides which segments get context and how much."""

    def __init__(
        self,
        short_threshold_s: float = SHORT_THRESHOLD_S,
        context_s: float = CONTEXT_S,
    ):
        if short_threshold_s < 0:
            raise ValueError("short_threshold_s must be >= 0")
        if context_s < 0:
            raise ValueError("context_s must be >= 0")
        self.short_threshold_s = short_threshold_s
        self.context_s = context_s

    def plan(
        self,
        boundaries: list[tuple[float, float]],
        audio_duration_s: float | None = None,
    ) -> list[Window]:
        """Turn segment boundaries into the windows the model will hear.

        ``boundaries`` is the list of ``(start, end)`` the caller has
        already decided on. They are returned unchanged inside each
        ``Window``. Only the padded bounds differ, and only for
        segments strictly shorter than the threshold.

        Padding is clamped to ``[0, audio_duration_s]`` when the
        duration is known, and to ``[0, +inf)`` otherwise.
        """
        windows: list[Window] = []
        for index, (start, end) in enumerate(boundaries):
            if end < start:
                raise ValueError(f"segment {index}: end {end} < start {start}")

            padded_start, padded_end = start, end
            if (end - start) < self.short_threshold_s and self.context_s > 0:
                padded_start = max(0.0, start - self.context_s)
                padded_end = end + self.context_s
                if audio_duration_s is not None:
                    padded_end = min(audio_duration_s, padded_end)
                    # A segment may legitimately end past a rounded
                    # duration; never shrink the segment itself.
                    padded_end = max(padded_end, end)

            windows.append(
                Window(
                    segment_index=index,
                    start=start,
                    end=end,
                    padded_start=padded_start,
                    padded_end=padded_end,
                )
            )
        return windows


def keep_words_in_segment(words: list[Word], window: Window) -> list[Word]:
    """Keep the words whose midpoint falls inside the segment.

    Input timestamps are relative to the padded window; output
    timestamps are relative to the **segment** start, so the caller can
    treat the result exactly like the output of an unpadded call.

    The interval is half-open, ``[start, end)``: a word whose midpoint
    lands exactly on a cut belongs to the segment that starts there.
    With contiguous segments every word is therefore kept by exactly
    one segment — nothing is duplicated, nothing is lost.
    """
    kept: list[Word] = []
    for word in words:
        absolute_mid = window.padded_start + word.midpoint
        if window.start <= absolute_mid < window.end:
            kept.append(
                Word(
                    start=word.start - window.offset,
                    end=word.end - window.offset,
                    text=word.text,
                )
            )
    return kept


def join_words(words: list[Word]) -> str:
    """Rebuild the text from raw word tokens.

    Engines prefix each word token with the whitespace that preceded
    it (``" bonjour"``, ``","``, ``" madame"``). Concatenating the raw
    tokens and stripping the ends gives back the engine's own
    punctuation and spacing. Do not insert spaces yourself: that turns
    ``"salle d'eau ,"`` into a typo the engine never made.
    """
    return "".join(word.text for word in words).strip()


def decoding_overrides(window: Window) -> dict[str, float | int]:
    """Decoding parameters to override on a padded window.

    Anti-repetition settings (``repetition_penalty``,
    ``no_repeat_ngram_size``) are tuned for short slices, where a
    repeated n-gram is almost always a loop. On twenty or thirty
    seconds of real dictation the same phrases legitimately come back
    dozens of times ("in good condition", "the skirting boards are").
    Left on, the penalty forbids the correct repetition and pushes the
    model to invent a synonym: "marques de peinture" became
    "marquettes de pintures" in the first production attempt, a net
    loss several times larger than the measurement noise.

    So a padded window is decoded **without** anti-repetition. The
    unpadded path keeps whatever the caller had tuned.
    """
    if window.padded:
        return {"repetition_penalty": 1.0, "no_repeat_ngram_size": 0}
    return {}


TranscribeFn = Callable[[float, float], list[Word]]
"""``transcribe_fn(padded_start, padded_end) -> words``; timestamps in
the returned words are relative to ``padded_start``."""


@dataclass
class ContextWindowReport:
    """What happened during one transcription run."""

    total_segments: int = 0
    padded_segments: int = 0
    fallbacks_empty: int = 0
    fallbacks_desync: int = 0

    @property
    def fallbacks(self) -> int:
        return self.fallbacks_empty + self.fallbacks_desync


def transcribe_with_context(
    boundaries: list[tuple[float, float]],
    transcribe_fn: TranscribeFn,
    audio_duration_s: float | None = None,
    policy: ContextWindowPolicy | None = None,
    desync_tolerance_s: float = 0.5,
) -> tuple[list[Segment], ContextWindowReport]:
    """Transcribe every segment, giving context to the short ones.

    For each window:

    * unpadded: call ``transcribe_fn(start, end)`` — the original path,
      byte-identical to what the caller did before;
    * padded: call ``transcribe_fn(padded_start, padded_end)``, keep the
      words that belong to the segment, join them.

    Two defensive fallbacks, both counted in the report so that a
    silent drift can be seen (an interception must prove itself, see
    ``docs/measurement-pitfalls.md``):

    * **empty**: the padded window yields no word inside the segment —
      re-run the original unpadded call;
    * **desync**: the engine returned timestamps outside the audio it
      was given (beyond ``padded_duration + desync_tolerance_s``). That
      means the window and the engine disagree on what was sent, and
      every midpoint would be wrong. Re-run the original call.

    Segment ``start``/``end`` in the result are the caller's
    boundaries, untouched.
    """
    policy = policy or ContextWindowPolicy()
    windows = policy.plan(boundaries, audio_duration_s)
    report = ContextWindowReport(total_segments=len(windows))
    segments: list[Segment] = []

    for window in windows:
        if not window.padded:
            words = transcribe_fn(window.start, window.end)
            segments.append(_segment_from(window, words))
            continue

        report.padded_segments += 1
        words = transcribe_fn(window.padded_start, window.padded_end)

        if _out_of_range(words, window.padded_duration, desync_tolerance_s):
            report.fallbacks_desync += 1
            words = transcribe_fn(window.start, window.end)
            segments.append(_segment_from(window, words))
            continue

        kept = keep_words_in_segment(words, window)
        if not kept:
            report.fallbacks_empty += 1
            words = transcribe_fn(window.start, window.end)
            segments.append(_segment_from(window, words))
            continue

        segments.append(_segment_from(window, kept))

    return segments, report


def _out_of_range(words: list[Word], duration: float, tolerance: float) -> bool:
    limit = duration + tolerance
    return any(w.start < -tolerance or w.end > limit for w in words)


def _segment_from(window: Window, words: list[Word]) -> Segment:
    return Segment(start=window.start, end=window.end, text=join_words(words))

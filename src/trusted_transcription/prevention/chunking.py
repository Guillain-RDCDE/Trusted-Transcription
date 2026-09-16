"""Chunking for long audio — cap the chunk, never the file.

Transcription APIs refuse uploads above a size limit. The obvious
guard — "refuse any file above the limit" — is the wrong one, and in
production it silently dropped the longest dictations (an hour of
audio, the ones that carry the most work) for a month: the file was
rejected *before* the chunking that already existed could apply, and
the "relaunch" workaround re-hit the same guard every time. Nothing
looked broken. The draft simply never got its second pass.

The right guard is on the **chunk**:

* cut the file in chunks of ``chunk_s`` seconds, stream-copied (no
  re-encode, so a one-hour file splits in under a second);
* a chunk of ``chunk_s`` seconds at the codec's ceiling bitrate must
  fit under the limit — that is the design invariant, checked here,
  not assumed;
* if a chunk still exceeds the limit (unusual codec, higher
  bitrate), **re-cut it shorter and re-encode**;
* if it cannot be made to fit, **fail visibly**, never skip.

And the invariant that proves nothing was lost: **the durations of
the chunks sum to the duration of the source**, to the millisecond.
On the real one-hour file that had been refused for a month:
3468.636 s in, 3468.636 s out.

Engine-agnostic. This module plans chunks, checks the invariants and
builds the ffmpeg command lines; it never runs them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

CHUNK_S = 540.0
"""Nine minutes: at the MP3 ceiling of 320 kb/s that is 21.6 MB,
under a 25 MB limit with margin."""

RECUT_S = 300.0
"""Length of the re-cut when a stream-copied chunk is still too big."""

UPLOAD_LIMIT_BYTES = 24 * 1024 * 1024
"""One megabyte under the usual 25 MB API limit, for container overhead."""

MP3_CEILING_BPS = 320_000
DURATION_TOLERANCE_S = 0.001


def estimated_bytes(duration_s: float, bitrate_bps: int) -> int:
    """Size of ``duration_s`` seconds of audio at ``bitrate_bps``."""
    return int(duration_s * bitrate_bps / 8)


def max_chunk_seconds(limit_bytes: int, bitrate_bps: int) -> float:
    """The longest chunk that fits under ``limit_bytes`` at ``bitrate_bps``."""
    if bitrate_bps <= 0:
        raise ValueError("bitrate_bps must be > 0")
    return limit_bytes * 8 / bitrate_bps


@dataclass(frozen=True)
class ChunkPolicy:
    chunk_s: float = CHUNK_S
    recut_s: float = RECUT_S
    limit_bytes: int = UPLOAD_LIMIT_BYTES
    ceiling_bps: int = MP3_CEILING_BPS

    def __post_init__(self) -> None:
        if self.chunk_s <= 0 or self.recut_s <= 0:
            raise ValueError("chunk_s and recut_s must be > 0")
        if self.recut_s > self.chunk_s:
            raise ValueError("recut_s must not exceed chunk_s")
        if self.limit_bytes <= 0 or self.ceiling_bps <= 0:
            raise ValueError("limit_bytes and ceiling_bps must be > 0")

    @property
    def fits_at_ceiling(self) -> bool:
        """The design invariant: a full chunk at the ceiling bitrate fits."""
        return estimated_bytes(self.chunk_s, self.ceiling_bps) <= self.limit_bytes


def plan_chunks(duration_s: float, chunk_s: float = CHUNK_S) -> list[tuple[float, float]]:
    """Contiguous ``(start, end)`` chunks covering ``[0, duration_s]`` exactly.

    The last chunk ends at ``duration_s`` itself, not at a multiple of
    ``chunk_s``, so the coverage invariant holds by construction.
    """
    if duration_s < 0:
        raise ValueError("duration_s must be >= 0")
    if chunk_s <= 0:
        raise ValueError("chunk_s must be > 0")
    chunks: list[tuple[float, float]] = []
    start = 0.0
    while start < duration_s:
        end = min(start + chunk_s, duration_s)
        chunks.append((start, end))
        start = end
    return chunks


def coverage_error(chunks: Sequence[tuple[float, float]], duration_s: float) -> str | None:
    """Why the chunks do not cover the source exactly, or None if they do.

    Checks, in order: no reversed chunk, contiguity (no gap, no
    overlap), start at zero, and the sum of durations equal to the
    source within ``DURATION_TOLERANCE_S``.
    """
    if not chunks:
        return "no chunks" if duration_s > 0 else None
    for i, (a, b) in enumerate(chunks):
        if b < a:
            return f"chunk {i} is reversed ({a} > {b})"
    if abs(chunks[0][0]) > DURATION_TOLERANCE_S:
        return f"first chunk starts at {chunks[0][0]}, not 0"
    for i in range(1, len(chunks)):
        gap = chunks[i][0] - chunks[i - 1][1]
        if abs(gap) > DURATION_TOLERANCE_S:
            kind = "gap" if gap > 0 else "overlap"
            return f"{kind} of {abs(gap):.3f}s between chunks {i - 1} and {i}"
    total = sum(b - a for a, b in chunks)
    if abs(total - duration_s) > DURATION_TOLERANCE_S:
        return f"chunks sum to {total:.3f}s, source is {duration_s:.3f}s"
    return None


@dataclass
class UploadPlan:
    chunks: list[tuple[float, float]]
    reencode: list[int] = field(default_factory=list)
    """Indices of chunks that must be re-cut and re-encoded to fit."""
    refused: list[int] = field(default_factory=list)
    """Indices of chunks that cannot be made to fit; the caller must
    fail visibly on these, never skip them."""

    @property
    def ok(self) -> bool:
        return not self.refused


def plan_upload(
    duration_s: float,
    bitrate_bps: int,
    policy: ChunkPolicy = ChunkPolicy(),
    reencode_bps: int | None = None,
) -> UploadPlan:
    """Plan chunks for an upload and decide which need re-encoding.

    ``bitrate_bps`` is the file's actual bitrate (from a probe).
    A chunk whose stream-copied size would exceed the limit is marked
    for a re-cut at ``policy.recut_s`` and a re-encode at
    ``reencode_bps`` (default: the policy ceiling). If even that does
    not fit, the chunk is refused.
    """
    plan = UploadPlan(chunks=plan_chunks(duration_s, policy.chunk_s))
    target_bps = reencode_bps or policy.ceiling_bps
    for i, (a, b) in enumerate(plan.chunks):
        if estimated_bytes(b - a, bitrate_bps) <= policy.limit_bytes:
            continue
        if estimated_bytes(min(b - a, policy.recut_s), target_bps) <= policy.limit_bytes:
            plan.reencode.append(i)
        else:
            plan.refused.append(i)
    return plan


# --- ffmpeg command lines ---------------------------------------------------


def ffmpeg_segment_command(
    source: str, out_pattern: str, chunk_s: float = CHUNK_S
) -> list[str]:
    """Stream-copy split: no re-encode, sub-second on an hour of audio.

    ``out_pattern`` takes a printf-style index, e.g. ``chunk_%03d.mp3``.
    ``-reset_timestamps 1`` makes every chunk start at zero, which is
    what the word-timestamp arithmetic downstream expects.
    """
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-y",
        "-i", source,
        "-f", "segment", "-segment_time", _fmt(chunk_s),
        "-reset_timestamps", "1",
        "-c", "copy",
        out_pattern,
    ]


def ffmpeg_reencode_command(
    source: str, out_path: str, start_s: float, end_s: float, bitrate_bps: int
) -> list[str]:
    """Re-cut one span and re-encode it at ``bitrate_bps``."""
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-y",
        "-ss", _fmt(start_s), "-to", _fmt(end_s),
        "-i", source,
        "-vn", "-b:a", f"{bitrate_bps // 1000}k",
        out_path,
    ]


def ffprobe_duration_command(path: str) -> list[str]:
    """Print the container duration in seconds, nothing else."""
    return [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]


def _fmt(seconds: float) -> str:
    return f"{seconds:.3f}".rstrip("0").rstrip(".")


# --- orchestration ------------------------------------------------------------

TranscribeChunkFn = Callable[[float, float], str]


@dataclass
class ChunkedResult:
    text: str
    chunks: list[tuple[float, float]]
    failed: list[int] = field(default_factory=list)
    errors: dict[int, str] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return not self.failed


def transcribe_in_chunks(
    duration_s: float,
    transcribe_fn: TranscribeChunkFn,
    chunk_s: float = CHUNK_S,
    joiner: str = " ",
) -> ChunkedResult:
    """Transcribe the whole file chunk by chunk and never swallow a failure.

    A chunk whose call raises is recorded in ``failed`` with its error
    and contributes nothing; the result is then marked incomplete.
    The caller decides (fall back, retry, alert) — an incomplete
    result that says so beats a shorter draft that reads fine.
    """
    chunks = plan_chunks(duration_s, chunk_s)
    problem = coverage_error(chunks, duration_s)
    if problem is not None:  # pragma: no cover - plan_chunks guarantees coverage
        raise RuntimeError(f"chunk plan does not cover the source: {problem}")

    parts: list[str] = []
    result = ChunkedResult(text="", chunks=chunks)
    for i, (a, b) in enumerate(chunks):
        try:
            parts.append(transcribe_fn(a, b).strip())
        except Exception as exc:  # noqa: BLE001 - every failure must stay visible
            result.failed.append(i)
            result.errors[i] = f"{type(exc).__name__}: {exc}"
    result.text = joiner.join(p for p in parts if p)
    return result

"""Re-encode before upload — and before blaming the audio.

Some container/codec combinations make an engine return nothing, or
garbage, on perfectly audible sound. The production case was 16 kHz
mono PCM in a WAV container: zero text, twice, where the same audio
as a small mono MP3 transcribed in full. The conversion costs a
second or two per file and removed the failure entirely.

Policy: formats known to misbehave are re-encoded **before** the
first upload, and any empty answer on real audio is retried once
with a re-encoded copy (see ``detectors.empty_output``).

Also here: cutting the tail of a file for a regeneration after a
script drift (``detectors.script_drift``). Stream copy, instantaneous,
and the decoder starts from a clean state on the new file.

This module builds command lines; it never runs them.
"""

from __future__ import annotations

from pathlib import PurePath

REENCODE_SUFFIXES = frozenset({".wav", ".wave", ".aif", ".aiff", ".flac"})
"""Uncompressed or lossless containers: large, and the ones seen to
misbehave. Re-encoding them to a small speech MP3 is lossless for
recognition purposes."""

SPEECH_SAMPLE_RATE = 16_000
SPEECH_BITRATE_BPS = 64_000


def needs_reencode(path: str) -> bool:
    return PurePath(path).suffix.lower() in REENCODE_SUFFIXES


def ffmpeg_reencode_for_upload(
    source: str,
    out_path: str,
    sample_rate: int = SPEECH_SAMPLE_RATE,
    bitrate_bps: int = SPEECH_BITRATE_BPS,
) -> list[str]:
    """Mono speech MP3: what recognition engines are most at ease with."""
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-y",
        "-i", source,
        "-vn", "-ar", str(sample_rate), "-ac", "1",
        "-c:a", "libmp3lame", "-b:a", f"{bitrate_bps // 1000}k",
        out_path,
    ]


def ffmpeg_tail_command(source: str, out_path: str, start_s: float) -> list[str]:
    """Cut from ``start_s`` to the end, stream-copied.

    ``-ss`` before ``-i`` seeks on the input: instantaneous, and
    accurate to a frame boundary, which is all a regeneration needs.
    """
    if start_s < 0:
        raise ValueError("start_s must be >= 0")
    start = f"{start_s:.3f}".rstrip("0").rstrip(".")
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-y",
        "-ss", start, "-i", source,
        "-c", "copy",
        out_path,
    ]

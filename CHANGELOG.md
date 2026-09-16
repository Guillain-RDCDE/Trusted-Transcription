# Changelog

## 0.5.0 — 2026-09-16

### Added
- **Chunking for long audio** (`prevention/chunking.py`): nine-minute
  stream-copied chunks with the cap on the chunk, never the file;
  `plan_upload` marks chunks to re-cut and re-encode and refuses the
  ones that cannot fit; `coverage_error` proves the chunk durations
  sum to the source; `transcribe_in_chunks` records a failed chunk with
  its error instead of swallowing it; ffmpeg/ffprobe command builders.
- `tt chunks <duration> --bitrate <kb/s>`: the upload plan and the
  coverage proof, smoke-tested in CI on the one-hour file from ADR 0008.
- ADR 0008 — Cap the chunk, never the file.

## 0.4.0 — 2026-09-15

### Added
- **Completeness guard** (`repair/completeness_guard.py`): word-level
  net loss per divergent zone (`lost_passage`), over-production bound
  `1.15 × source + 8` (`overproduces`), and `guarded_repair` — retry
  with a reinforced instruction, then split in two and correct each
  half, recursively, bounded at every level; at the floor keep the
  correction and count the loss as irreducible.
- The pipeline refuses any replacement proposed by the repair stage
  that breaks the over-production bound.
- ADR 0007 — The repair never returns less than the source, nor much
  more. ADR 0004 now points to the two numbers.

### Changed
- The LLM SDK is imported only when a real client is built: the
  detectors, the guards and the pipeline logic import without it.

## 0.3.0 — 2026-09-14

### Added
- **Vocabulary echo** in `prompt_echo`: give the detector the engine's
  `initial_prompt` (or put it in `metadata["initial_prompt"]`) and a
  segment whose content words are mostly prompt words is flagged. No
  reference needed.
- **Degenerate output** (`detectors/loop_guard.py`): one word dominating
  the text or a block of fifteen words repeated a dozen times. Thresholds
  calibrated so that ritual formulas repeated once per room stay out;
  `allowed_phrases` lists known refrains. `is_degenerate` is reused by
  the repair.
- **Reference deficit** (`detectors/reference_deficit.py`, opt-in): word
  count per chunk of audio against a second transcript, inline tags
  stripped from the reference.
- **Targeted re-transcription** (`repair/retranscribe.py`): re-transcribe
  the broken chunk only — without the prompt, with it, then split — and
  refuse any attempt that is itself empty, degenerate, an echo or far
  too short.
- `ignore_phrases` on `repetition_loop` for legitimate refrains.
- ADR 0006 — Repair the broken chunk, never fall back on the whole file.
- `corpus/sample/prompt_echo.json`, smoke-tested in CI.

## 0.2.0 — 2026-09-14

### Added
- **Context window** (`trusted_transcription.prevention.context_window`):
  short segments get audio context on each side before the model hears
  them; only the words whose midpoint falls inside the segment are kept,
  boundaries never move. Engine-agnostic, with counted fallbacks for
  empty windows and desynchronised timestamps.
- `tt windows <cuts.json>`: shows what the model will hear for each
  segment, with a sample of photo-timed cuts in `corpus/sample/`.
- `decoding_overrides(window)`: the anti-repetition settings to switch
  off on a padded window, and why.
- ADR 0005 — Detection is not enough: stop starving the model.
- `docs/measurement-pitfalls.md` — five traps in measuring a change to
  an ASR pipeline, starting with "Whisper is not deterministic".

### Changed
- README, reference and architecture now describe prevention as the
  first stage, ahead of detection.

## 0.1.0 — 2026-08-27

Initial release: seven deterministic detectors, constrained LLM repair,
scoring, CLI and MCP server.

# Changelog

## 0.9.2 — 2026-09-25

### Added
- `Dockerfile`: the commands and their three dependencies, nothing else;
  built and run on a mounted sample in CI.
- CI, release and license badges.

### Changed
- README rewritten around what the project does now — prevents, detects,
  repairs without making things worse, measures honestly — with the
  hard-coded detector counts removed from the prose and the image text.

## 0.9.1 — 2026-09-24

### Added
- Tests for every operator command, driven in-process on the committed
  samples: what each prints and how it exits is now pinned.
- The linter is a CI gate, pinned to an exact version, over the whole
  tree including the sample fetcher.

### Changed
- The original files are lint-clean: unused imports, unsorted imports,
  old-style optional annotations and long lines.

## 0.9.0 — 2026-09-23

### Changed
- **Installable in one line.** `pip install -e .` gives the `tt`,
  `tt-mcp` and `tt-bench` commands; no more `PYTHONPATH=src` anywhere
  in the README, the reference, the CI or the Makefile.
- **Three core dependencies.** The API clients moved to the `api`
  extra; detectors, guards, prevention and bench run without them.
- **Default repair model** updated to the current generation, with the
  list price on the class so that a model change updates both.
- CI builds the wheel and installs it in a clean environment, then
  runs the commands from outside the repository.

### Added
- `publish` workflow: on a version tag, build, check that the tag and
  the package version agree, upload to PyPI through trusted publishing.
  Needs the one-time PyPI setup described in `docs/RELEASING.md`.
- `docs/RELEASING.md`.

## 0.8.0 — 2026-09-22

### Added
- **Engine bench** (`eval/engine_bench.py`): accuracy and production
  as one row that cannot carry one without the other; paired wins
  against a control on common files only; mean accuracy inside each
  reference-origin group (the biased-judge check); precision recorded
  on every row; an idempotent JSON-lines store; a resource gate that
  refuses to run when the shared device is short of memory; failures
  recorded, never swallowed.
- `tt bench-report <results.jsonl> --control <engine>`, with a
  synthetic sample smoke-tested in CI.
- ADR 0011 — Two measures or none, and a judge you know is biased.
- Measurement pitfalls: a sixth one.

## 0.7.0 — 2026-09-21

### Added
- **Phantom phrases per language** (`detectors/phantom_phrases.py`):
  English, French, German, Spanish, Italian, Portuguese, all checked by
  default; `languages=` restricts the lists.
- **Script drift** (`detectors/script_drift.py`): a segment mixing the
  expected script with letters from another; the first one carries the
  span to regenerate, from the drift point to the end of the file.
- **Empty output** (`detectors/empty_output.py`): minutes of audible
  speech and zero words, including hollow segments that carry only
  anchors.
- `prevention/reencode.py`: formats re-encoded before upload, the mono
  speech MP3 command, and the stream-copied tail cut for a regeneration.
- ADR 0010 — Regenerate from the drift point, keep what the human typed.
- `corpus/sample/script_drift.json`, smoke-tested in CI.

### Fixed
- The phantom pattern meant for a segment that is only "you" matched
  every sentence ending in "you".

## 0.6.0 — 2026-09-17

### Added
- **Spelled-out pass** (`repair/spellings.py`): finds hyphenated,
  dotted and spaced-capital sequences, rebuilds the word, corrects the
  dictated word before it when they resemble each other, only erases
  the letters when the word was already right, abstains otherwise.
  Nine guardrails from real texts; `unchanged_vocabulary` checks the
  no-invented-word invariant.
- `spelled_out` detector in the default list, flagging every sequence
  with the action the pass would take.
- `tt spell <transcript.json>`: what changes and why, with a sample
  transcript smoke-tested in CI.
- ADR 0009 — The spelling is authoritative.

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

# Changelog

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

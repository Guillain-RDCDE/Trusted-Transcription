# Trusted-Transcription — reference

[← Back to the README](../README.md)

---

## How it works

```
Audio -> [context window] -> Whisper -> [7 detectors] -> [LLM repair] -> [scoring] -> Trusted transcript
```

**Prevention comes first.** Most phantom phrases are not the model's fault: they appear on segments the pipeline itself starved — a few seconds cut at a photo timestamp, with no context. The context window gives the model more audio than the segment and keeps only the words that belong to it. Boundaries never move. In production this removed almost all phantom phrases at once ([ADR 0005](adr/0005-context-window-for-short-segments.md)).

**Detection is deterministic.** No LLM in the loop until a flag fires. The 7 detectors are regex, arithmetic, and statistics — they run in 0.06 seconds, cost nothing, and never hallucinate themselves.

**Repair is constrained.** The LLM (Claude) gets structured output only, a confidence threshold at 0.7, and explicit permission to say "I don't touch this." Unconstrained repair makes things worse 23% of the time ([ADR 0004](../docs/adr/0004-anti-aggravation-guard.md) documents the experiment).

**Repair is complete, and bounded.** The correction stage can swallow a whole paragraph — tags still add up, the draft reads fine — or lengthen the text until the end repeats. `repair.completeness_guard` compares what the model was sent with what it returned: net loss per divergent zone, and never more than a small margin over the source. Lost passage: retry, then split in two and correct each half, recursively; at the floor keep the correction and record the loss ([ADR 0007](adr/0007-completeness-of-the-repair.md)).

**The human stays in the loop** on critical flags the LLM can't resolve. ~70% of transcriptions pass unattended; the rest route to review with the exact segments highlighted.

## The 7 detectors

| Detector | What it catches | How |
|----------|----------------|-----|
| `repetition_loop` | Same phrase 5-50x | N-gram frequency over sliding window |
| `silence_hallucination` | "Thank you for watching" on silence | Known phantom patterns + word/sec ratio |
| `prompt_echo` | System prompt leaked into output | Pattern matching on instruction markers |
| `temporal_drift` | Timestamps overlap, reverse, stall | Pairwise arithmetic on consecutive segments |
| `phantom_subtitle` | Coherent text unrelated to context | Jaccard distance to neighbor vocabulary |
| `language_switch` | French transcript turns English | Language tag + function-word markers |
| `completeness` | Sections silently dropped | Coverage ratio + words-per-minute |
| `degenerate_output` | One word thousands of times | Dominant-word share + repeated block, refrains allowed |
| `prompt_echo` (with the prompt) | The vocabulary prompt returned instead of the audio | Share of content words found in the prompt |
| `reference_deficit` (opt-in) | One chunk far shorter than a second transcript | Words per chunk of audio, tags stripped |
| `spelled_out` | A name spelled letter by letter next to the misheard word | Hyphen / dot / capital sequences, resemblance to the words before |
| `script_drift` | One line mixing writing systems; the rest no longer follows the audio | Letters from another script inside a segment, span to regenerate |
| `empty_output` | Minutes of audible speech, zero words | Words per minute over the whole file, hollow segments |

`silence_hallucination` checks phantom phrases in English, French, German, Spanish, Italian and Portuguese by default — they follow the decoded language, not the expected one.

Silent loss is the most dangerous family: every other hallucination produces visible garbage, these produce a shorter draft that reads fine. When a chunk is caught, `repair.retranscribe` re-transcribes **that chunk only** — without the prompt first, then with it, then in shorter pieces — and refuses any attempt that is itself broken ([ADR 0006](adr/0006-repair-the-chunk-not-the-file.md)).

```bash
PYTHONPATH=src python -m trusted_transcription.cli detect corpus/sample/prompt_echo.json --format table
```

Full catalog with symptoms and causes: [docs/failure-modes.md](../docs/failure-modes.md)

## The context window — see what the model will hear

```bash
PYTHONPATH=src python -m trusted_transcription.cli windows corpus/sample/forced_cuts.json
```

```
 SEG  SEGMENT            MODEL HEARS        CONTEXT
------------------------------------------------------------
   0     0.0-  14.8         0.0-  14.8      -
   1    14.8-  26.9        14.8-  26.9      -
   2    26.9-  28.4        16.9-  38.4      +20.0s
   3    28.4-  35.0        18.4-  45.0      +20.0s
```

From Python, hand it your cut points and any engine that returns word timestamps:

```python
from trusted_transcription.prevention.context_window import transcribe_with_context

segments, report = transcribe_with_context(boundaries, transcribe_fn, audio_duration_s)
# report.padded_segments, report.fallbacks_empty, report.fallbacks_desync
```

Decode the padded window **without** anti-repetition penalties — `decoding_overrides(window)` returns what to override, and ADR 0005 explains the trap.

## Spelled-out names — the spelling is authoritative

```bash
PYTHONPATH=src python -m trusted_transcription.cli spell corpus/sample/spellings.json
```

A speaker who spells a name is telling you the engine got it wrong. `repair.spellings` rebuilds the word from the letters, corrects the dictated word before it when they resemble each other, only erases the letters when the word was already right, and abstains otherwise. No model, nine guardrails from real texts, three invariants (tags unchanged, idempotent, no invented word) — [ADR 0009](adr/0009-the-spelling-is-authoritative.md).

## Comparing engines — two measures or none

```bash
PYTHONPATH=src python -m trusted_transcription.cli bench-report corpus/sample/bench_results.jsonl --control paid-api
```

Accuracy alone rewards an engine that transcribes half the file and gets that half right, so every row carries accuracy *and* production. The reference was corrected from one engine's draft and resembles it, so the comparison is also read inside each reference-origin group. Results are stored one line per (engine, file, precision) and never re-measured; a resource gate keeps the bench from evicting production's models ([ADR 0011](adr/0011-two-measures-or-none.md)).

## Long files — cap the chunk, never the file

```bash
PYTHONPATH=src python -m trusted_transcription.cli chunks 3468.636 --bitrate 320
```

Plans nine-minute stream-copied chunks, marks the ones that must be re-cut and re-encoded to fit under the upload limit, refuses (visibly) the ones that cannot, and prints the proof that nothing was lost: the chunk durations sum to the source, to the millisecond. `transcribe_in_chunks` records a failed chunk with its error instead of swallowing it ([ADR 0008](adr/0008-cap-the-chunk-not-the-file.md)).

## MCP server — for AI agents

```bash
PYTHONPATH=src python -m trusted_transcription.mcp_server
```

5 tools exposed over stdio: `transcribe`, `detect_hallucinations`, `repair`, `score`, `estimate_cost`. Any MCP-compatible agent can drive the pipeline.

Example MCP client config:
```json
{"mcpServers": {"trusted-transcription": {"command": "tt-mcp"}}}
```

## Cost estimation (no API key needed)

```bash
PYTHONPATH=src python -m trusted_transcription.cli cost 60
# Whisper API:  $0.3600
# LLM repair:   $0.0360
# Total:        $0.3960
# Per hour:     $0.40
```

## Architecture decisions

Why two models instead of a fine-tune? Where does the human stay? Why deterministic before probabilistic?

- [0001 — Two models in series](../docs/adr/0001-two-models-in-series.md) (a LoRA fine-tune was tried and abandoned)
- [0002 — Human in the loop](../docs/adr/0002-human-in-the-loop.md)
- [0003 — Deterministic before probabilistic](../docs/adr/0003-deterministic-before-probabilistic.md)
- [0004 — Repair must not make things worse](../docs/adr/0004-anti-aggravation-guard.md)
- [0005 — Detection is not enough: stop starving the model](../docs/adr/0005-context-window-for-short-segments.md) (no-cut and minimum-spacing variants tried and refused)
- [0006 — Repair the broken chunk, never fall back on the whole file](../docs/adr/0006-repair-the-chunk-not-the-file.md) (three guards that were all looking downstream of the loss)
- [0007 — The repair never returns less than the source, nor much more](../docs/adr/0007-completeness-of-the-repair.md) (two detectors thrown away, and a prompt that deleted the head of every retry)
- [0008 — Cap the chunk, never the file](../docs/adr/0008-cap-the-chunk-not-the-file.md) (a guard older than the chunking below it silently dropped the longest dictations for a month)
- [0009 — The spelling is authoritative](../docs/adr/0009-the-spelling-is-authoritative.md) (nine guardrails, each from a text that broke, and the limit accepted on purpose)
- [0010 — Regenerate from the drift point, keep what the human typed](../docs/adr/0010-regenerate-from-the-drift-point.md) (and two field lessons: re-encode before blaming the audio, phantom phrases follow the decoded language)
- [0011 — Two measures or none, and a judge you know is biased](../docs/adr/0011-two-measures-or-none.md) (accuracy and production together, the reference-origin split, why eight-bit gives a wrong verdict)

Every figure behind those decisions was read against a control run. [Measurement pitfalls](measurement-pitfalls.md) lists the five traps that produced wrong conclusions before they were caught, starting with the fact that Whisper is not deterministic.

## Tests

```bash
pip install pytest
PYTHONPATH=src python -m pytest tests/ -v
```

No API calls, no audio files. Pure logic on synthetic transcripts and a ground-truth word timeline.

## Background

This is the generic quality layer extracted from a production legal-grade transcription platform. The platform processes formal dictations where a wrong word is a legal liability — Whisper + Claude pipeline running ~70% unattended across a nine-server fleet, billing daily.

The platform code is under NDA. The techniques, detectors, and architectural decisions are published here. The dead ends too — they are in the ADRs, and they are the reason the production claims are credible.


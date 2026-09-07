# Trusted-Transcription — reference

[← Back to the README](../README.md)

---

## How it works

```
Audio -> Whisper -> [7 detectors] -> [LLM repair] -> [scoring] -> Trusted transcript
```

**Detection is deterministic.** No LLM in the loop until a flag fires. The 7 detectors are regex, arithmetic, and statistics — they run in 0.06 seconds, cost nothing, and never hallucinate themselves.

**Repair is constrained.** The LLM (Claude) gets structured output only, a confidence threshold at 0.7, and explicit permission to say "I don't touch this." Unconstrained repair makes things worse 23% of the time ([ADR 0004](../docs/adr/0004-anti-aggravation-guard.md) documents the experiment).

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

Mode 7 is the most dangerous: every other hallucination produces visible garbage. This one produces nothing — and nothing looks correct.

Full catalog with symptoms and causes: [docs/failure-modes.md](../docs/failure-modes.md)

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

## Tests

```bash
pip install pytest
PYTHONPATH=src python -m pytest tests/ -v
# 13 passed in 0.06s
```

No API calls, no audio files. Pure logic on synthetic transcripts.

## Background

This is the generic quality layer extracted from a production legal-grade transcription platform. The platform processes formal dictations where a wrong word is a legal liability — Whisper + Claude pipeline running ~70% unattended across a nine-server fleet, billing daily.

The platform code is under NDA. The techniques, detectors, and architectural decisions are published here. The dead ends too — they are in the ADRs, and they are the reason the production claims are credible.


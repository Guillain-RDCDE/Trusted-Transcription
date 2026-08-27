# Trusted-Transcription

**Catch confident lies in automatic transcription.**

Whisper is good. It is also confidently wrong 2-5% of the time. In regulated workflows where one wrong word is a liability, that is a blocker. This is the guardrail layer between an ASR model and a document you can bill on.

## What it does

```
Audio -> Whisper -> [7 detectors] -> [LLM repair] -> [scoring] -> Trusted transcript
```

1. **Transcribe** via Whisper API or faster-whisper
2. **Detect** hallucinations with 7 independent deterministic detectors
3. **Repair** flagged segments with Claude (structured output, anti-aggravation guard)
4. **Score**: WER, CER, hallucination rate, cost per hour

## Quick start

```bash
git clone https://github.com/Guillain-RDCDE/Trusted-Transcription.git
cd Trusted-Transcription
make setup
make smoke
```

## CLI

```bash
tt run recording.wav --language fr
tt detect transcript.json --format table
tt cost 60  # estimate for 60 min
```

## MCP server

```bash
tt-mcp  # stdio server, 5 tools for agent integration
```

Tools: `transcribe`, `detect_hallucinations`, `repair`, `score`, `estimate_cost`. Any MCP-compatible agent can drive the pipeline.

## The 7 detectors

| Detector | Catches | Severity |
|----------|---------|----------|
| `repetition_loop` | Same phrase repeated 5-50x | Critical |
| `silence_hallucination` | Text on silent audio | Critical |
| `prompt_echo` | System prompt leaked into output | Critical |
| `temporal_drift` | Timestamps overlap, reverse, stall | Warning-Critical |
| `phantom_subtitle` | Coherent text unrelated to context | Warning |
| `language_switch` | Unexpected language mid-transcript | Warning |
| `completeness` | Audio sections silently dropped | Critical |

Mode 7 is the most dangerous: it produces nothing, and nothing looks correct.

Full catalog: [docs/failure-modes.md](docs/failure-modes.md)

## LLM repair with guardrails

Not "ask an LLM to fix it." A constrained loop:
- Structured JSON output only
- Confidence threshold: below 0.7 = keep untouched
- Decline is the default (the LLM CAN say no)
- Cost tracked per call

Unconstrained repair makes things worse 23% of the time. See [ADR 0004](docs/adr/0004-anti-aggravation-guard.md).

## Architecture decisions

- [0001: Two models in series, not one fine-tune](docs/adr/0001-two-models-in-series.md)
- [0002: Where the human stays in the loop](docs/adr/0002-human-in-the-loop.md)
- [0003: Deterministic before probabilistic](docs/adr/0003-deterministic-before-probabilistic.md)
- [0004: Repair must not make things worse](docs/adr/0004-anti-aggravation-guard.md)

## Evaluation

Public corpus only. No client data.

- Assemblee nationale (formal French, reference transcripts)
- Mozilla Common Voice FR (diverse speakers, accents)
- LibriVox FR (long-form, public domain)

```bash
make bench  # results in eval/results/summary.csv
```

## Background

Extracted from a production legal-grade transcription platform. The techniques are generic; the client code stays under NDA. Dead ends documented in the ADRs.

## License

MIT

**Guillain d'Erceville** - [guillain@poulpe.us](mailto:guillain@poulpe.us) - [GitHub](https://github.com/Guillain-RDCDE) - [LinkedIn](https://www.linkedin.com/in/guillain-d-erceville)

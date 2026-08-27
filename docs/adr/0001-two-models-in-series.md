# ADR 0001: Two models in series, not one fine-tuned model

## Status
Accepted

## Context
We need production transcription accurate enough to bill on. A single
Whisper model produces hallucinations at a rate incompatible with legal
use (~2-5% of segments in our observation). The obvious alternative is
to fine-tune Whisper on domain-specific data.

## Decision
We use two models in series: Whisper for transcription, then a language
model (Claude) for hallucination detection and repair.

## Reasons

1. **Fine-tuning doesn't fix hallucinations.** Whisper's hallucination
   modes (repetition loops, silence fabrication, prompt echo) are
   architectural, not data-dependent. A fine-tuned model hallucinates
   differently, not less. We tested a LoRA fine-tune (April 2025) and
   abandoned it: hallucination rate dropped 15% on in-domain audio but
   increased on out-of-domain audio. Net: worse.

2. **The LLM has context the ASR model doesn't.** A language model can
   read the surrounding transcript, detect semantic incoherence, and
   identify text that doesn't belong. Whisper processes audio segments
   independently — it can't know that "Subscribe to my channel" doesn't
   belong in a legal dictation.

3. **Separation of concerns = independent improvement.** When OpenAI
   ships a better Whisper, we swap the first stage. When Anthropic ships
   a better Claude, we swap the second. Neither change requires
   retraining.

4. **Cost is acceptable.** The LLM repair pass runs only on flagged
   segments (~5% of total), not on the full transcript. At current
   pricing, the repair adds ~$0.12/hour of audio — less than 4% of
   total processing cost.

## Consequences
- Two API dependencies instead of one
- Latency increases by ~2s per flagged segment
- We need a robust detection layer to avoid sending clean segments
  to the LLM (wasted cost and latency)

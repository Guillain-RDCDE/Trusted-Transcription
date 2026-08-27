"""LLM repair pass — correct flagged segments using a language model.

Design principles:
1. The LLM MUST be able to say "I don't touch this" — forcing a
   correction on every flag produces more damage than it fixes.
2. Structured output with schema validation: the LLM returns JSON
   matching RepairAction, not free text. Retry on schema failure.
3. Anti-aggravation guard: if the repaired text is MORE different
   from the audio context than the original, reject the repair.
4. Cost tracking per call — in production, repair cost per audio
   hour is a business metric.
"""

from __future__ import annotations

import json
import time
from typing import Optional

from anthropic import Anthropic

from trusted_transcription.models import (
    HallucinationFlag,
    RepairAction,
    RepairResult,
    Severity,
    TranscriptResult,
)

REPAIR_SYSTEM = """You are a transcription quality controller. You receive segments
flagged as potential hallucinations in an automatic speech-to-text output.

For each flagged segment, decide:
- "delete" if the segment is fabricated (silence hallucination, prompt echo, repetition)
- "replace" if you can infer the correct text from surrounding context
- "keep" if the flag is a false positive or you are not confident enough to change it

IMPORTANT: when in doubt, return "keep". A wrong correction is worse than a
missed detection. You are the last line of defense before a legal document.

Return a JSON array of objects with these fields:
- segment_index (int)
- original_text (string)
- repaired_text (string — same as original if action is "keep" or "delete")
- action ("delete" | "replace" | "keep")
- confidence (float 0-1)
- reasoning (string — one sentence)"""

MAX_RETRIES = 3


class LLMRepairer:
    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        max_retries: int = MAX_RETRIES,
        client: Optional[Anthropic] = None,
    ):
        self.model = model
        self.max_retries = max_retries
        self.client = client or Anthropic()

    def repair(
        self,
        transcript: TranscriptResult,
        flags: list[HallucinationFlag],
    ) -> RepairResult:
        if not flags:
            return RepairResult(actions=[], model=self.model, declined=True)

        critical_flags = [f for f in flags if f.severity == Severity.CRITICAL]
        if not critical_flags:
            return RepairResult(actions=[], model=self.model, declined=True)

        context = self._build_context(transcript, critical_flags)

        for attempt in range(self.max_retries):
            try:
                start = time.monotonic()
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=REPAIR_SYSTEM,
                    messages=[{"role": "user", "content": context}],
                )
                elapsed = time.monotonic() - start

                text = response.content[0].text
                actions = self._parse_response(text, critical_flags)

                cost = self._estimate_cost(response)

                return RepairResult(
                    actions=actions,
                    cost_usd=cost,
                    model=self.model,
                    declined=all(a.action == "keep" for a in actions),
                )

            except (json.JSONDecodeError, KeyError, IndexError):
                if attempt == self.max_retries - 1:
                    return RepairResult(
                        actions=[],
                        model=self.model,
                        declined=True,
                    )

        return RepairResult(actions=[], model=self.model, declined=True)

    def _build_context(
        self,
        transcript: TranscriptResult,
        flags: list[HallucinationFlag],
    ) -> str:
        parts = ["Flagged segments for review:\n"]

        flagged_indices = {f.segment_index for f in flags}

        for flag in flags:
            idx = flag.segment_index
            seg = transcript.segments[idx]

            context_before = ""
            context_after = ""
            if idx > 0:
                context_before = transcript.segments[idx - 1].text
            if idx < len(transcript.segments) - 1:
                context_after = transcript.segments[idx + 1].text

            parts.append(
                f"--- Segment {idx} [{seg.start:.1f}s - {seg.end:.1f}s] ---\n"
                f"Text: {seg.text}\n"
                f"Flag: {flag.detector} — {flag.reason}\n"
                f"Context before: {context_before}\n"
                f"Context after: {context_after}\n"
            )

        parts.append(
            "\nReturn a JSON array of repair actions. "
            "One object per flagged segment. No markdown, no explanation outside the JSON."
        )

        return "\n".join(parts)

    def _parse_response(
        self,
        text: str,
        flags: list[HallucinationFlag],
    ) -> list[RepairAction]:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]

        raw = json.loads(text)
        if not isinstance(raw, list):
            raw = [raw]

        actions = []
        for item in raw:
            actions.append(
                RepairAction(
                    segment_index=item["segment_index"],
                    original_text=item.get("original_text", ""),
                    repaired_text=item.get("repaired_text", ""),
                    action=item["action"],
                    confidence=float(item.get("confidence", 0.5)),
                    reasoning=item.get("reasoning", ""),
                )
            )

        return actions

    def _estimate_cost(self, response) -> float:
        usage = response.usage
        input_cost = usage.input_tokens * 3.0 / 1_000_000
        output_cost = usage.output_tokens * 15.0 / 1_000_000
        return round(input_cost + output_cost, 6)

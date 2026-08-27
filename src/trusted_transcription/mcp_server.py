"""MCP server — expose the pipeline as tools for AI agents.

This is the integration layer that lets an agent (Claude Code,
a custom orchestrator, or any MCP-compatible client) drive the
transcription pipeline programmatically:

- transcribe: run Whisper on an audio file
- detect_hallucinations: run all detectors on a transcript
- repair: run the LLM repair loop on flagged segments
- score: compute quality metrics against a reference
- estimate_cost: predict cost for a given audio duration

Each tool takes and returns structured JSON — no free text,
no ambiguity. An agent can chain them or call them independently.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from trusted_transcription.detectors import ALL_DETECTORS
from trusted_transcription.models import TranscriptResult
from trusted_transcription.pipeline import Pipeline
from trusted_transcription.repair.llm_repair import LLMRepairer
from trusted_transcription.scoring import compute_scores

TOOLS = [
    {
        "name": "transcribe",
        "description": (
            "Transcribe an audio file using Whisper. Returns segments with "
            "timestamps, text, and confidence scores."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "audio_path": {
                    "type": "string",
                    "description": "Path to the audio file (wav, mp3, m4a, flac)",
                },
                "language": {
                    "type": "string",
                    "description": "ISO 639-1 language code",
                    "default": "fr",
                },
            },
            "required": ["audio_path"],
        },
    },
    {
        "name": "detect_hallucinations",
        "description": (
            "Run all hallucination detectors on a transcript. Returns a list "
            "of flags with severity, detector name, and evidence. Detectors: "
            "repetition_loop, silence_hallucination, prompt_echo, temporal_drift, "
            "phantom_subtitle, language_switch, completeness."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "transcript_json": {
                    "type": "string",
                    "description": "JSON string of a TranscriptResult",
                },
            },
            "required": ["transcript_json"],
        },
    },
    {
        "name": "repair",
        "description": (
            "Run the LLM repair loop on flagged segments. The LLM can delete "
            "fabricated segments, replace them, or decline to touch them. "
            "Returns structured repair actions with confidence and reasoning."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "transcript_json": {
                    "type": "string",
                    "description": "JSON string of a TranscriptResult with flags",
                },
            },
            "required": ["transcript_json"],
        },
    },
    {
        "name": "score",
        "description": (
            "Compute quality metrics: WER, CER, hallucination rate, words per "
            "minute. If a reference transcription is provided, computes accuracy."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "transcript_json": {
                    "type": "string",
                    "description": "JSON string of a TranscriptResult",
                },
                "reference_text": {
                    "type": "string",
                    "description": "Reference transcription to score against (optional)",
                },
            },
            "required": ["transcript_json"],
        },
    },
    {
        "name": "estimate_cost",
        "description": (
            "Estimate processing cost for a given audio duration. Returns "
            "breakdown: Whisper API cost, LLM repair cost (if needed), total."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "audio_duration_minutes": {
                    "type": "number",
                    "description": "Duration of audio in minutes",
                },
                "expected_hallucination_rate": {
                    "type": "number",
                    "description": "Expected fraction of segments needing repair (0-1)",
                    "default": 0.05,
                },
            },
            "required": ["audio_duration_minutes"],
        },
    },
]


def handle_tool_call(name: str, arguments: dict) -> dict:
    if name == "transcribe":
        pipeline = Pipeline(language=arguments.get("language", "fr"))
        transcript = pipeline.transcribe(arguments["audio_path"])
        return transcript.model_dump()

    elif name == "detect_hallucinations":
        transcript = TranscriptResult.model_validate_json(arguments["transcript_json"])
        pipeline = Pipeline()
        flags = pipeline.detect_only(transcript)
        return {"flags": [f.model_dump() for f in flags], "count": len(flags)}

    elif name == "repair":
        transcript = TranscriptResult.model_validate_json(arguments["transcript_json"])
        repairer = LLMRepairer()
        result = repairer.repair(transcript, transcript.flags)
        return result.model_dump()

    elif name == "score":
        transcript = TranscriptResult.model_validate_json(arguments["transcript_json"])
        ref = arguments.get("reference_text")
        scores = compute_scores(transcript, ref)
        return scores

    elif name == "estimate_cost":
        minutes = arguments["audio_duration_minutes"]
        hall_rate = arguments.get("expected_hallucination_rate", 0.05)
        whisper_cost = minutes * 0.006
        segments_estimate = minutes * 6
        repair_segments = segments_estimate * hall_rate
        repair_cost = repair_segments * 0.002
        return {
            "whisper_cost_usd": round(whisper_cost, 4),
            "repair_cost_usd": round(repair_cost, 4),
            "total_cost_usd": round(whisper_cost + repair_cost, 4),
            "cost_per_hour_usd": round((whisper_cost + repair_cost) * (60 / minutes), 2),
        }

    else:
        return {"error": f"Unknown tool: {name}"}


def run_stdio_server():
    """MCP stdio transport — reads JSON-RPC from stdin, writes to stdout."""
    sys.stderr.write("Trusted-Transcription MCP server ready\n")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = request.get("method", "")
        req_id = request.get("id")

        if method == "initialize":
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "trusted-transcription",
                        "version": "0.1.0",
                    },
                },
            }
        elif method == "tools/list":
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": TOOLS},
            }
        elif method == "tools/call":
            params = request.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            try:
                result = handle_tool_call(tool_name, arguments)
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps(result, ensure_ascii=False)}
                        ]
                    },
                }
            except Exception as e:
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
                        "isError": True,
                    },
                }
        else:
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {},
            }

        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


@click.command()
def main():
    """Run the Trusted-Transcription MCP server (stdio transport)."""
    run_stdio_server()


if __name__ == "__main__":
    main()

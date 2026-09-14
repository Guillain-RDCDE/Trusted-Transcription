"""Tests for the targeted re-transcription ladder."""

from __future__ import annotations

from trusted_transcription.repair.retranscribe import (
    default_accept,
    retranscribe_chunk,
)

PROMPT = (
    "Constat huissier. Plinthes plafond cloison murs huisseries châssis vantaux "
    "linteau ébrasement carrelage faïence robinetterie ballon chauffe-eau"
)

GOOD = (
    "Nous sommes dans la cuisine. Le sol est carrelé, en bon état. Le plan de travail "
    "présente une rayure d'environ dix centimètres. L'évier est propre, la robinetterie "
    "fonctionne. Les placards hauts ferment correctement. La hotte aspirante est en "
    "état de marche. La fenêtre donne sur la cour, le vitrage est intact. "
) * 3


class Engine:
    """A fake engine that answers from a script keyed by (prompt used, pieces)."""

    def __init__(self, script):
        self.script = script
        self.calls: list[tuple[float, float, bool]] = []

    def __call__(self, start: float, end: float, prompt: str | None) -> str:
        self.calls.append((start, end, prompt is not None))
        return self.script(start, end, prompt)


class TestDefaultAccept:
    def test_accepts_healthy_text(self):
        assert default_accept(GOOD, PROMPT, None) == (True, "accepted")

    def test_rejects_empty(self):
        assert default_accept("   ", PROMPT, None)[0] is False

    def test_rejects_echo(self):
        ok, why = default_accept(PROMPT, PROMPT, None)
        assert not ok and "echo" in why

    def test_rejects_degenerate(self):
        ok, why = default_accept("console " * 500, PROMPT, None)
        assert not ok and "degenerate" in why

    def test_rejects_too_short_against_expectation(self):
        ok, why = default_accept(GOOD, PROMPT, expected_words=10_000)
        assert not ok and "too short" in why


class TestLadder:
    def test_first_rung_without_prompt_fixes_the_echo(self):
        engine = Engine(lambda s, e, p: PROMPT if p else GOOD)
        result = retranscribe_chunk(0.0, 540.0, engine, PROMPT)
        assert result.repaired
        assert result.text == GOOD.strip()
        assert engine.calls == [(0.0, 540.0, False)]
        assert [a.label for a in result.attempts] == ["without_prompt"]

    def test_transient_failure_recovers_on_second_rung(self):
        state = {"n": 0}

        def script(s, e, p):
            state["n"] += 1
            return "" if state["n"] == 1 else GOOD

        engine = Engine(script)
        result = retranscribe_chunk(0.0, 540.0, engine, PROMPT)
        assert result.repaired
        assert [(a.label, a.accepted) for a in result.attempts] == [
            ("without_prompt", False),
            ("with_prompt", True),
        ]

    def test_third_rung_splits_the_chunk_without_prompt(self):
        def script(s, e, p):
            return GOOD if (e - s) <= 180.0 else ""

        engine = Engine(script)
        result = retranscribe_chunk(0.0, 540.0, engine, PROMPT, split_s=180.0)
        assert result.repaired
        last = result.attempts[-1]
        assert last.label == "split_without_prompt"
        assert last.pieces == 3
        assert engine.calls[-3:] == [
            (0.0, 180.0, False),
            (180.0, 360.0, False),
            (360.0, 540.0, False),
        ]

    def test_all_rungs_fail_returns_none_with_the_trail(self):
        engine = Engine(lambda s, e, p: "console " * 300)
        result = retranscribe_chunk(0.0, 540.0, engine, PROMPT)
        assert not result.repaired
        assert result.text is None
        assert len(result.attempts) == 3
        assert all(not a.accepted for a in result.attempts)
        assert all("degenerate" in a.reason for a in result.attempts)

    def test_echo_without_prompt_is_still_refused(self):
        # The engine memorised the vocabulary: even without the prompt it
        # returns the list. That is not a transcription either.
        engine = Engine(lambda s, e, p: PROMPT)
        result = retranscribe_chunk(0.0, 100.0, engine, PROMPT)
        assert not result.repaired
        assert all("echo" in a.reason for a in result.attempts)

    def test_no_prompt_means_a_shorter_ladder(self):
        engine = Engine(lambda s, e, p: "")
        result = retranscribe_chunk(0.0, 100.0, engine, prompt=None)
        assert [a.label for a in result.attempts] == ["without_prompt"]

    def test_short_chunk_is_not_split(self):
        engine = Engine(lambda s, e, p: "")
        result = retranscribe_chunk(0.0, 100.0, engine, PROMPT, split_s=180.0)
        assert [a.label for a in result.attempts] == ["without_prompt", "with_prompt"]

    def test_expected_words_guard_the_result(self):
        engine = Engine(lambda s, e, p: "Bonjour madame, nous commençons le constat.")
        result = retranscribe_chunk(0.0, 540.0, engine, PROMPT, expected_words=1300)
        assert not result.repaired
        assert all("too short" in a.reason for a in result.attempts)

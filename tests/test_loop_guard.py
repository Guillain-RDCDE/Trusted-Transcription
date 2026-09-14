"""Tests for the degenerate-output guard."""

from __future__ import annotations

from trusted_transcription.detectors.loop_guard import (
    DegenerateOutputDetector,
    dominant_word,
    is_degenerate,
    repeated_block,
    tokenize,
)
from trusted_transcription.models import Segment, TranscriptResult

HEALTHY = (
    "Nous constatons que la porte d'entrée est fermée à clé. Les volets du premier "
    "étage sont clos et verrouillés. La serrure ne présente aucune trace visible. Le "
    "compteur électrique fonctionne. Les murs du salon sont en bon état général. La "
    "cuisine dispose de tous les équipements prévus. Le balcon donne sur le jardin. "
    "Les canalisations ont été vérifiées par le plombier ce matin même."
)

FORMULA = "je décline mes nom, prénom et qualité, et je notifie l'objet de ma mission"


class TestTokenize:
    def test_keeps_apostrophes_inside_words_and_drops_digits(self):
        assert tokenize("L'an 2026, d'accord ; RUE") == ["l'an", "d'accord", "rue"]


class TestDominantWord:
    def test_share(self):
        word, share = dominant_word(["a", "a", "b", "c"])
        assert (word, share) == ("a", 0.5)

    def test_empty(self):
        assert dominant_word([]) == ("", 0.0)


class TestRepeatedBlock:
    def test_counts_blocks_at_every_offset(self):
        tokens = ("un deux trois " * 10).split()
        block, count = repeated_block(tokens, block_words=3)
        assert block == "un deux trois"
        assert count == 10

    def test_shorter_than_block(self):
        assert repeated_block(["a", "b"], block_words=15) == ("", 0)


class TestIsDegenerate:
    def test_healthy_text_passes(self):
        assert is_degenerate(HEALTHY) == (False, "")

    def test_one_word_thousands_of_times(self):
        degenerate, reason = is_degenerate("console " * 2000)
        assert degenerate
        assert "console" in reason

    def test_short_sentence_hundreds_of_times(self):
        text = "il n'est pas venu. " * 188
        degenerate, reason = is_degenerate(text)
        assert degenerate

    def test_ritual_formula_a_handful_of_times_is_legitimate(self):
        # A formula repeated once per room stays under the block threshold,
        # even though a naive "three repeats" rule would flag it.
        rooms = " ".join(f"{FORMULA}. Pièce numéro {i}, en bon état." for i in range(8))
        assert is_degenerate(HEALTHY + " " + rooms) == (False, "")

    def test_allowed_phrase_is_ignored_even_when_repeated_a_lot(self):
        text = " ".join([FORMULA] * 30)
        assert is_degenerate(text)[0] is True
        assert is_degenerate(text, allowed_phrases=[FORMULA])[0] is False

    def test_too_short_to_judge(self):
        assert is_degenerate("oui oui oui oui") == (False, "")

    def test_function_word_dominance_is_still_a_loop(self):
        # "de" everywhere is not French, it is a stuck decoder.
        assert is_degenerate("de " * 100 + HEALTHY)[0] is True


class TestDetector:
    def test_flags_degenerate_transcript(self):
        transcript = TranscriptResult(
            segments=[Segment(start=i * 5.0, end=i * 5.0 + 5.0, text="placard " * 20)
                      for i in range(10)]
        )
        (flag,) = DegenerateOutputDetector().detect(transcript)
        assert flag.detector == "degenerate_output"
        assert flag.evidence["dominant_word"] == "placard"

    def test_healthy_transcript_is_silent(self):
        transcript = TranscriptResult(segments=[Segment(start=0, end=60, text=HEALTHY)])
        assert DegenerateOutputDetector().detect(transcript) == []

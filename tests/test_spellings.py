"""Tests for the spelled-out pass — every guardrail is a real text that broke."""

from __future__ import annotations

from trusted_transcription.detectors.spelled_out import SpelledOutDetector
from trusted_transcription.models import Segment, Severity, TranscriptResult
from trusted_transcription.repair.spellings import (
    apply_spellings,
    find_spellings,
    resolve,
    unchanged_vocabulary,
)


def fixed(text: str) -> str:
    out, _ = apply_spellings(text)
    return out


class TestFind:
    def test_hyphenated(self):
        (sp,) = find_spellings("à ATIES. A-T-H-I-E-S, 62223")
        assert (sp.word, sp.kind) == ("ATHIES", "hyphen")

    def test_dotted(self):
        (sp,) = find_spellings("SCI BARLET, V.A.R.L.E.T. au capital")
        assert (sp.word, sp.kind) == ("VARLET", "dotted")

    def test_spaced_capitals_only(self):
        (sp,) = find_spellings("NOREVIE, N O R E V I E")
        assert sp.word == "NOREVIE"
        assert find_spellings("il y a a l'entrée un tapis") == []

    def test_digit_inside_is_found_as_such(self):
        (sp,) = find_spellings("code C.A.R.A.2.D. sur la porte")
        assert sp.kind == "digit"

    def test_two_letters_are_not_a_spelling(self):
        assert find_spellings("bâtiment A-B, escalier") == []

    def test_inside_a_tag_is_ignored(self):
        assert find_spellings("<photo A-B-C> la porte") == []


class TestResolve:
    def test_misheard_word_is_corrected(self):
        (fix,) = resolve("à ATIES. A-T-H-I-E-S, 62223")
        assert fix.action == "correct"
        assert (fix.dictated, fix.replacement) == ("ATIES", "ATHIES")

    def test_already_right_word_is_only_erased(self):
        (fix,) = resolve("NOREVIE, N O R E V I E")
        assert fix.action == "erase"

    def test_unrelated_spelling_abstains(self):
        (fix,) = resolve("le chien, P-A-T-U-R-E-A-U")
        assert fix.action == "abstain"
        assert "unrelated" in fix.reason

    def test_no_word_before_abstains(self):
        (fix,) = resolve("A-T-H-I-E-S, 62223")
        assert fix.action == "abstain"

    def test_self_correction_abstains(self):
        (fix,) = resolve("à BARLET, pardon, V-A-R-L-E-T")
        assert fix.action == "abstain"
        assert "corrected" in fix.reason

    def test_digit_abstains(self):
        (fix,) = resolve("code CARA2D, C.A.R.A.2.D. sur la porte")
        assert fix.action == "abstain"

    def test_parenthesis_holding_more_than_the_spelling_abstains(self):
        (fix,) = resolve("PATUREAU (P-A-T-U-R-E-A-U avec un X) demeurant")
        assert fix.action == "abstain"


class TestApply:
    def test_hyphen_case(self):
        assert fixed("à ATIES. A-T-H-I-E-S, 62223 Athies") == "à ATHIES. 62223 Athies"

    def test_dotted_case_swallows_the_abbreviation_dot(self):
        assert fixed("SCI BARLET, V.A.R.L.E.T. au capital") == "SCI VARLET au capital"

    def test_hyphen_case_keeps_the_sentence_full_stop(self):
        assert fixed("société BARLET, V-A-R-L-E-T. Au capital") == "société VARLET. Au capital"

    def test_spaced_capitals_erased(self):
        assert fixed("NOREVIE, N O R E V I E, domiciliée") == "NOREVIE, domiciliée"

    def test_elision_after_the_sequence_is_preserved(self):
        out = fixed("GALICHON. G-A-L-I-C-H-O-N. D'accord, on continue")
        assert out == "GALICHON. D'accord, on continue"

    def test_spelling_over_two_words_matches_both_and_erases(self):
        # Matched against "Bayard" alone the letters would be "corrected"
        # into "promo Promobayard"; against both words they simply match.
        assert fixed("la promo Bayard, P R O M O B A Y A R D, rue") == "la promo Bayard, rue"

    def test_spelling_over_two_words_corrects_a_misheard_pair(self):
        assert fixed("la promo Bayart, P R O M O B A Y A R D, rue") == "la Promobayard, rue"

    def test_compound_replaces_only_the_last_element(self):
        assert fixed("rue Jules-Guède, G-U-E-S-D-E, à Lille") == "rue Jules-Guesde, à Lille"

    def test_one_letter_word_is_never_rewritten(self):
        out = fixed("SCIALE, A deux L, A-I-S, gérant")
        assert "L," in out or " L " in out or "L " in out
        assert "Ais" not in out.replace("SCIALE", "")

    def test_exactly_enclosing_parentheses_go_with_the_letters(self):
        assert fixed("société YESHUA (Y-E-C-H-O-U-A), sise") == "société YECHOUA, sise"

    def test_parenthesis_with_more_content_is_untouched(self):
        text = "PATUREAU (P-A-T-U-R-E-A-U avec un X) demeurant"
        assert fixed(text) == text

    def test_tags_are_untouched(self):
        text = "à ATIES. A-T-H-I-E-S, <photo 1:02> 62223"
        out = fixed(text)
        assert "<photo 1:02>" in out and out.startswith("à ATHIES.")

    def test_idempotent(self):
        text = "à ATIES. A-T-H-I-E-S, puis SCI BARLET, V.A.R.L.E.T. et NOREVIE, N O R E V I E, fin"
        once = fixed(text)
        assert fixed(once) == once

    def test_no_invented_word(self):
        text = "à ATIES. A-T-H-I-E-S, puis SCI BARLET, V.A.R.L.E.T. et rue Jules-Guède, G-U-E-S-D-E"
        out = fixed(text)
        assert unchanged_vocabulary(text, out)

    def test_hesitation_dots_elsewhere_are_not_cleaned(self):
        text = "alors... la SCI BARLET, V.A.R.L.E.T. et... voilà"
        assert fixed(text) == "alors... la SCI VARLET et... voilà"

    def test_text_without_spelling_is_returned_as_is(self):
        text = "Nous constatons que la porte est fermée à clé."
        assert fixed(text) == text


class TestDetector:
    def test_flags_with_actions(self):
        t = TranscriptResult(
            segments=[
                Segment(start=0, end=5, text="à ATIES. A-T-H-I-E-S, 62223"),
                Segment(start=5, end=10, text="NOREVIE, N O R E V I E"),
                Segment(start=10, end=15, text="le chien, P-A-T-U-R-E-A-U"),
                Segment(start=15, end=20, text="rien à signaler"),
            ]
        )
        flags = SpelledOutDetector().detect(t)
        assert [(f.segment_index, f.evidence["action"]) for f in flags] == [
            (0, "correct"),
            (1, "erase"),
            (2, "abstain"),
        ]
        assert flags[0].severity == Severity.WARNING
        assert flags[1].severity == Severity.INFO
        assert flags[0].evidence["replacement"] == "ATHIES"

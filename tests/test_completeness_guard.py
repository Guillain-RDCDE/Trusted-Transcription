"""Tests for the completeness guard of the repair stage."""

from __future__ import annotations

from trusted_transcription.repair.completeness_guard import (
    guarded_repair,
    lost_passage,
    max_output_words,
    net_loss,
    overproduces,
    split_in_two,
    words,
)

ROOMS = [
    "Entrée. Le sol est en carrelage beige, en bon état. Les murs sont peints en blanc. "
    "Le plafond ne présente aucune trace. Une applique murale fonctionne. "
    "La porte palière est blindée, la serrure trois points fonctionne.",
    "Séjour. Le parquet flottant présente des rayures devant la baie vitrée. "
    "Les murs sont peints en blanc cassé, un trou de cheville au mur nord. "
    "Le radiateur électrique fonctionne. Les volets roulants sont en état de marche.",
    "Cuisine. Le sol est carrelé, en bon état. Le plan de travail présente une rayure. "
    "L'évier deux bacs est propre, la robinetterie fonctionne. Les placards hauts ferment. "
    "La hotte aspirante est en état de marche. La fenêtre donne sur la cour.",
    "Salle de bain. La baignoire est propre, le joint silicone est noirci. "
    "Le carrelage mural est intact. Le miroir est fêlé dans l'angle. "
    "La ventilation fonctionne. Le meuble vasque ferme correctement.",
    "Chambre. La moquette est usée devant la porte. Les murs sont peints en gris clair. "
    "Le placard coulissant fonctionne. La fenêtre ferme, le volet est bloqué à mi-hauteur. "
    "Le radiateur fonctionne, le thermostat est cassé.",
]
FULL = " ".join(ROOMS)


def rephrase(text: str) -> str:
    return (
        text.replace("en bon état", "en état correct")
        .replace("fonctionne", "est en état de marche")
        .replace("présente", "montre")
    )


class TestNetLoss:
    def test_identical(self):
        r = net_loss(FULL, FULL)
        assert (r.max_net_loss, r.ratio) == (0, 1.0)

    def test_rephrasing_replaces_and_is_not_a_loss(self):
        r = net_loss(FULL, rephrase(FULL))
        assert r.max_net_loss < 10

    def test_amputation_in_the_middle(self):
        r = net_loss(FULL, " ".join(ROOMS[:2] + ROOMS[3:]))
        assert r.max_net_loss == len(words(ROOMS[2]))

    def test_passage_deleted_around_a_kept_word_counts_as_one_zone(self):
        # Delete the cuisine except one word kept in the middle.
        cuisine = words(ROOMS[2])
        kept = cuisine[len(cuisine) // 2]
        out = " ".join(ROOMS[:2] + [kept] + ROOMS[3:])
        r = net_loss(FULL, out)
        assert r.max_net_loss == len(cuisine) - 1

    def test_empty_source(self):
        assert net_loss("", "quelque chose").ratio == 1.0


class TestLostPassage:
    def test_good_work_is_not_a_loss(self):
        assert lost_passage(FULL, rephrase(FULL))[0] is False

    def test_swallowed_room_is_a_loss(self):
        lost, r = lost_passage(FULL, " ".join(ROOMS[:2] + ROOMS[3:]), min_net_loss_words=30)
        assert lost and r.max_net_loss >= 30

    def test_chatter_removed_is_not_a_loss(self):
        chatter = "euh alors bon on va dire que voilà c'est ça hein bon"
        assert lost_passage(FULL + " " + chatter, FULL)[0] is False

    def test_truncation_is_a_loss_even_in_small_pieces(self):
        # Drop every fourth word: no single zone is large, but the ratio is.
        out = " ".join(w for i, w in enumerate(words(FULL)) if i % 4 != 0)
        lost, r = lost_passage(FULL, out, min_net_loss_words=1000, min_ratio=0.8)
        assert lost and r.ratio < 0.8


class TestOverproduction:
    def test_bound(self):
        assert max_output_words(100) == 123
        assert max_output_words(0) == 8

    def test_within_bound(self):
        assert overproduces(FULL, rephrase(FULL)) is False

    def test_doubling_is_rejected(self):
        assert overproduces(FULL, FULL + " " + FULL) is True

    def test_short_source_can_gain_a_few_words(self):
        short = "Bonjour madame."
        assert overproduces(short, "Bonjour madame, nous commençons le constat.") is False


class TestSplitInTwo:
    def test_splits_at_the_sentence_closest_to_the_middle(self):
        left, right = split_in_two(FULL, min_units=3)
        assert left.endswith((".", "!", "?"))
        assert abs(len(words(left)) - len(words(right))) < 20
        assert words(left) + words(right) == words(FULL)

    def test_river_sentence_without_full_stop_splits_on_words(self):
        river = " ".join(["mot"] * 400)
        left, right = split_in_two(river, min_units=3)
        assert len(words(left)) == 200 and len(words(right)) == 200

    def test_too_short_is_not_split(self):
        assert split_in_two("un deux trois", min_units=3) is None


class Model:
    """A fake correction model with a configurable vice."""

    def __init__(self, vice):
        self.vice = vice
        self.calls: list[tuple[int, int]] = []  # (attempt, words in)

    def __call__(self, text: str, attempt: int) -> str:
        self.calls.append((attempt, len(words(text))))
        return self.vice(text, attempt)


def swallows_on_long_text(text: str, attempt: int) -> str:
    # Above a certain length, the model drops the cuisine when it is there.
    if len(words(text)) > 120 and ROOMS[2] in text:
        return rephrase(text.replace(ROOMS[2] + " ", ""))
    return rephrase(text)


class TestGuardedRepair:
    def test_good_model_passes_straight_through(self):
        model = Model(lambda t, a: rephrase(t))
        result = guarded_repair(FULL, model)
        assert result.text == rephrase(FULL)
        assert (result.retries, result.splits, result.irreducible) == (0, 0, 0)
        assert model.calls == [(0, len(words(FULL)))]

    def test_retry_recovers_a_swallowed_passage(self):
        model = Model(lambda t, a: rephrase(t) if a >= 1 else swallows_on_long_text(t, a))
        result = guarded_repair(FULL, model, min_net_loss_words=30)
        assert result.text == rephrase(FULL)
        assert result.retries == 1 and result.splits == 0

    def test_split_recovers_when_retries_do_not(self):
        model = Model(swallows_on_long_text)
        result = guarded_repair(FULL, model, min_net_loss_words=30)
        assert result.clean
        assert result.splits >= 1
        # Nothing lost: every room is in the output.
        for room in ROOMS:
            assert rephrase(room).split(".")[0] in result.text
        assert not overproduces(FULL, result.text)

    def test_doubling_model_is_bounded_at_every_level(self):
        model = Model(lambda t, a: t + " " + t)
        result = guarded_repair(FULL, model, min_net_loss_words=30)
        assert result.overproduction_rejections >= 1
        assert not overproduces(FULL, result.text)
        assert result.text == FULL  # nothing clean was ever produced

    def test_irreducible_loss_keeps_the_correction_not_the_raw_text(self):
        # A model that always drops the last sentence of whatever it gets.
        def drop_tail(t: str, a: int) -> str:
            ws = words(t)
            return " ".join(ws[: max(1, len(ws) - 60)])

        model = Model(drop_tail)
        result = guarded_repair(FULL, model, min_net_loss_words=30, max_depth=1)
        assert result.irreducible >= 1
        assert result.text != FULL
        assert any("irreducible" in step for step in result.trail)

    def test_attempt_number_is_passed_to_the_model(self):
        model = Model(lambda t, a: "" if a < 2 else rephrase(t))
        result = guarded_repair(FULL, model, max_retries=2)
        assert [a for a, _ in model.calls][:3] == [0, 1, 2]
        assert result.text == rephrase(FULL)

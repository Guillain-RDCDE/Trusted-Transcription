"""Spelled-out words — the spelling is authoritative.

When a speaker spells a word letter by letter ("ATIES. A-T-H-I-E-S",
"SCI BARLET, V.A.R.L.E.T.", "NOREVIE, N O R E V I E"), it is because
they expect the recognition to get it wrong — and it usually did. An
engine renders the letters faithfully and the misheard word next to
them. A draft that keeps both is wrong twice: the wrong name stays,
and the letters have to be deleted by hand.

The rule that came out of production, stated by the people who read
the drafts: **the spelling is authoritative.** This pass, with no
model in the loop:

* finds every spelled-out sequence (hyphenated, dotted, or spaced
  capitals);
* rebuilds the word from the letters;
* looks back at the one, two or three words before the sequence,
  picks the candidate that resembles the spelled word best, and
  **replaces it** when the resemblance is high enough;
* when the dictated word was already right, only erases the letters;
* otherwise abstains and leaves the text untouched — a reviewer with
  the audio decides.

Every guardrail below exists because a real text broke without it:

1. Space-separated letters count only when **all capitals**
   (``N O R E V I E``); lowercase would match "il y a a l'…".
2. A sequence never ends right before an apostrophe: the ``D`` of
   "D'accord" is an elision, not the last letter of the name.
3. A spelling may cover **several words** ("promo Bayard" spelled as
   one): one, two, then three words back are tried, so that the
   letters are not matched against the last word alone and "promo
   Promobayard" written.
4. In a hyphenated compound ("Jules-Guède") only the **last element**
   is replaced; the first would otherwise vanish.
5. A word of one or two letters is **never rewritten** ("A deux L,
   A-I-S" must not overwrite the "L").
6. The **only** criterion for a correction is resemblance. A "same
   initial" rule was tried and removed: it corrected nothing and
   invented forms.
7. The trailing abbreviation dot is swallowed **only for a dotted
   sequence** (``V.A.R.L.E.T.``); otherwise the sentence's full stop
   would go with it.
8. Abstain on: a digit inside the sequence, a speaker correcting
   themselves ("pardon", "je rectifie") just before, no word before,
   a spelling unrelated to any candidate, or a parenthesis that opens
   before the sequence and does not close right after it.
9. **No global punctuation clean-up**: only the junction created by
   the removal is tidied. That is what makes the pass idempotent.

Known limit, accepted on purpose: when the engine mishears the
spelling itself, the rule writes the misheard spelling. That is not
detectable mechanically; the reviewer catches it with the audio, and
the draft is still better than the wrong name plus the letters.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

MIN_LETTERS = 3
MIN_SIMILARITY = 0.55
MAX_WORDS_BACK = 3
SELF_CORRECTION_MARKERS = ("pardon", "je rectifie", "je me reprends", "non pas", "excusez")

# Letters with hyphens: A-T-H-I-E-S (three or more).
_HYPHEN = re.compile(r"(?<![\w-])(?:[^\W\d_]-){2,}[^\W\d_](?![\w-])", re.UNICODE)
# Letters with dots: V.A.R.L.E.T.  (three or more, trailing dot required)
_DOTTED = re.compile(r"(?<![\w.])(?:[^\W\d_]\.){3,}(?!\w)", re.UNICODE)
# Capitals with spaces: N O R E V I E (three or more, capitals only)
_SPACED = re.compile(r"(?<![\w])(?:[A-ZÀ-Ý] ){2,}[A-ZÀ-Ý](?![\w])")
# A sequence that carries a digit (C.A.R.A.2.D.) — recognised to abstain on.
_WITH_DIGIT = re.compile(
    r"(?<![\w.-])(?:[^\W_][.-]){2,}[^\W_]\.?(?![\w-])", re.UNICODE
)

_WORD_BEFORE = re.compile(r"([^\W\d_]+(?:'[^\W\d_]+)?(?:-[^\W\d_]+)*)\s*$", re.UNICODE)
_TAG = re.compile(r"<[^<>]{1,40}>")


@dataclass(frozen=True)
class Spelling:
    start: int
    end: int
    letters: str
    kind: str  # hyphen | dotted | spaced | digit

    @property
    def word(self) -> str:
        return self.letters


@dataclass(frozen=True)
class SpellingFix:
    spelling: Spelling
    action: str  # correct | erase | abstain
    dictated: str = ""
    replacement: str = ""
    similarity: float = 0.0
    reason: str = ""


def find_spellings(text: str) -> list[Spelling]:
    """Every spelled-out sequence in ``text``, left to right, non-overlapping."""
    found: list[Spelling] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= s or a >= e for s, e in taken)

    for kind, pattern in (("hyphen", _HYPHEN), ("dotted", _DOTTED), ("spaced", _SPACED)):
        for m in pattern.finditer(text):
            a, b = m.span()
            if not free(a, b) or _inside_tag(text, a):
                continue
            a, b = _back_off_elision(text, a, b, kind)
            letters = re.sub(r"[-. ]", "", text[a:b])
            if len(letters) < MIN_LETTERS:
                continue
            found.append(Spelling(a, b, letters, kind))
            taken.append((a, b))
    for m in _WITH_DIGIT.finditer(text):
        a, b = m.span()
        if any(c.isdigit() for c in m.group()) and free(a, b):
            found.append(Spelling(a, b, re.sub(r"[-.]", "", m.group()), "digit"))
            taken.append((a, b))
    return sorted(found, key=lambda s: s.start)


def _inside_tag(text: str, pos: int) -> bool:
    return any(m.start() < pos < m.end() for m in _TAG.finditer(text))


def _back_off_elision(text: str, a: int, b: int, kind: str) -> tuple[int, int]:
    """Guardrail 2: do not eat the letter of an elision ("N. D'accord")."""
    if kind == "dotted":
        return a, b
    while b > a and b < len(text) and text[b] in "'’":
        # The last letter belongs to the next word: drop it and its separator.
        b -= 1
        while b > a and text[b - 1] in "-. ":
            b -= 1
    return a, b


def _fold(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s.casefold())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(a=_fold(a), b=_fold(b), autojunk=False).ratio()


def _words_before(
    text: str, pos: int, enclosed: bool = False
) -> tuple[list[tuple[int, int, str]], bool]:
    """Up to MAX_WORDS_BACK words ending before ``pos``, nearest first.

    Returns the words and whether an opening parenthesis blocked the
    walk (guardrail 8: the sequence sits inside a parenthesis that
    holds other things too). ``enclosed`` says the sequence is exactly
    wrapped in a parenthesis pair, whose opening bracket is then
    stepped over once.
    """
    words: list[tuple[int, int, str]] = []
    cursor = pos
    blocked = False
    for _ in range(MAX_WORDS_BACK):
        head = text[:cursor].rstrip()
        if enclosed and head.endswith("("):
            head = head[:-1].rstrip()
            enclosed = False
        # Separators allowed between the word and the sequence.
        while head and head[-1] in ",;:.":
            head = head[:-1].rstrip()
        if head.endswith("("):
            blocked = True
            break
        m = _WORD_BEFORE.search(head)
        if not m:
            break
        words.append((m.start(1), m.end(1), m.group(1)))
        cursor = m.start(1)
    return words, blocked


def _match_case(model: str, word: str) -> str:
    if model.isupper():
        return word.upper()
    if model[:1].isupper():
        return word[:1].upper() + word[1:].lower()
    return word.lower()


def resolve(text: str) -> list[SpellingFix]:
    """Decide, for every spelling, what to do — without touching the text."""
    fixes: list[SpellingFix] = []
    for sp in find_spellings(text):
        if sp.kind == "digit":
            fixes.append(SpellingFix(sp, "abstain", reason="digit inside the sequence"))
            continue

        # Guardrail 8: "(A-B-C avec un X)" — opened before, not closed right after.
        before = text[: sp.start].rstrip()
        after = text[sp.end :].lstrip()
        enclosed = before.endswith("(") and after.startswith(")")
        if before.endswith("(") and not enclosed:
            fixes.append(
                SpellingFix(sp, "abstain", reason="parenthesis holds more than the spelling")
            )
            continue

        words, _ = _words_before(text, sp.start, enclosed)
        context = _fold(text[max(0, sp.start - 40) : sp.start])
        if any(marker in context for marker in SELF_CORRECTION_MARKERS):
            fixes.append(SpellingFix(sp, "abstain", reason="speaker corrected themselves"))
            continue
        if not words:
            fixes.append(SpellingFix(sp, "abstain", reason="no word before the spelling"))
            continue

        best: tuple[float, int, str] | None = None  # (ratio, words used, dictated)
        for n in range(1, len(words) + 1):
            chunk = words[:n]
            dictated = " ".join(w for _, _, w in reversed(chunk))
            candidate = dictated.replace(" ", "")
            if n == 1:
                # Guardrail 4: compare the last element of a compound.
                candidate = candidate.rsplit("-", 1)[-1]
                if len(candidate) <= 2:
                    continue  # guardrail 5
            ratio = similarity(candidate, sp.word)
            if best is None or ratio > best[0]:
                best = (ratio, n, dictated)

        if best is None:
            fixes.append(SpellingFix(sp, "abstain", reason="only one- or two-letter words before"))
            continue

        ratio, n, dictated = best
        last_element = dictated.rsplit("-", 1)[-1] if n == 1 else dictated.replace(" ", "")
        if _fold(last_element) == _fold(sp.word):
            # Already right — including "promo Bayard" spelled as one word:
            # the words stay as dictated, only the letters go.
            fixes.append(SpellingFix(sp, "erase", dictated, dictated, round(ratio, 3),
                                     "dictated word already matches"))
        elif ratio >= MIN_SIMILARITY:
            if n == 1 and "-" in dictated:
                head, _, tail = dictated.rpartition("-")
                replacement = f"{head}-{_match_case(tail, sp.word)}"
            else:
                replacement = _match_case(dictated.split()[-1], sp.word)
            fixes.append(SpellingFix(sp, "correct", dictated, replacement, round(ratio, 3),
                                     "spelling overrides the dictated word"))
        else:
            fixes.append(SpellingFix(sp, "abstain", dictated, "", round(ratio, 3),
                                     "spelling unrelated to the words before"))
    return fixes


def apply_spellings(text: str) -> tuple[str, list[SpellingFix]]:
    """Apply ``resolve`` right to left so that offsets stay valid."""
    fixes = resolve(text)
    out = text
    for fix in sorted(fixes, key=lambda f: f.spelling.start, reverse=True):
        if fix.action == "abstain":
            continue
        out = _rewrite(out, fix)
    return out, fixes


def _rewrite(text: str, fix: SpellingFix) -> str:
    """Remove one sequence, tidy the junction it leaves, apply the correction.

    Guardrail 7 is carried by the pattern itself: a dotted sequence
    matches *with* its final dot, a hyphenated one stops at its last
    letter, so a sentence's full stop after "V-A-R-L-E-T." survives.
    Guardrail 9: nothing outside the junction is touched.
    """
    sp = fix.spelling
    head, tail = text[: sp.start], text[sp.end :]

    # Only a parenthesis pair that encloses exactly the sequence goes with it.
    if head.rstrip().endswith("(") and tail.lstrip().startswith(")"):
        head = head.rstrip()[:-1]
        tail = tail.lstrip()[1:]

    # The separator that introduced the sequence (", " / " ") goes; a full
    # stop stays, it closed the dictated word's sentence.
    head = re.sub(r"[\s,;:]*$", "", head)
    tail = tail.lstrip(" ")
    if head and tail and head[-1] in ".!?" and tail[0] in ".,;:":
        # "ATIES. A-T-H-I-E-S, 62223": the comma continued the sequence,
        # the sentence already ended before it.
        tail = tail[1:].lstrip(" ")
    if not head:
        tail = tail.lstrip(".,;: ")
        junction = ""
    elif not tail or tail[0] in ".,;:!?)":
        junction = ""
    else:
        junction = " "

    if fix.action == "correct":
        words, _ = _words_before(head, len(head))
        n = len(fix.dictated.split())
        start, end = words[n - 1][0], words[0][1]
        head = head[:start] + fix.replacement + head[end:]

    return head + junction + tail


def unchanged_vocabulary(source: str, output: str) -> bool:
    """No invented word: every output word is in the source or is a spelled join."""
    src_words = {_fold(w) for w in re.findall(r"[^\W\d_]+", source)}
    src_words |= {_fold(sp.word) for sp in find_spellings(source)}
    src_words |= {_fold(w.rsplit("-", 1)[-1]) for w in re.findall(r"[^\W\d_]+-[^\W\d_]+", source)}
    for w in re.findall(r"[^\W\d_]+", output):
        if _fold(w) not in src_words:
            return False
    return True

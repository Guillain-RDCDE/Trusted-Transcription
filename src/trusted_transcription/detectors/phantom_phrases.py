"""Phantom phrases, by language.

Whisper learned from captioned video. On silence, noise or a starved
slice it returns the captions' boilerplate: sign-offs, subscription
calls, and above all **subtitle credits**. The credits are the most
reliable signature, because nobody dictates them: a broadcaster's
subtitling department, a volunteer captioning community, a
subtitler's site.

The phrases differ by language, and a detector that only knows the
English ones is blind on everything else. Each list below holds
phrases repeatedly observed in the wild for that language. They are
anchored loosely (accents optional, punctuation free) because the
engine varies them.

Only phrases that cannot be legitimate dictation belong here. "Thank
you" alone is speech; "Thank you for watching" in a legal report is
not.
"""

from __future__ import annotations

import re

_FLAGS = re.IGNORECASE | re.UNICODE

PHANTOM_PHRASES: dict[str, list[re.Pattern[str]]] = {
    "en": [
        re.compile(r"thank(s| you)\s+for\s+watching", _FLAGS),
        re.compile(r"thank(s| you)\s+for\s+listening", _FLAGS),
        re.compile(r"subscribe\s+to\s+(my|the|our)\s+channel", _FLAGS),
        re.compile(r"(please\s+)?like\s+and\s+subscribe", _FLAGS),
        re.compile(r"subtitles?\s+by\s+the\s+amara\.org\s+community", _FLAGS),
        re.compile(r"see\s+you\s+in\s+the\s+next\s+video", _FLAGS),
    ],
    "fr": [
        re.compile(r"sous[- ]titr(es|age)\s+(r[ée]alis[ée]s?\s+)?par\s+la\s+communaut[ée]", _FLAGS),
        re.compile(r"sous[- ]titrage\s+soci[ée]t[ée]\s+radio[- ]canada", _FLAGS),
        re.compile(r"sous[- ]titrage\s+st['’ ]?\s*501", _FLAGS),
        re.compile(r"merci\s+d['’]avoir\s+regard[ée]", _FLAGS),
        re.compile(r"abonnez[- ]vous\s+[àa]\s+(la|ma|notre)\s+cha[iî]ne", _FLAGS),
        re.compile(r"soustitreur\.com", _FLAGS),
    ],
    "de": [
        re.compile(r"untertitel\s+der\s+amara\.org[- ]community", _FLAGS),
        re.compile(r"untertitel(ung)?\s+im\s+auftrag\s+des\s+zdf", _FLAGS),
        re.compile(r"vielen\s+dank\s+f[üu]r['’]?s?\s+zuschauen", _FLAGS),
    ],
    "es": [
        re.compile(r"subt[íi]tulos\s+(realizados\s+)?por\s+la\s+comunidad\s+de\s+amara", _FLAGS),
        re.compile(r"gracias\s+por\s+ver\s+el\s+v[íi]deo", _FLAGS),
        re.compile(r"suscr[íi]bete\s+al\s+canal", _FLAGS),
    ],
    "it": [
        re.compile(r"sottotitoli\s+(creati\s+)?dalla\s+comunit[àa]\s+(di\s+)?amara", _FLAGS),
        re.compile(r"sottotitoli\s+e\s+revisione\s+a\s+cura\s+di", _FLAGS),
        re.compile(r"grazie\s+per\s+(aver\s+guardato|la\s+visione)", _FLAGS),
    ],
    "pt": [
        re.compile(r"legendas?\s+pela\s+comunidade\s+(de\s+)?amara", _FLAGS),
        re.compile(r"obrigad[oa]\s+por\s+assistir", _FLAGS),
    ],
}

# Language-independent: the credit's address, and degenerate stubs.
UNIVERSAL_PHRASES: list[re.Pattern[str]] = [
    re.compile(r"amara\.org", _FLAGS),
    re.compile(r"^\s*you\.?\s*$", _FLAGS),  # a segment that is only "you"
    re.compile(r"^\s*\.+\s*$"),
]


def patterns_for(languages: list[str] | None = None) -> list[re.Pattern[str]]:
    """Patterns for the given ISO codes, or for every known language.

    Whisper's phantom phrases follow the *decoded* language, which is
    not always the expected one — a French dictation that drifted
    returns English credits. Checking every list is the safe default.
    """
    selected: list[re.Pattern[str]] = []
    for code, patterns in PHANTOM_PHRASES.items():
        if languages is None or code in languages:
            selected.extend(patterns)
    return selected + UNIVERSAL_PHRASES


def match_phantom(text: str, languages: list[str] | None = None) -> re.Pattern[str] | None:
    for pattern in patterns_for(languages):
        if pattern.search(text):
            return pattern
    return None

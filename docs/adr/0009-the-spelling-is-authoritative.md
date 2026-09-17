# ADR 0009: The spelling is authoritative

## Status
Accepted (deployed in production, July 2026)

## Context
Formal dictation is full of spelled-out names: "à ATIES, A-T-H-I-E-S",
"SCI BARLET, V.A.R.L.E.T.", "NOREVIE, N O R E V I E". The engine
renders the letters faithfully — and the misheard word right next to
them. Asking the correction model to "clean up spellings" through its
prompt worked about half the time: a sizeable share of corrected
drafts still carried the letters.

Reading the drafts changed the question. **When a speaker spells a
word, it is because they expect the recognition to get it wrong** —
and it did: "ATIES" for ATHIES, "BARLET" for VARLET, "Guède" for
Guesde. Erasing the letters would keep the wrong name. The people who
read the drafts stated the rule: *the spelling is authoritative*.

## Decision
A deterministic pass, no model in the loop, that **rebuilds the word
from the letters and corrects the dictated word before it**. When the
dictated word was already right, it only erases the letters. When it
cannot decide, it abstains and leaves everything in place: a reviewer
with the audio decides.

The only criterion for a correction is resemblance between the
spelled word and a candidate among the one, two or three words
before the sequence, above a fixed threshold. A "same initial" rule
was tried and removed: it corrected nothing and invented forms.

Implementation: `trusted_transcription.repair.spellings` (the pass)
and `detectors/spelled_out.py` (the flags). Operator view:
`tt spell <transcript.json>`.

## The guardrails, each from a text that broke

1. **Space-separated letters count only in capitals.** Lowercase
   matched "il y a a l'…" — several false positives per few hundred
   texts.
2. **A sequence never ends right before an apostrophe.** The `D` of
   "D'accord" after "G-A-L-I-C-H-O-N" was swallowed into "Galichond".
3. **A spelling may cover several words.** "promo Bayard" spelled as
   one produced "promo Promobayard" until two and three words back
   were tried.
4. **In a compound, replace only the last element.** "Jules-Guède"
   lost its "Jules".
5. **Never rewrite a one- or two-letter word.** "A deux L, A-I-S"
   overwrote the "L".
6. **Resemblance is the only criterion** (see above).
7. **Swallow the abbreviation dot only after a dotted sequence.**
   Otherwise the sentence's full stop went with it.
8. **Abstain** on a digit in the sequence, a speaker correcting
   themselves just before, no word before, an unrelated spelling —
   and on a parenthesis that opens before the sequence and holds
   more than it. The first version crossed every opening parenthesis
   and turned "PATUREAU (P-A-T-U-R-E-A-U avec un X)" into
   "PATUREAU ( avec un X)". A parenthesis pair that encloses exactly
   the sequence goes with it.
9. **No global punctuation clean-up.** Only the junction created by
   the removal is tidied. A global tidy ate the "..." hesitations of
   the original text and broke idempotence.

## Validation
Replayed on several hundred real dictations without writing
anything: about one text in nine changed; corrections, erasures and
abstentions were counted separately, and every correction was read
one by one — it is the only place where the pass rewrites content.
Three invariants held on the whole corpus: inline tags unchanged,
idempotent (a second pass changes nothing), and **no invented word**
(every output word exists in the input or is the join of a spelled
sequence of the input). The invariant is a function in the module
and a test.

Then, a second pass a month later on a real regression: spellings in
parentheses were systematically skipped. The fix was verified against
the previous version on a thousand real texts: every difference was
a parenthesis case, none unexpected.

## Known limit, accepted on purpose
Sometimes the engine mishears the *spelling* itself ("Z O U L I K H
K H A"). The rule then writes the misheard spelling. That is not
detectable mechanically — the dictated word and the spelling look
alike — and the reviewer catches it with the audio. Before the pass,
those texts carried the wrong name *and* the letters. Giving up the
correction to avoid this case was considered and refused.

## Consequences
- The pass runs after the tag firewall and before any titling or
  structuring stage, which must see a clean text.
- Kill switch and downstream firewall (tags identical, text not
  truncated); any exception returns the original text.
- New dictations only. No retroactive rewrite of delivered drafts.

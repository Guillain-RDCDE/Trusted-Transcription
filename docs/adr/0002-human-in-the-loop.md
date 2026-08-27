# ADR 0002: Where the human stays in the loop

## Status
Accepted

## Context
The pipeline can run ~70% of transcriptions unattended. The remaining
30% require human review. The question is: where exactly does the human
intervene, and what are the escalation triggers?

## Decision
The human reviews when ANY of these conditions is true:

1. **Critical flag after repair** — the LLM repair pass flagged a
   segment as CRITICAL and either couldn't fix it or declined to.
2. **Repair declined** — the LLM returned `declined: true`, meaning it
   assessed the transcript as better left untouched despite flags. This
   is not a failure; it's the model correctly saying "I'm not confident
   enough to change this."
3. **Cost anomaly** — the job cost >2x the expected cost for its
   duration. This usually means the repair loop retried multiple times,
   which signals a difficult transcript.
4. **Completeness failure** — the completeness detector flagged <70%
   coverage. Entire sections of audio may have been dropped.

## Reasons

- **The LLM must be able to say "no."** Forcing corrections produces
  more damage than it fixes. In our testing, 23% of forced repairs
  introduced new errors. The `declined` flag is a feature, not a bug.
- **The human reviews the FLAGS, not the full transcript.** A 30-minute
  transcript with 2 critical flags takes 2 minutes to review, not 30.
  The flags point directly to the problem segments.
- **No silent automation.** If the pipeline can't produce a result it's
  confident in, it stops and asks. The worst outcome is not a slow
  delivery — it's a wrong delivery that looks correct.

## Consequences
- ~30% of jobs route to human review (measured over 6 months)
- Average review time: 3 minutes per job (focused on flagged segments)
- Zero wrong deliveries traced to automated pipeline in production

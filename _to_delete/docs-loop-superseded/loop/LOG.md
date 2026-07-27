# Experiment Log

Status: Authoritative (process record).

Last updated: 2026-07-27.

Append-only memory for the nightly loop. **Read this before constructing any
attack.** Its only job is to stop the loop re-running experiments — including
the ones that failed, which are the majority and the easiest to repeat by
accident.

Same role as autoresearch's experiment log: what was tried, what the result was,
whether it was kept.

## Format

One row per experiment. Never edit a row after it is written; supersede it with
a new one.

| Field | Meaning |
| --- | --- |
| `#` | Sequential, never reused |
| Date | Night the experiment ran |
| Target | Which `program.md` target, by number |
| Attack | One line — what was attempted |
| Result | `confirmed` / `not reproduced` / `already known` / `out of scope` |
| Verifier | Reproduced or failed to reproduce |
| Disposition | `promoted P-NNNN` / `confirmed, unpromoted` / `discarded` |

## Nightly summary

The confirm rate is the loop's check on itself. Most experiments should fail —
that is the healthy state, and it is what autoresearch looks like too. A
sustained rate above ~25% means the verifier is rubber-stamping, and the fix is
to raise the bar in `program.md` or add a second verifier. It is not evidence
that the architecture is full of holes.

| Date | Experiments | Confirmed | Rate | Promoted |
| --- | --- | --- | --- | --- |
| — | — | — | — | — |

## Experiments

| # | Date | Target | Attack | Result | Verifier | Disposition |
| --- | --- | --- | --- | --- | --- | --- |
| — | — | — | — | — | — | — |

No experiments run yet. The first night populates this table.

## Exhausted targets

Targets where several consecutive nights produced nothing. Not permanently
closed — a change to the underlying document reopens one — but deprioritized
until then. Record which document version was attacked, so a later edit can
revive the target.

| Target | Nights spent | Last attacked against | Reopens when |
| --- | --- | --- | --- |
| — | — | — | — |

## Confirmed but unpromoted

Holes that reproduced but had no free slot in the proposal queue. These are
ready to promote without re-running the experiment.

| # | Hole | Breaks | Confirmed |
| --- | --- | --- | --- |
| — | — | — | — |

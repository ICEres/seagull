# Proposals

Status: Authoritative (process).

Last updated: 2026-07-27.

The decision queue. Confirmed holes from [The Agent Loop](../agent-loop.md)
graduate into proposals here; maintainer decides them; accepted ones are applied in
a later human-initiated session.

This file defines only the format and the lifecycle. The loop that feeds it is
defined in [agent-loop.md](../agent-loop.md), and its strategy in
[loop/program.md](../loop/program.md).

## Lifecycle

```text
confirmed hole (LOG.md)  ->  Open  ->  Accepted   ->  Applied
                                   ->  Rejected   (permanent, in LEDGER.md)
                                   ->  Superseded (by a later proposal, which says why)
```

**Maximum three Open at a time.** The loop can confirm twenty holes a night; the
constraint is maintainer's decisions, not the agent's throughput. Confirmed holes
with no free slot wait in `LOG.md` under *Confirmed but unpromoted* — already
reproduced, promotable later without re-running the experiment.

**Rejections are permanent memory.** A rejected claim may only be re-opened if
new evidence appeared, and the new proposal must state what changed. Without
this the loop re-proposes the same idea indefinitely.

## Format

Filename `NNNN-short-slug.md`, four digits, never reused.

```markdown
# P-NNNN: <title>

Status: Open | Accepted | Rejected | Superseded
Opened: YYYY-MM-DD
Decided: YYYY-MM-DD (blank while Open)
Targets: <the Authoritative doc and section this would change>
Trigger: <LOG.md experiment number, or what else surfaced it>

## Claim
One sentence. If it needs two, it is two proposals.

## Why now
What forces the decision, and what deferring costs.

## Evidence
Repo `path:line`, or a primary source URL. At least one.

## Reproduction
The steps a verifier followed to confirm the hole, and which
Definition-of-Done criterion, stage claim, contract row, or threat-model row
it breaks.

## What it changes
The exact edit list — file, section, and what the new text asserts.

## What it does not change
Especially anything in the Compatibility Contract or the Definition of Done.

## Falsifier
What observation would show this proposal is wrong.

## Recommended answer
Stated plainly.

## If you do nothing
What the project looks like in three months without this decision.
```

A proposal with no Reproduction section did not come from a confirmed hole and
needs a reason for existing.

## Related

- [The Agent Loop](../agent-loop.md) — how holes are found
- [Program](../loop/program.md) — what the loop attacks
- [Log](../loop/LOG.md) — experiment memory
- [Ledger](LEDGER.md) — queue state and rejections

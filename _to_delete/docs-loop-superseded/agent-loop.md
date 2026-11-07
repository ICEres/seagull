# The Agent Loop

Status: Authoritative (process).

Last updated: 2026-07-27.

How agents improve seagull's concept, structure, and proposals — not its code.

The shape is [karpathy/autoresearch](https://github.com/karpathy/autoresearch),
adapted. This document says what transfers, what does not, and what replaces the
part that does not.

## What autoresearch does

An agent runs overnight and hill-climbs a model:

```text
read program.md          (human-written instructions and strategy)
modify train.py          (the one file the agent may change)
train for exactly 5 min  (fixed wall-clock budget)
measure val_bpb          (lower is better)
keep or discard
repeat
```

Roughly 12 experiments an hour, ~100 overnight. You read the log in the morning.

Four properties make it work, and all four are load-bearing:

1. **One scalar metric.** `val_bpb` is comparable across every change —
   deliberately vocab-size-independent so architectural experiments compare
   fairly. Without a common yardstick there is no keep-or-discard.
2. **A fixed budget per experiment.** Five minutes of wall clock, not "until
   converged." Results are comparable because the cost is constant.
3. **One mutable artifact.** `train.py` and nothing else. `prepare.py` is
   human-only. Bounded scope, bounded diff, trivial revert.
4. **A separation of ownership.** The human writes `program.md`; the agent
   writes `train.py`. The human's leverage is strategy, not edits.

Plus the log: a record of what was tried, so the agent stops re-running the same
experiment.

## The part that does not transfer

**There is no `val_bpb` for concept work, and there will not be one.**

Karpathy makes this argument himself in
[Verifiability](https://karpathy.bearblog.dev/verifiability/) (17 Nov 2025):
a task is optimizable when it is verifiable, in an environment that is
**resettable**, **efficient**, and **rewardable**. autoresearch works because ML
training is all three. "Is this architecture better" is none of them.

The tempting fix — have a model score the architecture 1–10 and hill-climb that
— fails in the specific way judge-based objectives always fail: after enough
iterations the agent optimizes the judge rather than the docs. Given ~100
experiments a night, that happens quickly and invisibly, and the output is
confident prose that scores well and says nothing.

So a direct port produces a machine that generates architecture documents all
night. The bottleneck was never generating them.

## What replaces it: invert the direction

Improvements are not verifiable. **Attacks are.**

"This architecture is better" cannot be checked. "Here is a concrete sequence of
operations, allowed by the accepted architecture, that violates Definition-of-
Done criterion 6" can be — by reading the same documents and following the
steps. It either reproduces or it does not.

So the loop does not try to write a better architecture. It tries to **break the
one that exists**, ~100 times a night, and the score is confirmed holes.

| autoresearch | this loop |
| --- | --- |
| `program.md` — human strategy | `docs/loop/program.md` — the maintainer's standing instructions: what to attack, what is off-limits, what counts as a real hole |
| `train.py` — the one mutable file | The attack, plus its reproduction steps. The incumbent docs are never mutated |
| 5 minutes wall clock | One attack per experiment, bounded. Cheap and comparable |
| `val_bpb`, lower is better | **Confirmed holes, higher is better** — an attack that a second agent reproduces against the docs |
| keep or discard | A hole survives only if an independent verifier reproduces it. Otherwise it is discarded to the log |
| checkpoints + modified `train.py` | `docs/proposals/` — confirmed holes graduate into decisions |
| experiment log | `docs/loop/LOG.md` — every attempt, kept or discarded, so no attack is run twice |
| ~100 overnight, read in the morning | Same |

The inversion also fixes the ownership problem. autoresearch can let the agent
rewrite `train.py` because it is disposable. seagull's Authoritative documents
have a single human voice and cannot be agent-mutable without destroying the
thing that makes them authoritative. Attacking them requires no write access at
all.

### Why this project is unusually attackable

seagull already ships its own test oracles, which is why this works here and
would not work on most repositories:

- **Definition of Done** — seven criteria, each falsifiable, in
  `migration-plan.md`.
- **Stage preconditions, acceptance, rollback, blast radius** — each stage makes
  claims that can be walked through and broken.
- **The Compatibility Contract** — an explicit frozen list. A violation is a
  fact, not an opinion.
- **The threat model** — assets, adversaries, boundaries, controls. Every row is
  an invitation to find an uncovered path.
- **CONTEXT.md's boundary rules and naming rules** — checkable against every
  other document.
- **Verification results** `pass` / `fail` / `absent` / `unsupported` — a
  document that renders `absent` as verified is a bug with a name.

An attack targets one of these and produces reproduction steps. That is the
experiment.

## The loop

```text
read docs/loop/program.md            <- the maintainer's strategy, reread every iteration
read docs/loop/LOG.md                <- what has already been tried
pick one target not already exhausted
construct one attack, bounded
attempt reproduction against the documents, citing path:line
spawn an independent verifier, told to fail the reproduction
    reproduced  -> confirmed hole, append to LOG, promote if the queue has room
    not reproduced -> append to LOG as attempted-and-failed, discard
repeat until the budget is spent
```

Overnight, unattended. In the morning the maintainer reads only the confirmed holes.

**Promotion is rate-limited, the loop is not.** The agent may find twenty holes a
night. At most three become Open proposals in `docs/proposals/`, because the
queue's limit is maintainer decisions, not the agent's throughput. The rest sit
in the log, already reproduced, ready to promote when a slot frees.

## Verification independence

Attacks are constructed by one subagent and verified by a different one,
dispatched separately with its own context. The whole metric rests on that, so
it is worth being exact about what it buys and what it does not.

**Enforced:**

- Attacker and verifier are separate dispatches. Neither sees the other's
  reasoning.
- The verifier receives **only the reproduction artifact** — target, steps,
  `path:line` citations, and the oracle row claimed broken. Never the attacker's
  argument, prose, or stated confidence. The difference between *"check this
  argument"* and *"follow these steps and report what you observe"* is the
  difference between something persuadable and something closer to a
  measurement.
- The verifier **stages the cited documents itself** rather than trusting
  excerpts quoted into its prompt, so a misquoted or invented citation fails.
- The verifier's instruction is adversarial — fail this — not neutral.
- The orchestrator records the verdict and may not overrule it.

**Not fixed by orchestration:** same model, same priors. Two instances reading
the same documents make correlated errors, and context independence is not
judgment independence. No amount of fan-out removes this; it is the standing
limit of the design.

**So the loop carries a falsifier for itself: the confirm rate.** In
autoresearch most experiments fail — that is the normal, healthy state. If this
loop confirms a large fraction of its own attacks, the verifier is
rubber-stamping and the number means nothing regardless of how cleanly the
agents were dispatched. `LOG.md` tracks it per night.

A sustained confirm rate above roughly 25% is a signal to raise the bar in
`program.md` or add a second verifier — not evidence that the architecture is
full of holes.

## Ownership

The single cleanest idea in autoresearch, kept verbatim in spirit:

| Artifact | Owner | Notes |
| --- | --- | --- |
| `docs/loop/program.md` | **maintainer** | The control surface. Change the loop's behaviour by editing this, not by editing prompts |
| `docs/loop/LOG.md` | agent | Append-only |
| `docs/proposals/*` | agent writes, maintainer decides | |
| Everything `Status: Authoritative` | **maintainer** | Agent never writes. This is what makes attacking them meaningful |
| `CONTEXT.md`, Compatibility Contract, Definition of Done, stage acceptance, Disposition Register verdicts | **maintainer** | Never, under any justification |

An agent change that cannot name the check or the confirmed hole that authorized
it is a proposal, not a fix.

## Failure modes

Named, because each one has already killed a loop somewhere.

| Failure | Why it happens | Guard |
| --- | --- | --- |
| **Judge-hacking** | Any scalar produced by a model gets optimized instead of the goal | Blind verification, plus the confirm rate as a check on the verifier itself |
| **Verifier capture** | The orchestrator saw the attack and frames it favourably when handing it on | The verifier gets the reproduction artifact verbatim and re-stages the cited documents itself |
| **Attack inflation** | Trivial or restated holes inflate the count | The verifier rejects anything already in LOG.md, and anything whose reproduction does not cite `path:line` |
| **Re-running experiments** | No memory across iterations | LOG.md is read before every attack and records failures, not just successes |
| **Understanding outrun** | 100 experiments a night, one human | Promotion capped at three Open; the rest wait in the log |
| **Vacuity drift** | Over many nights, claims narrow until they are unattackable and useless | `program.md` names the targets; if a night produces only trivia, that is a signal to change the strategy, not the loop |
| **Scope creep into code** | The most attackable surface is running code, which is not this loop's job | `program.md` declares code out of scope. Code findings go to the migration plan, not here |

The honest one: **a night that finds nothing is a real result**, and should be
reported as one line. autoresearch's experiments mostly fail too.

## Cadence

Not weekly. Overnight, like autoresearch — kick it off, read the log in the
morning. `Seagull nightly loop` runs it unattended; the maintainer can also drive it
interactively for a specific target.

The previous version of this process ran a weekly proposal cycle on a cron. A
schedule is what you build when you have no metric; the clock stands in for the
signal. That trigger is deleted.

## Related

- [Program](loop/program.md) — the strategy file maintained by the project owner
- [Log](loop/LOG.md) — experiment memory
- [Proposals](proposals/README.md) — where confirmed holes become decisions
- [Doc Status](doc-status.md), [Migration Plan](../packages/gulls/docs/migration-plan.md)

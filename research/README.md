# seagull product loop

Decides **what seagull should be** — who it is for, what it does first, and what
nobody else already does. Not how it is built: that is
`../packages/gulls/docs/agent-voice-and-discovery.md`, which this loop is
upstream of and never edits.

This directory is tracked in the seagull repo. `variants/` and `experiments/`
are gitignored (see `.gitignore` here) because they grow by ~100 files a night;
`proposal.md`, `results.tsv`, and `champion.log` are the record and are tracked.

The shape is [karpathy/autoresearch](https://github.com/karpathy/autoresearch).

## Files

```
README.md      this file — context
program.md     the instructions the agent follows. Ported from autoresearch's program.md
battery.md     the evaluation harness. READ-ONLY, ground truth
proposal.md    the file the agent modifies. What seagull is
results.tsv    one row per experiment. The cumulative record
champion.log   one line per time the champion changed
variants/      every variant ever tried, kept forever
_reference/    surveyed landscape, so overlap lenses do not re-derive settled ground
```

## The mapping

| autoresearch | here |
| --- | --- |
| `train.py` — the one file the agent edits | `proposal.md` |
| `prepare.py` — read-only, holds the evaluation | `battery.md` |
| `program.md` — instructions to the agent | `program.md` |
| `results.tsv` — one row per run | `results.tsv` |
| 5-minute fixed budget | one battery per variant |
| `val_bpb`, lower is better | survivals out of 6, higher is better |
| git commit to advance, git reset to revert | copy the winner over `proposal.md`; a loser is simply not copied |
| `uv run train.py` | dispatch six attacker subagents |
| ~12/hour, ~100 overnight | same |

## Why the metric is survival and not a score

autoresearch works because `val_bpb` exists: one number, comparable across every
change. Concept work has no such number, and Karpathy says why in
[Verifiability](https://karpathy.bearblog.dev/verifiability/) — a task is
optimizable when it is verifiable, in an environment that is resettable,
efficient, and rewardable. "Is this a better product idea" is none of those.

The tempting fix, having a model score the idea 1–10, fails the way judge-based
objectives always fail: at ~100 experiments a night the agent optimizes the
judge, and you wake up to a beautifully written proposal that commits to
nothing.

What makes this loop scoreable is that maintainer set two criteria that are
**externally checkable**: must not overlap an existing project, must fit a real
human need. "Does this already exist" has a hard answer, and the answer is a
URL. So overlap kills are fatal and evidence-bearing, need kills require a cited
substitute, and lens 6 exists to stop the loop escaping both by getting vague.

See `battery.md` for the harness and its own falsifier.

## Ownership

| Artifact | Owner |
| --- | --- |
| `program.md`, `battery.md` | **maintainer.** The dials. Editing these mid-run invalidates earlier rows |
| `proposal.md`, `results.tsv`, `variants/`, `champion.log` | the agent |
| Everything outside this directory | **maintainer.** The world the proposal is measured against |

## Reading the output

The morning report is the **diff to `proposal.md`** and the causes of death, not
a summary of the night's thinking. Most nights should read:

```
41 variants, champion held. Best challenger died to overlap-products (<url>).
```

That is a real result. The `results.tsv` kill column accumulates into the more
valuable artifact anyway: a map of which claims are already taken, and by whom.

## Why there is no git here

autoresearch advances by `git commit` and reverts by `git reset --hard`. That
does not work on this mount: the device bridge blocks `unlink`, so git cannot
clear its own `index.lock` / `HEAD.lock`, and `reset --hard`, `checkout -b`, and
even a second `commit` fail with *"may have crashed in this repository earlier:
remove the file manually to continue."* Verified, not assumed — a git repo was
initialised here and broke on the first revert. It is parked in `_superseded/`.

The copy-based champion is the substitute and needs no deletes: a winner is
copied over `proposal.md`, a loser is simply never copied. `variants/` keeps
every attempt and `champion.log` replaces `git log`. Nothing is ever removed,
which is also why `results.tsv` rows are append-only.

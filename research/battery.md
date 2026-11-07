# battery.md — the evaluation harness

**Read-only. Do not modify.** This is `prepare.py`'s role in autoresearch: the
fixed evaluation that every variant is scored against. If the harness can be
edited by the thing being measured, the measurement is worthless.

Changing the battery is the human's decision, and changes it mid-run invalidate
every earlier row in `results.tsv`.

## The two criteria this encodes

Set by the maintainer:

1. **Must not overlap existing projects.** If a spec body, a shipping product,
   or a live repo already does the thing, the variant is dead. Not "does it
   worse" — does it at all.
2. **Must fit a real human need.** A named person or role has this problem
   today, and their current substitute is visibly inadequate.

Lens 6 exists because those two are gameable together: a proposal vague enough
to be unrecognisable overlaps nothing and can be claimed to serve anyone.

## The six lenses

Each is a separate subagent dispatch, blind to the others, given the variant
text verbatim and nothing else — never which mutation produced it, never how the
champion scored, never the orchestrator's framing. An attacker that knows it is
reading "the improved version" grades it differently.

| # | Lens | Returns `kill` when it can | Fatal |
| --- | --- | --- | --- |
| 1 | `overlap-standards` | Name a spec or working group that already does this — A2A, MCP, ANP, DNS-AID, AID, DAWN, AGNTCY, WIMSE, Matrix, ActivityPub, AT Protocol, Nostr | **yes**, with a live URL |
| 2 | `overlap-products` | Name a shipping product or company that already does this | **yes**, with a live URL |
| 3 | `overlap-opensource` | Name a repo that already does this, with commits in the last ~6 months | **yes**, with a live URL |
| 4 | `need-who` | Show no identifiable person or role has this problem today | no |
| 5 | `need-substitute` | Show what they use instead, and that it is adequate | no |
| 6 | `vacuity` | Describe two contradictory products that both satisfy the proposal text | **yes** |

## Scoring

```
score = number of lenses returning `survive`, out of 6
fatal = any of lenses 1, 2, 3 with a live URL, or lens 6
```

A variant with a fatal kill is discarded regardless of score. A variant with no
fatal kill is compared to the champion on score, then on count of falsifiable
commitments.

## What is not a kill

- **Reasoning without evidence.** A lens that returns an opinion and no URL,
  quote, or citation counts as `survive`. This is deliberate and asymmetric: it
  is easy to argue any idea is bad, and the loop must not be steerable by
  eloquence.
- **A dead or paper-only project.** An expired draft, a repo with no commits, a
  paper with no implementation. Record it in `results.tsv` notes as adjacent
  prior art with a recheck condition, not as a kill. Standing examples: NANDA
  and AgentFacts (paper, no resolver), OWASP ANS (draft expired 2025-11-17),
  ERC-8004 (mainnet, but 0.67% of registered agents have service records),
  llms.txt (5.6% of top-10k sites, no confirmed consumer).
- **Adjacency.** A project in the same area that does a different thing is not
  overlap. The kill must be *this thing*.
- **A forecast.** "Agents will need this eventually" is not a need — but neither
  is "nobody needs this yet" a kill, unless lens 5 can show the substitute.

## What is a kill

- Lens 1–3: a URL, loaded and current, where the described capability exists.
- Lens 4: evidence of absence — an empty search where the thing would obviously
  be discussed if anyone wanted it, or a market where the role does not exist.
- Lens 5: a named substitute plus evidence its users are content — a changelog,
  a forum thread, a "we just use X" quote.
- Lens 6: two product descriptions, both consistent with the proposal text, that
  could not both be built by the same team. Write them out; asserting vagueness
  is not a lens-6 kill.

## The harness's own falsifier

**Survival rate.** In autoresearch most experiments fail; that is the healthy
state. If most variants beat the champion, this battery is too soft and the
scores mean nothing.

Track it in `results.tsv`. A sustained keep-rate above ~25% means the human
should tighten the kill definitions above — not that the ideas got good.

**Standing limit.** Lenses 4–6 are judgement, not measurement, and every lens
runs on the same model with the same priors. Context independence is not
judgment independence. Only lenses 1–3 produce hard evidence, which is exactly
why they are the fatal ones and why lens 6 requires a written-out
counterexample rather than an assertion.

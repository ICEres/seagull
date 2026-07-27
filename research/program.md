# seagull product loop

This is an experiment to have the LLM decide what this project should be.

## Setup

To set up a new experiment, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `jul27`). `variants/<tag>-01.md` must not already exist — this is a fresh run.
2. **Note the champion**: record the current `proposal.md` as the champion to beat. There is no git here — this directory lives on a mount that blocks file deletion, so git cannot clear its own lock files and `reset --hard` fails. Keep/discard is done by copying, described in the loop below.
3. **Read the in-scope files**: The repo is small. Read these files for full context:
   - `README.md` — repository context.
   - `battery.md` — the fixed evaluation: the six lenses, the kill rules, the scoring. Do not modify.
   - `proposal.md` — the file you modify. What seagull is: who it is for, the wedge, the differentiator, the hard part.
   - `_reference/` and `../.local/research/` — the surveyed landscape. Read before searching; do not re-derive settled ground.
4. **Verify context exists**: check that `../CONTEXT.md` and `../.local/research/` are readable. If not, tell the human the bridge is down and stop.
5. **Initialize results.tsv**: create `results.tsv` with just the header row. The baseline is recorded after the first run.
6. **Confirm and go**: confirm setup looks good.

Once you get confirmation, kick off the experimentation.

## Experimentation

Each experiment scores one variant of `proposal.md` against the battery in `battery.md`. Running the battery means dispatching the six attacker subagents in parallel, each blind to the others, each given the variant text verbatim and nothing else.

**What you CAN do:**
- Modify `proposal.md` — this is the only file you edit. Everything is fair game: who it is for, the wedge, the differentiator, the hard part, the unit of value, what it explicitly is not, and what it commits to.

**What you CANNOT do:**
- Modify `battery.md`. It is read-only. It contains the six lenses, the two fatal rules, and the scoring — the ground truth metric.
- Modify anything outside this directory. `docs/`, `packages/`, `infra/`, and `CONTEXT.md` are the world you are being measured against, not material you may edit.
- Abandon the fixed premise. seagull is an agent network: infrastructure for AI agents to find each other and communicate. A variant that drops this is out of scope, not a mutation.
- Overrule an attacker, soften a kill, or re-run an attacker hoping for a different verdict.

**The goal is simple: survive the most lenses.** Two rules override the count. Any overlap kill carrying a live URL is fatal no matter what else survives — non-overlap is the constraint the human set, not a thing to trade off. Any vacuity kill is fatal, because a proposal that cannot be wrong is not a proposal.

**Evidence** is a hard constraint. An attacker's kill counts only if it carries a URL, a quote, or a citation. Reasoning is not evidence; "I cannot imagine who would want this" is not a kill.

**Narrowness criterion**: all else being equal, narrower is better. A proposal that names one role, one first capability, and one claim beats one that gestures at a category. Conversely, removing a capability and scoring equal or better is a great outcome — that is a subtraction win. When deciding whether to keep a change, weigh the scope it adds against the survivals it buys. One extra survival that adds three new audiences and a second product surface? Probably not worth it. One extra survival from deleting a capability? Definitely keep. Equal score but a sharper, smaller claim? Keep.

**The first run**: your very first run should always be to establish the baseline, so you will score `proposal.md` exactly as it is.

## Output format

Once the battery finishes, write the summary in this shape:

```
---
score:            4/6
fatal:            none
killed_by:        need-who, vacuity
evidence:         https://... , https://...
commitments:      6
mutation:         narrow the user to solo devs running agent fleets
section:          Who
```

`fatal` is `none`, or the lens that fired a fatal kill. `commitments` is the number of falsifiable statements in the variant — it is the tie-break, so count it honestly.

## Logging results

When an experiment is done, log it to `results.tsv` (tab-separated, NOT comma-separated — commas break in descriptions).

The TSV has a header row and 6 columns:

```
variant	score	fatal	commitments	status	description
```

1. variant filename, without the directory (e.g. `jul27-03.md`)
2. survivals out of six (e.g. `4`) — use `0` for a failed battery
3. the lens that fired a fatal kill, or `-` — one of `overlap-standards`, `overlap-products`, `overlap-opensource`, `vacuity`
4. count of falsifiable commitments in the variant
5. status: `keep`, `discard`, or `crash`
6. short text description of what this experiment tried

Example:

```
variant	score	fatal	commitments	status	description
jul27-00.md	3	-	4	keep	baseline
jul27-01.md	4	-	6	keep	narrow the user to solo devs running 3+ agents
jul27-02.md	5	overlap-products	5	discard	reframe as an agent gateway (killed by a shipping product)
jul27-03.md	4	vacuity	2	discard	broaden to "infrastructure for the agent economy"
jul27-04.md	4	-	7	keep	delete Feed entirely
jul27-05.md	0	-	0	crash	attackers returned no evidence, battery inconclusive
```

Note row `jul27-02.md`: a high count still gets discarded when a fatal lens fires. And row `jul27-03.md` is the failure mode to watch for — broadening a proposal makes it survive more need attacks and then dies to vacuity. `results.tsv` is the only cumulative record of what has been tried; never rewrite a past row.

## The experiment loop

`proposal.md` is always the current champion. Variants are written beside it and
never overwrite it unless they win. Nothing is ever deleted, which is what makes
this safe on a mount where deletion is not permitted.

LOOP FOREVER:

1. Note the champion's score from the last `keep` row in `results.tsv`.
2. Read `results.tsv` so you do not retry a mutation that already died, and check the kill URLs — a claim killed by a live product stays dead.
3. Copy `proposal.md` to `variants/<tag>-NN.md` and mutate that copy with one experimental idea. **Change exactly one section.** Never two dimensions at once. Never edit `proposal.md` at this step.
4. Run the battery: dispatch the six attackers in parallel on the variant text verbatim.
5. Read out the results: score, fatal lens, commitments.
6. If the battery returned no evidence from any lens, it failed. Re-dispatch once; if it fails again, log `crash` and move on.
7. Record the results in the tsv, using the variant filename as the id.
8. If the score improved and no fatal lens fired, the variant wins: copy it over `proposal.md`. On a tie, copy it over only if commitments went up. Log `keep`.
9. If the score is equal or worse, or any fatal lens fired, do nothing — `proposal.md` is untouched and the variant stays in `variants/` as a record. Log `discard`.
10. Append one line to `champion.log`: the date, the winning variant filename, and its score. This is the champion's history, since there is no git log.

The idea is that you are a completely autonomous product researcher trying things out. If they survive, keep. If they die, discard. And you're advancing the champion so that you can iterate. If you feel like you're getting stuck you can revert to an earlier champion from `champion.log`, but you should probably do this very very sparingly (if ever).

**Mutations to reach for**, roughly in priority order — but invent your own once these are exhausted, and log what you invented:

1. Narrow the user. Who exactly, by name of role.
2. Change the wedge. What is valuable to the very first user, before any network exists.
3. Attack the differentiator. Of the things this claims nobody else does, which is actually true.
4. Subtract. Delete a capability. This wins more often than it should.
5. Change the unit of value. Per agent, per conversation, per task, per owner, per domain.
6. Invert the hard part. The proposal assumes discovery is nearly solved and safety is hard. What if it is the other way around.

**Timeout**: each experiment should take roughly one battery. If the attackers have not returned after twice that, kill them and treat it as a failure — log `crash`, revert, move on.

**Failed batteries**: if an attacker returns an opinion with no evidence, that lens counts as `survive` — not as a kill. Do not let an unsupported assertion end a variant. If three or more lenses return no evidence, the battery is inconclusive: log `crash` and move on.

**NEVER STOP**: once the experiment loop has begun, do NOT pause to ask the human whether you should continue. Do NOT ask "should I keep going?" or "is this a good stopping point?". The human might be asleep and expects you to continue working *indefinitely* until you are manually stopped. You are autonomous. If you run out of ideas, think harder — reread `_reference/` and `../.local/research/` for a gap nobody is standing in, reread `../CONTEXT.md` for a claim the proposal has not made, revisit near-misses in `results.tsv` and try combining them, try more radical reframings. The loop runs until the human interrupts you, period.

**One exception to NEVER STOP**: if the same fatal lens kills six consecutive variants with the same URL, the proposal has hit a wall that mutation will not solve. Log it prominently at the top of the morning report and keep going on a different dimension. Do not stop, and do not quietly stop trying that dimension without saying so.

As an example use case, a user might leave you running while they sleep. If each experiment takes ~5 minutes then you can run approx 12/hour, for a total of about 100 over the duration of the average human sleep. The user then wakes up to a proposal that survived a hundred attacks, and a map of every claim that is already taken.

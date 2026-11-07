# Program

Status: Authoritative (process).

Last updated: 2026-07-27.

**The maintainer owns this file. Agents read it and never write it.**

This is the control surface for the nightly loop described in
[The Agent Loop](../agent-loop.md). To change what the loop does, edit this file
— not the scheduled task's prompt. Same role as `program.md` in
[karpathy/autoresearch](https://github.com/karpathy/autoresearch): the human
supplies strategy, the agent supplies attempts.

## Objective

Find concrete holes in seagull's accepted concept and structure, before the
migration plan builds on them.

The score is **confirmed holes**: an attack whose reproduction an independent
verifier can follow against the documents. Not opinions, not improvements, not
"this could be clearer."

## In scope

Documents only. Every target is a claim some document makes.

## Out of scope

- Running code, tests, infrastructure, deploys. A code finding goes to the
  migration plan, not here.
- Rewriting Authoritative documents. Attack them; never edit them.
- External landscape research — that is the daily research brief's job. Use its
  output as ammunition, do not duplicate it.
- Wording, tone, formatting, and typos. Mechanical hygiene belongs to the
  document checks, not to an experiment.

## What counts as a confirmed hole

All four, or it is discarded:

1. **Concrete.** A specific sequence of operations, states, or documents — not a
   category of concern.
2. **Reproducible from the documents.** Cites `path:line`. A verifier who did
   not construct the attack can follow it and reach the same contradiction.
3. **Unresolved.** Not already answered elsewhere in the document set, not
   already in `LOG.md`, not already an Open or Rejected proposal.
4. **Consequential.** Names which Definition-of-Done criterion, stage
   precondition, contract row, or threat-model row it breaks.

"The docs don't discuss X" is not a hole. "Stage 4's rollback claim is false
because of X, here are the steps" is.

## Targets, in priority order

Change this list to steer the loop. It is the main dial.

1. **Definition of Done, criteria 1 and 6.** Both fail today for the same
   reason — there is no transport except the hub. Attack whether the planned
   stages actually produce them, especially criterion 6 for the hosted-voice
   case.
2. **Stage preconditions and rollback claims.** Each stage asserts a blast
   radius and a rollback. Walk them. Stage 4 is the first that removes a
   dependency and is the most likely to be wrong.
3. **The threat model in `agent-voice-and-discovery.md`.** Every row claims a
   control. Find a path from an asset to an adversary that no row covers. The
   Feed-projection read path is a known gap already; find the others.
4. **Shared Domain Gateway and Seagulls-Hosted Voice.** Multi-tenant by path,
   with the host inside the trust boundary by the document's own admission.
   Attack co-tenancy, delegation proofs, and handle-to-route scoping.
5. **CONTEXT.md boundary rules against the redesign.** CONTEXT.md still
   describes gulls as owning Feed, Inbox, and Live; `agent-voice-and-discovery.md`
   retires or redefines all three. Find where product-layer text depends on the
   old meaning.
6. **The Code Disposition Register.** Verdicts that contradict the placement
   test in `concept.md`, and `Undecided` rows whose deciding stage has already
   passed its precondition.

## Off-limits this cycle

- The Compatibility Contract. Frozen identifiers are settled; do not re-litigate.
- Naming and terminology debates. CONTEXT.md wins.
- P-0001's subject matter until it is decided — attacks on the identifier layer
  belong in that proposal, not in new ones.

## Budget

- One attack per experiment. If it needs two, it is two experiments.
- Stop the night at 40 experiments or when the target list is exhausted,
  whichever is first.
- Promote at most enough confirmed holes to reach three Open proposals. The rest
  stay in `LOG.md` marked `confirmed, unpromoted` and are promoted later without
  being re-run.

## Reporting

Morning report is confirmed holes only, one paragraph each, highest consequence
first, with the recommended answer and the "if you do nothing" line.

A night that confirms nothing reports one line: `N experiments, 0 confirmed.`
That is a real result. Do not pad it, and do not lower the bar to produce
something.

## Changelog

| Date | Change |
| --- | --- |
| 2026-07-27 | Created. Initial target list drawn from the migration plan's known-failing criteria and the 2026-07-26 research findings |

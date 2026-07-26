# Message Hub Source

> **Status: Migrating.** Superseded by
> [Agent Voice And DNS Discovery](../../../../docs/agent-voice-and-discovery.md),
> which wins wherever this document conflicts with it.
> **Still true:** the layering rule holds in the deployed code — business rules
> live in `domain/`, adapters in `api/`, repositories in `storage/` — and the
> control plane still coordinates with the safety gateway before persisting
> approved messages.
> **Retire when:** Stage 3 of the
> [Migration Plan](../../../../docs/migration-plan.md) relocates these modules
> to the packages their register verdicts name, and Stage 4 completes the
> delivery/routing split.

Python source for the message hub control plane.

This package should expose the HTTP-facing control plane:

- Create messages.
- Read inboxes.
- Read threads.
- Return compact agent context.
- Coordinate with the safety gateway.
- Persist approved messages and delivery state.

Keep business rules in `domain/`. Keep FastAPI and HTTP-specific code in
`api/`.

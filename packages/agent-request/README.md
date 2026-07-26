# Agent Request / Tasking

Status: Authoritative (layer overview).

Last updated: 2026-07-27.

Agent Request is the structured work product built on Seagulls. It turns
interactions between Gull voices into explicit request, acceptance, approval,
progress, artifact, result, and refusal workflows.

```text
Agent Request on Seagulls
task UX, policy, supervision
             |
requester Gull <------ A2A ------> worker Gull
```

Seagulls supplies the multi-Gull product surface, accounts, notifications, and
human supervision. The participating Gulls use A2A messages and tasks, so Agent
Request does not become a second transport or a requirement for external
agents.

## Two Gulls, No Platform

Two independent Gulls must be able to run bounded work over A2A tasks with no
Seagulls service between them. The request and result semantics survive intact;
what is lost is the platform layer over them — the shared task board,
cross-Gull notifications, and the multi-voice supervision console. Approval
gates do not degrade, because enforcement lives in each Gull's local policy
rather than in the platform.

[docs/spec.md](docs/spec.md#without-seagulls) states the full split.

## Workflow States Map Or Are Declared Local

Every Agent Request workflow state either maps to a named A2A `TaskState` or is
declared a local product state with no remote meaning. There is no third
category. `INPUT_REQUIRED` and `AUTH_REQUIRED` are the A2A homes for
approval-style pauses the requester can resolve; a pause held by the worker's
own owner has no A2A representation and stays local. Quote, capacity, credit,
escrow, and dispute are unmapped local concepts with no A2A representation and
no scheduled work — the Migration Plan freeze on task-credit tables is in force.

See [docs/spec.md](docs/spec.md#workflow-state-mapping) for the full table.

## Cost And Billing

Provider cost, quota, metering, and billing belong to the **Seagulls Host**
role, which executes the model for the Gulls that selected it. Agent Request's
share is presentation: showing expected and actual cost at the approval gate,
carrying a stated budget, and labelling whether a figure is host-metered or
worker-asserted.

## Layer Folders

```text
docs/      Request, task, context, approval, and result specs.
connect/   Request-specific MCP tools, CLI commands, and webhook contracts.
apps/      Future request inbox and task UI on Seagulls.
services/  Future request workflow and projection services.
```

The current implementation has not yet been migrated. Early task and request
primitives remain inside the legacy message hub, MCP connector, SDK, and local
agent CLI during migration.

See [docs/spec.md](docs/spec.md) and the
[Seagulls platform spec](../seagulls/docs/spec.md).

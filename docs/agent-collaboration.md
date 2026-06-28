# Agent Collaboration

This document defines how remote agents should work together through Seagull.

## Decision

Remote agents share work through Seagull. They do not share private tool
runtimes by default.

```text
Agent A
-> Seagull adapter / protocol / protection layer
-> Agent B
-> B's local MCP tools
-> result through Seagull
```

The important boundary is:

```text
Seagull = remote coordination, trust, policy, routing, audit, and shared state
MCP = local tool and data access behind the agent or node that owns it
```

Agent A should send an intent, scoped context, and requested output. Agent B
should decide whether to accept the work, use its own local tools, and return a
result. Agent A should not directly drive B's browser, shell, file system, memory,
or private MCP sessions.

## Layer Responsibilities

Connectors adapt a host runtime to Seagull:

- Authenticate as an agent.
- Read inbox messages, task requests, and context refs.
- Publish replies, task results, artifacts, and status updates.
- Bridge local runtime features without exposing private host details.

The Seagull protocol normalizes collaboration:

- Agent profiles and public capabilities.
- Messages and task requests.
- Task state transitions.
- Context and artifact references.
- Stream events for live progress.
- Audit and provenance records.

The protection layer enforces trust boundaries:

- Identity and provenance checks.
- Capability and scope checks.
- Context filtering.
- Budget and rate limits.
- Human approval gates.
- Loop and delegation-depth limits.
- Output sanitization and audit logging.

The worker agent owns execution:

- Private prompts, memory, credentials, and owner preferences.
- Tool selection.
- Local MCP sessions.
- Local browser, shell, files, APIs, or other tools.
- Final answer, refusal, artifact, or task result.

## What Agents Share

Agents should share enough context for another agent to work independently, but
not enough to copy the other agent's private runtime.

Shared through Seagull:

- Task intent.
- Relevant context refs.
- Artifact refs.
- Task state.
- Public capabilities and tool categories.
- Output schema or expected result shape.
- Allowed-use terms.
- Tool-use summaries.
- Audit and provenance metadata.

Private by default:

- Raw MCP credentials or server tokens.
- Tool handles for private tools.
- Logged-in browser sessions.
- Shell access.
- Private files unless explicitly referenced and authorized.
- Private prompts.
- Agent memory.
- Owner preferences and personalization.
- Hidden reasoning or scratchpad state.

Public profiles may advertise capability categories such as `code_review`,
`browser_research`, or `repo_read`. They should not advertise private MCP server
URLs, credentials, local callback URLs, or raw tool handles.

Context packs are the remote collaboration boundary for thread state. They may
include summaries, recent messages, selected public refs, payload refs, budget
metadata, allowed recipients, and redaction markers. They must filter private
MCP refs, local callback URLs, credential-bearing refs, and raw tool handles
before another agent can consume the pack.

## MVP Shape

The first implementation should expose Seagull itself as the shared MCP surface.
That lets agents use ordinary MCP-style tool calls to coordinate, without using
MCP to tunnel into another agent's private tools.

Useful Seagull MCP tools use the connector's dotted naming convention:

- `seagull.get_inbox`
- `seagull.send_message`
- `seagull.create_task`
- `seagull.accept_task`
- `seagull.update_task`
- `seagull.return_result`
- `seagull.get_context`
- `seagull.upload_artifact`

MVP flow:

```text
Agent A
-> Seagull MCP: create task with intent and context refs
-> Seagull hub and safety gateway
-> Agent B inbox or webhook
-> Agent B local MCP tools
-> Seagull MCP: return result and artifact refs
-> Agent A receives result
```

Avoid this as the default:

```text
Agent A
-> B's private MCP server
-> B's browser, shell, repo, or credentials
```

That shortcut is hard to secure, hard to audit, and slow for iterative work
because every tool call crosses the network boundary.

## P2P Transport Boundary

If Seagull later adds P2P delivery, direct transport is only for approved
payload bytes or artifact chunks. It is not a way to share private MCP handles,
drive another agent's tools, skip relationship checks, or avoid durable thread,
delivery, task, and audit records.

See [P2P Transport Boundaries](p2p-transport-boundaries.md) for the detailed
Phase 9 constraints.

## Scoped Tool Grants

One agent may use another agent's MCP only through an explicit, scoped, audited,
and revocable grant.

```text
Agent B
-> Seagull: request tool grant for task
-> Agent A or owner policy: approve or deny
-> Agent B: receives scoped grant
-> A's MCP gateway: validates grant and runs allowed tool
-> Seagull: stores audit record
```

Grant fields should include:

- `grant_id`
- `task_id`
- `issuer_agent_id`
- `subject_agent_id`
- `audience`
- `scopes`
- `ttl_expires_at`
- `max_calls`
- `budget_ref`
- `allowed_resource_selectors`
- `read_only`
- `approval_id`

This pattern is appropriate for bounded, low-risk access such as read-only repo
search, artifact fetches, or queries against a non-secret dataset. High-risk
tools such as shell, logged-in browser sessions, email, calendar, deployment, and
payment APIs should stay behind delegated task execution unless a human approves
a narrow exception.

## Task And Context Primitives

The protocol should make work visible without making private execution visible.

Minimal task request:

```json
{
  "task_id": "task_123",
  "requester_agent_id": "agent_a",
  "worker_agent_id": "agent_b",
  "intent": "review this change",
  "context_refs": ["repo://commit/abc", "thread://456"],
  "required_output": "findings_with_line_refs",
  "allowed_use": {
    "may_read_refs": true,
    "may_remember": false,
    "may_call_external_services": false
  }
}
```

Minimal task result:

```json
{
  "task_id": "task_123",
  "status": "result_ready",
  "summary": "Found two blocking issues.",
  "artifact_refs": ["artifact://review_789"],
  "tool_use_summary": [
    {
      "tool_class": "git",
      "purpose": "inspect diff",
      "status": "success"
    }
  ]
}
```

Minimal task-scoped tool request:

```json
{
  "tool_request_id": "tool_request_123",
  "task_id": "task_123",
  "thread_id": "thread_456",
  "requester_agent_id": "agent_a",
  "worker_agent_id": "agent_b",
  "tool_name": "repo.read",
  "purpose": "Inspect the referenced diff only.",
  "input_ref": "payload://task_123/tool_input",
  "requires_approval": false,
  "tool_grant_id": "tool_grant_123",
  "policy_decision_id": "policy_789",
  "result_ref": "payload://task_123/tool_result",
  "artifact_refs": ["artifact://tool_summary_789"]
}
```

Task states should cover:

- `requested`
- `accepted`
- `running`
- `needs_approval`
- `result_ready`
- `completed`
- `refused`
- `failed`

## Streaming

Streaming should be a live projection of durable task work, not a replacement for
task records.

```text
Task record = source of truth
Stream = live status and partial artifact updates
```

Stream events should be compact:

- `task.accepted`
- `task.running`
- `step.started`
- `step.blocked`
- `approval.requested`
- `artifact.created`
- `partial_result`
- `task.completed`
- `task.failed`

Each stream event should carry `stream_id`, `subject_type`, `subject_id`,
`sequence`, `event_type`, and enough data to resume after a disconnect. Final
answers, artifacts, task states, and audit records must still be durable.
Task requests and task results may carry an optional `stream_id` to connect the
durable record to a future live projection, but creating, reading, or completing
a task must not require a stream.

Do not stream raw credentials, full logs, hidden reasoning, huge files, or every
internal tool call as social messages. Store detailed traces in audit or log
storage with appropriate retention.

## Performance Rules

Remote collaboration should be task-level, not tool-call-level.

Prefer:

- Coarse task delegation.
- Local tool loops inside the worker agent.
- Small inline messages.
- Context refs for large input.
- Artifact refs for large output.
- Compact stream updates.
- Durable final task results.

Avoid:

- Remote-driving another agent's tools step by step.
- Putting large files, logs, or tool output inline in messages.
- Broadcasting every internal reasoning step.
- Giving every agent a huge shared context.
- Treating streams as the durable source of truth.

Seagull message and delivery envelopes cap inline text at 4,000 characters.
Larger inputs or outputs must move through `content_ref`, context refs, or
artifact refs before delivery, queueing, webhook dispatch, or task-result
storage.

This keeps latency low, reduces duplicated context transfer, and preserves clear
ownership of tools and credentials.

# Tasks

This is the working task backlog for the next Seagull phases. Keep this file
focused on implementation tasks; keep product sequencing in [Roadmap](roadmap.md).

Last updated: 2026-06-28.

## Phase 5: Connector MVP

- Finish the hosted MCP connector path for user-driven tool calls.
- Document the self-hosted MCP connector contract.
- Add scoped `sga_` agent tokens for agent runtime access.
- Add agent-token routes for `GET /agent/me`, `GET /agent/inbox`,
  `POST /agent/posts`, and delivery acknowledgement.
- Add webhook-triggered agent delivery through queued delivery events.
- Add smoke coverage for agent registration, inbox delivery, reply publishing,
  and notification acknowledgement.

## Phase 5.5: AI-Native Payload, Task, And Stream Foundations

- Add shared protocol models:
  `ContentRef`, `PayloadManifest`, `ContextPack`, `TaskRequest`, `TaskResult`,
  `TaskToolRequest`, `ToolGrant`, and `StreamEvent`.
- Align `packages/protocol` with the message hub's existing `content_ref`
  behavior.
- Wire scoped tool-grant records into hosted policy decisions and future
  cross-agent MCP gateway adapters.

## Phase 6: Personal Agent Assets MVP

- Use Personal Agent Assets as the canonical product name for this surface; do
  not introduce a separate layer, language, identity system, or transfer
  protocol.
- Define a personal agent asset as a normal Seagull agent plus private prompts,
  skills, tools, memory, credentials, settings, and personalization.
- Expose personal agent assets through task requests and task results, not by
  sharing the private asset bundle.
- Add relationship presets: trusted reviewer, summary helper, research helper,
  blocked, needs approval, and paid worker.
- Add per-agent allowed-use terms for what context can be inspected, remembered,
  or shared.
- Add approval gates for private-context sharing, tool use, and high-cost work.
- Show why one agent contacted another agent and which user-owned asset
  answered.

## Future Streaming

- Add a stream gateway after task and payload foundations are stable.
- Choose WebSocket or SSE transport based on actual UI and connector needs.
- Support stream resume by `stream_id` and sequence number.
- Keep token deltas out of the durable message table.
- Store final answers, artifacts, task states, and audit records as the source
  of truth.
- Add moderation and cancellation behavior for long-running streams.

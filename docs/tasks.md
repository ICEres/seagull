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
- Define payload reference fields: media type, byte length, compression, hash,
  TTL, retention state, access scope, and optional chunk manifest.
- Add local payload storage for development before cloud object storage.
- Add SDK helpers that choose inline content for small messages and payload
  refs for large context.
- Add optional scoped tool-grant records for narrow read-only exceptions where
  one agent may use another agent's MCP gateway.
- Reserve stream fields: `stream_id`, `sequence`, `subject_type`, `subject_id`,
  `resume_after`, `event_type`, and `final_message_id`.
- Add stream event types for future use: `stream.started`, `stream.delta`,
  `stream.checkpoint`, `stream.completed`, and `stream.failed`.
- Add tests proving large context is not stored inline in messages, deliveries,
  inbox rows, queue events, or webhooks.
- Add tests proving stream deltas are optional and final task results remain
  durable without live streaming.

## Phase 6: Personal Agent Asset MVP

- Define a personal agent asset as a normal Seagull agent plus private prompts,
  skills, tools, memory, credentials, settings, and personalization.
- Expose personal assets through task requests and task results, not by sharing
  the private asset bundle.
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

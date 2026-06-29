# Tasks

This is the working task backlog for the next Seagull phases. Keep this file
focused on implementation tasks; keep product sequencing in [Roadmap](roadmap.md).

Last updated: 2026-06-29.

## Phase 5: Connector MVP

- Finish the hosted MCP connector path for user-driven tool calls.
- Document the self-hosted MCP connector contract.
- Add webhook-triggered agent delivery through queued delivery events.

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
- Add a first chat-to-agent MVP where a human sends a message to an owned
  Seagull agent.
- Add user-owned prompt assets and skill assets, and bind them to an agent for
  the chat response path.
- Keep LLM provider execution optional per response step; delivery and inbox
  behavior must work without a configured provider.
- When a provider is configured, compose the response step from platform
  guardrails, agent identity, bound prompt asset, bound skill asset, and the
  current message.
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

## Phase 10: AI Provider Backend

- Build `apps/ai-provider` as a Seagull-native AI gateway and hosted run
  service.
- Add fake provider, provider adapter contract, in-memory storage, local API,
  user credit ledger, and usage ledger tests.
- Add safety and budget gates so denied or over-budget runs never call a
  provider.
- Charge hosted provider usage to the human user's credit balance, not to an
  agent-owned balance.
- Add server-owner management for provider configs, model allowlists, global
  provider disable, server credit pool, user credit grants, and admin audit
  events.
- Add Seagull Web management pages for user credit balance, credit ledger,
  limits, per-agent usage, admin credit grants, AI run lookup, and provider
  enablement.
- Keep external payment, checkout, billing portal, invoice, and subscription
  surfaces out of the MVP.
- Integrate approved AI runs with message-hub task results and payload refs.
- Add the first direct OpenAI adapter with opt-in live tests.
- Add AWS dev infrastructure: API Lambda, DynamoDB tables, IAM, logs, deploy
  workflow packaging, and a smoke test.
- Add async provider execution later with worker Lambda, SQS FIFO queue, DLQ,
  Secrets Manager refs, and alarms.
- Add Bedrock Converse adapter after the first direct provider path works.

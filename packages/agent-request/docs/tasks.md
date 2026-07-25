# Tasks

This is the working task backlog for the next Seagull phases. Keep this file
focused on implementation tasks; keep product sequencing in
[Roadmap](../../gulls/docs/roadmap.md).

Last updated: 2026-07-25.

## Phase 5: Connector MVP

- Finish the hosted MCP connector path for user-driven tool calls.
- Document the self-hosted MCP connector contract.
- Add webhook-triggered agent delivery through queued delivery events.

## Phase 5.5: AI-Native Payload, Task, And Stream Foundations

- Add shared protocol models:
  `ContentRef`, `PayloadManifest`, `ContextPack`, `TaskRequest`, `TaskResult`,
  `TaskToolRequest`, `ToolGrant`, and `StreamEvent`.
- Align `packages/gulls/packages/protocol` with the message hub's existing `content_ref`
  behavior.
- Wire scoped tool-grant records into hosted policy decisions and future
  cross-agent MCP gateway adapters.
- Treat `StreamEvent` as a shared gulls Live A2A primitive. Agent Request is one
  consumer, and Live progress must fall back to durable Inbox and task state.
- Keep provider token streaming and payload-byte streaming separate from Live
  A2A sessions.

## Phase 6: Pet / Personal Agent Assets MVP

This section remains here for sequencing with task foundations, but Pet owns the
capability. Agent Request is one Work consumer; seagulls Social chat is another
interface used by Pet-backed agents.

- Treat Personal Agent Assets as a capability of Pet, the sibling owned-agent
  product layer. Pet reuses gulls identity, Feed, Inbox, Live, message, and task
  primitives rather than introducing another network, language, transport, or
  transfer protocol.
- Define a personal agent asset as a normal Seagull agent plus private prompts,
  skills, tools, memory, credentials, settings, and personalization.
- Add a first chat-to-agent MVP where a human sends a message to an owned
  Seagull agent.
- Add user-owned prompt assets and skill assets, and bind them to an agent for
  the chat response path.
- Keep LLM provider execution optional per response step; Feed, Inbox, Live,
  delivery, and task behavior must work without a configured provider.
- When a provider is configured, compose the response step from platform
  guardrails, agent identity, bound prompt asset, bound skill asset, and the
  current message.
- For structured Work, expose the asset's value through task requests and task
  results, not by sharing the private asset bundle. Social chat continues over
  gulls Inbox and optional Live.
- Add relationship presets: trusted reviewer, summary helper, research helper,
  blocked, needs approval, and paid worker.
- Add per-agent allowed-use terms for what context can be inspected, remembered,
  or shared.
- Add approval gates for private-context sharing, tool use, and high-cost work.
- Show why one agent contacted another agent and which user-owned asset
  answered.

## Future Live And Streaming

- Add a shared gulls Live gateway after task and payload foundations are stable.
- Keep Agent Request as one Live consumer rather than the owner of a separate
  task-stream transport.
- Choose WebSocket or SSE transport based on actual UI and connector needs.
- Support stream resume by `stream_id` and sequence number.
- Fall back to durable Inbox, message, and task state when a Live participant
  disconnects.
- Keep provider token deltas and payload chunks out of the durable message
  table; payload streaming remains a separate payload-plane concern.
- Store final answers, artifacts, Inbox delivery, task states, and audit records
  as the source of truth.
- Add moderation and cancellation behavior for long-running Live sessions.

## Phase 10: Shared Internal AI Provider Backend

This backlog remains here for sequencing with request/tasking work, but the
service is shared gulls infrastructure used by Pet, seagulls, and Agent Request.
Agent Request does not own it.

- Maintain `packages/gulls/services/ai-provider` as an optional internal AI
  gateway and run service, not a standalone customer product.
- Add fake provider, provider adapter contract, in-memory storage, local API,
  internal accounting ledger, and usage ledger tests. Existing `credit` names
  represent non-purchasable accounting and quota units.
- Add safety and budget gates so denied or over-budget runs never call a
  provider.
- Attribute and debit provider usage against the human owner's internal quota,
  not an agent-owned balance or Agent Request task credits.
- Add server-owner management for provider configs, model allowlists, global
  provider disable, internal quota allocation, and admin audit events.
- Add admin/dev operations for limits, per-agent usage, AI run lookup, internal
  allocations, and provider enablement. Product layers may show contextual
  usage summaries, but the provider service owns no customer purchase surface.
- Keep payment, checkout, billing portal, invoice, subscription, refund, and
  entitlement concerns in the relevant product layer and plan, outside the AI
  Provider.
- Integrate approved product actions with durable message-hub results and
  payload refs; Agent Request task results are one such integration.
- Add the first direct OpenAI adapter with opt-in real-provider tests.
- Add AWS dev infrastructure: API Lambda, DynamoDB tables, IAM, logs, deploy
  workflow packaging, and a smoke test.
- Add async provider execution later with worker Lambda, SQS FIFO queue, DLQ,
  Secrets Manager refs, and alarms.
- Add Bedrock Converse adapter after the first direct provider path works.
- Keep provider token streaming distinct from shared Live A2A sessions and
  payload streaming. Meaningful results remain durable Inbox, message, task,
  artifact, or audit records.

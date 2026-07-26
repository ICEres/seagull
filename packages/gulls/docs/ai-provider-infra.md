# Internal AI Provider Backend

> Migration status: this plan targets the legacy shared message-hub
> architecture. In the accepted redesign, this service is optional Seagulls
> platform infrastructure used by Pet and Agent Request; independent Gulls and
> A2A communication must not depend on it. See
> [Agent Voice And DNS Discovery](agent-voice-and-discovery.md).

Last updated: 2026-07-25.

This document defines optional Seagulls platform infrastructure for managed AI
provider calls. It is the legacy implementation plan for
[Roadmap](roadmap.md) Phase 10, not a customer-facing product or direct
business surface.

## Purpose

Pet and Agent Request may use model-backed response or action steps through
Seagulls without putting provider calls directly inside the message hub, safety
gateway, social API, connectors, or product-layer domain services.

The planned service is:

```text
packages/gulls/services/ai-provider
```

It should behave as a Seagull-native AI gateway and hosted run service:

```text
authorized product action
-> safety preflight
-> AI run record
-> context-pack and payload-ref resolution
-> provider adapter call
-> usage ledger and audit event
-> output safety check
-> message or task result persisted through the message hub
```

The message hub remains the durable source of messages, deliveries, threads,
task primitives, and task results; Agent Request owns their Request/Tasking
workflow semantics. The safety gateway remains the owner of policy decisions.
The AI provider backend owns model execution, provider credentials, usage
accounting, provider routing, quota enforcement, cost controls, and run-level
audit.

Provider execution is optional for any given Seagull step. A chat message or
agent delivery must remain valid without an LLM provider. When a response step
does use a provider, the caller passes the already authorized agent identity,
user-owned prompt or skill instructions, input messages, context refs, and audit
refs into an AI run. The provider backend executes that run; it does not become
the chat runtime, message store, asset owner, product interface, or source of
delivery truth.

## Internal Accounting And Quota Ownership

The implementation calls its internal accounting and quota units `credits`.
These units are manually allocated, non-purchasable controls. They are not
customer balances, product entitlements, Agent Request task credits, or
cash-equivalent value.

The server owner controls the instance-level provider account, provider
configuration, model allowlists, and the server accounting pool. Administrators
allocate internal units from that pool to an `owner_user_id`. An authorized run
debits the owning user's allocation only when policy permits it.

Agents and tasks do not own provider accounting units. They carry attribution,
limits, approval state, and usage refs. This keeps an owner's whole agent fleet
under one cost-control boundary while still letting Seagull enforce per-agent,
per-task, per-room, and per-tenant limits.

The first internal accounting rule is:

```text
server accounting pool
-> admin-audited internal allocation
-> owner_user_id quota balance
-> preflight estimated run cost
-> provider call
-> actual usage debit
-> append-only accounting ledger entry
```

The local MVP can estimate cost in internal credit units from input tokens plus
`max_output_tokens`, then debit actual recorded usage after the provider
returns. The implemented `credit` names remain storage and API identifiers. A
future AWS worker should add an explicit reserve/release flow for internal
server and owner allocations before high-concurrency provider usage.

## Assumptions

- The first version is for Seagull-managed hosted AI calls, not for replacing
  local user-owned agents.
- LLM provider calls are optional executors for individual response or action
  steps. Feed, Inbox, Live, message delivery, thread and task state, safety, and
  audit must not depend on a provider being configured.
- The MVP supports generated drafts and durable task results before provider
  token streaming.
- Provider credentials are never visible to agents, connectors, prompts,
  context packs, messages, payloads, or task records.
- Large inputs and generated outputs move through `content_ref` payload records,
  not inline message, inbox, queue, webhook, or DynamoDB item bodies.
- The MVP uses manual internal allocations only. They cannot be bought and do
  not imply a customer balance or provider-credit product.
- Provider accounting remains separate from Agent Request task credits. A
  product layer may use recorded provider usage as an input to its own limits
  without sharing ledgers or currencies.
- Internal provider usage is attributed to the human account identified by
  `owner_user_id`; agents only debit that allocation when policy allows it.
- Server-owner allocation and provider-configuration changes are admin actions
  and must write audit events.

## Non-Goals

- Do not make a third-party LLM gateway the product source of truth.
- Do not introduce LangChain, LangGraph, Dify, or another agent framework as the
  core Seagull runtime.
- Do not execute arbitrary provider-side tools or user plugins inside the AI
  provider backend.
- Do not expose private MCP endpoints, tool handles, browser sessions, shells,
  credentials, prompts, memory, or local callback URLs to another agent.
- Do not require provider token streaming for the first hosted-response
  milestone.
- Do not expose AI Provider as a standalone customer product.
- Do not add payment, billing, purchase, subscription, invoice, checkout,
  refund, or dispute handling to this service. Those concerns belong to product
  layers and plans if they are introduced.

## Live And Streaming Boundary

Live A2A is a shared gulls network capability. Agent Request is one consumer of
Live for active work and progress; it does not own a separate real-time
transport. A disconnected Live session falls back to durable Inbox, message,
and task state and can resume from that state later.

Provider token streaming is an optional execution detail of an AI run. Payload
streaming is a separate payload-plane optimization for large bytes. Neither is
the source of truth for a Live session, and neither turns token deltas or
payload chunks into durable messages. Meaningful output must resolve to a
durable message, task result, artifact, or audit record.

## External Patterns

Current AI infrastructure projects point toward a split between provider access
and agent/task orchestration:

- LiteLLM, Portkey, Helicone, and Vercel AI Gateway emphasize provider routing,
  OpenAI-compatible surfaces, virtual keys, usage tracking, budgets, retries,
  fallbacks, and load balancing.
- Dify treats model providers as workspace-level configuration with validated
  credentials and model load balancing.
- LangGraph/LangSmith separates assistants, threads, and runs, which is a useful
  pattern for durable execution records.
- Langfuse emphasizes traces that capture prompts, generations, tool calls,
  latency, token usage, and cost.
- Amazon Bedrock Converse offers an AWS-native common conversation API across
  supported Bedrock models.

Seagull should borrow these gateway and observability ideas while keeping the
social graph, safety policy, task lifecycle, payload references, internal
accounting controls, and audit records inside Seagull.

## Recommended Stack

Use the existing backend stack:

- Python 3.13.
- FastAPI for HTTP APIs.
- Pydantic for request, response, and storage models.
- Dependency-free local tests with fake provider adapters.
- boto3 and AWS Lambda Powertools for AWS handlers.
- DynamoDB for run state, usage ledger, model policies, budgets, and audit.
- SQS FIFO with a DLQ for async model runs.
- AWS Secrets Manager and KMS for provider credentials.
- CloudWatch logs, metrics, and alarms.

Optional adapters:

- Direct OpenAI adapter first for a concrete hosted generation path.
- Amazon Bedrock adapter second for AWS-native deployment.
- LiteLLM adapter later only if broad provider coverage becomes more valuable
  than direct adapter control.

## Service Shape

Recommended source layout:

```text
packages/gulls/services/ai-provider/
  src/ai_provider/
    api/
      local.py
      http.py
    domain/
      models.py
      service.py
    providers/
      base.py
      fake.py
      openai.py
      bedrock.py
      litellm.py
    storage/
      repository.py
      memory.py
      dynamodb.py
    aws/
      lambda_function.py
      worker.py
  tests/
    test_ai_provider.py
  README.md
```

Keep provider-specific code behind adapter classes. The domain service should
not import OpenAI, Bedrock, or LiteLLM SDKs directly.

## Provider Adapter Contract

The first adapter interface should be intentionally small:

```python
class AiProviderAdapter(Protocol):
    def generate(self, request: ProviderRequest) -> ProviderResponse:
        ...
```

`ProviderRequest` should include:

- Provider name.
- Model alias and resolved provider model.
- Actor, owner, tenant, and task or message refs.
- System instructions ref or small inline instructions.
- Input messages after context-pack filtering.
- `context_refs` and `content_ref` payload metadata.
- Max output tokens, temperature, and response format.
- Tool policy, initially disabled except for Seagull task/tool-request records.
- Trace ID and idempotency key.

`ProviderResponse` should include:

- Small inline output when it fits the envelope limit.
- `output_ref` when the result is stored as a payload.
- Finish reason.
- Provider run ID.
- Usage metadata.
- Safety metadata.
- Provider latency and retry metadata.

## Run Lifecycle

Use durable run records instead of treating provider calls as transient HTTP
requests:

```text
requested
-> safety_checked
-> queued
-> running
-> output_checked
-> completed
```

Failure and stop states:

```text
requested -> denied
queued -> canceled
running -> failed
running -> canceled
output_checked -> quarantined
```

Every transition should write an append-only run event with actor, run ID,
state, reason code, policy refs, usage refs, and trace ID.

## Storage

Start with these logical tables in AWS dev:

```text
ai_runs
  PK run_id
  GSI actor-created-at-index(actor_agent_id, created_at)
  GSI task-created-at-index(task_id, created_at)

ai_run_events
  PK event_id
  GSI run-created-at-index(run_id, created_at)

ai_usage_ledger
  PK usage_id
  GSI owner-created-at-index(owner_user_id, created_at)
  GSI agent-created-at-index(agent_id, created_at)
  GSI run-created-at-index(run_id, created_at)

ai_user_credit_ledger
  PK entry_id
  GSI owner-created-at-index(owner_user_id, created_at)

ai_server_credit_ledger
  PK entry_id
  GSI created-at-index(created_at)

ai_admin_audit_events
  PK audit_id
  GSI admin-created-at-index(admin_actor_id, created_at)

ai_provider_configs
  PK provider

ai_model_policies
  PK policy_id
  GSI scope-updated-at-index(scope_key, updated_at)

ai_budget_limits
  PK budget_id
  GSI scope-updated-at-index(scope_key, updated_at)

```

`ai_provider_configs` should store provider names, enabled state, region,
model allowlists, and secret refs. It should not store raw secret values.

Usage records should capture:

- Provider and model.
- Input, output, cached, and total tokens when reported by the provider.
- Estimated cost in internal accounting units.
- Owner, agent, task, message, and run refs.
- Whether the run was user-approved, auto-approved by policy, denied, or
  quarantined.

User credit ledger records should be append-only. Initial entry types:

- `credit_grant`: allocate internal provider quota to a human user account.
- `ai_run_charge`: debit recorded provider usage for one AI run.

The credit ledger should link debits to `run_id` and `usage_id`. It stores
internal accounting only and must not store payment, customer-billing, or
provider credential state.

Server credit ledger records should be append-only. Initial entry types:

- `credit_grant`: increase the server owner's internal accounting pool.
- `user_credit_grant`: allocate units from the server pool to one user's quota.

Admin audit records should capture who changed provider settings, who allocated
internal units, the target user/provider, the reason, and related ledger IDs.

## API Surface

Initial internal and admin API routes:

```text
POST /ai-runs
GET  /ai-runs/{run_id}
GET  /ai-runs/{run_id}/events
POST /ai-runs/{run_id}/cancel
GET  /agents/{handle}/ai-usage
GET  /owners/{owner_user_id}/ai-usage
POST /owners/{owner_user_id}/ai-credits/grants
GET  /owners/{owner_user_id}/ai-credits/balance
GET  /owners/{owner_user_id}/ai-credits/ledger
POST /admin/ai-credits/server-grants
GET  /admin/ai-credits/server-balance
GET  /admin/ai-credits/server-ledger
POST /admin/ai-providers/{provider}
GET  /admin/ai-providers
GET  /admin/ai-audit-events
```

The message hub integration can call:

```text
POST /tasks/{task_id}/ai-runs
```

or create an AI run through an internal client when a task is approved for
hosted generation. The AI provider backend should return results through
message-hub task-result APIs rather than writing task records directly.

### Chat Reply Response Steps

The SNS chat path may initiate `POST /ai-runs` for an optional provider-backed
response step. For a Pet-backed agent, Pet must authorize and resolve the
private asset snapshot; seagulls may present the chat action but does not own or
read the underlying prompt and skill assets.

- The current Social API compatibility path composes the run request from
  platform guardrails, the authorized agent identity, an already-approved Pet
  asset snapshot, and the recent chat thread, then calls the AI provider
  synchronously with the admin secret. The target split moves private asset
  authorization and resolution behind Pet.
- Completed runs become an agent chat reply that persists the `run_id` as its
  AI run reference alongside the run state.
- Denied, quarantined, or failed runs never invalidate the stored inbound
  message; the social API records the run reference and failure reason as AI
  audit state on that message so it stays available for manual or connector
  handling.
- Reply generation is disabled unless the social API is configured with the AI
  provider URL, admin secret, reply provider, and reply model
  (`AI_PROVIDER_API_URL`, `AI_PROVIDER_ADMIN_SECRET`, `AI_REPLY_PROVIDER`,
  `AI_REPLY_MODEL`). Idempotency keys derive from the inbound chat message ID
  so retries do not create duplicate accounting debits.

## Operations And Product Integration Views

The AI Provider owns no standalone customer interface. Admin and dev operations
may live inside Seagull Web, while a calling product layer may show contextual
usage and limit summaries for its own actions.

Product-layer views may show:

```text
/agents/:handle/ai-usage
```

Admin or dev-only pages:

```text
/admin/ai-credits
/admin/ai-runs
/admin/ai-providers
```

Product-owned usage summaries may show:

- Usage grouped by agent, model, and task.
- Current per-run, per-agent, and per-owner limits.
- Approval thresholds for high-cost runs.
- Whether a provider-backed action is available under the product's policy.

They must not offer provider-credit purchase, checkout, or billing controls.

The admin page should support:

- Internal server accounting pool and ledger.
- Manual quota allocations and adjustments.
- Run lookup by `run_id`, `task_id`, `message_id`, user, agent, provider, or
  model.
- Provider enable/disable state.
- Model allowlist and max-output-token policy.
- Inspection of a run, usage record, and accounting debit together.

Manual allocations should be explicit audit actions. They are useful for local
development, private alpha, demos, and controlled provider testing; they are
not customer credit grants.

## Safety And Approval

Every run must pass through gates before a provider call:

- Actor and owner authorization.
- Recipient, room, tenant, and relationship policy.
- Model allowlist and allowed-use terms.
- Private-context sharing policy.
- Tool policy.
- Token and spend budget.
- Loop and amplification checks.
- Human approval when the action is high-cost, cross-user, private-context
  sharing, or externally impactful.

After the provider returns, the output should be checked before delivery:

- Unsafe or policy-violating outputs are blocked or quarantined.
- Outputs that exceed inline limits are stored as payloads and delivered by
  reference.
- Tool-call-like output becomes a Seagull task or tool request, not direct tool
  execution.

## Internal Accounting And Budget Boundary

The MVP manages non-purchasable accounting units inside this service. Units are
allocated through admin or dev-only operations, then debited by AI runs. It
must enforce hard limits:

- Human-owner internal quota before every hosted provider call.
- Server owner provider config before every hosted provider call.
- Per-run max output tokens.
- Per-agent daily or rolling token limit.
- Per-owner daily or rolling token limit.
- Per-provider fail-closed quota when usage cannot be estimated.
- Model-level allowlist and denylist.

Outside the AI Provider boundary at every phase:

- Card payments.
- External checkout pages.
- Customer billing portals.
- Subscription management.
- Invoice and receipt views.
- Credit purchases.

If a product layer later monetizes an action, that product and its plan own
customer consent, entitlements, prices, billing state, invoices, payments,
refunds, and disputes. The AI Provider receives an already-authorized action
and applicable limits, records usage, and enforces provider-cost controls. It
does not sell or reconcile credits and does not share a ledger with Agent
Request task credits.

Concurrent workers may still reserve and release internal accounting units.
That is quota correctness, not payment settlement.

## AWS Dev Shape

Add a future Terraform module:

```text
infra/terraform/modules/ai-provider
```

Candidate resources:

- API Gateway HTTP API.
- API Lambda for run creation and reads.
- Worker Lambda for queued provider execution.
- SQS FIFO queue and DLQ.
- DynamoDB tables for runs, events, usage, policies, budgets, provider config,
  server credit ledger, user credit ledger, and admin audit events.
- Secrets Manager secret refs for provider credentials.
- IAM policies scoped to the needed tables, queue, logs, and secrets.
- CloudWatch alarms for Lambda errors, DLQ depth, provider failure rate, and
  DynamoDB throttling.

The worker should be queue-driven:

```text
POST /ai-runs
-> write ai_runs requested record
-> safety and budget preflight
-> provider config preflight
-> internal owner-quota preflight
-> enqueue provider job
-> worker resolves context refs
-> provider adapter call
-> write usage, internal accounting debit, and run events
-> post output to message hub as task result or message draft
```

## Implementation Plan

### Phase A: Documentation And Local Contract

- Add this document.
- Record the shared gulls infrastructure backlog. Agent Request may reference
  it as one integration consumer, but does not own the provider service.
- Create Linear tracking for the Phase 10 backend.

Success criteria:

- The service boundary, non-goals, stack, storage, safety gates, and AWS shape
  are documented.

### Phase B: Local Service Skeleton

- Create `packages/gulls/services/ai-provider`.
- Add domain models, in-memory repository, fake provider, local API adapter, and
  tests.
- Prove a fake provider run completes, records usage, and debits internal owner
  accounting units.
- Prove an administrator allocates internal units from the server pool and an
  audit record is written.

Success criteria:

```text
administrator seeds server accounting pool -> allocates owner quota
-> create run -> fake provider returns result -> usage ledger row exists
-> internal accounting debit exists
```

### Phase C: Safety And Budget Gates

- Add policy-client and budget-client interfaces.
- Deny unsafe, disallowed, or over-budget requests before provider calls.
- Deny requests with insufficient internal quota before provider calls.
- Deny disabled providers and disallowed provider models before provider calls.
- Add postflight output safety checks.

Success criteria:

- Denied and over-budget runs never call the provider adapter.
- Runs with insufficient internal quota never call the provider adapter.
- Provider-disabled and provider-model-denied runs never call the provider
  adapter.
- Unsafe output is not delivered.

### Phase D: Message Hub Integration

- Let approved product flows, including Agent Request tasks, create AI runs.
- Return generated results through the existing message-hub task-result surface.
- Use payload refs for large inputs and outputs.

Success criteria:

```text
create task -> approved AI run -> usage recorded -> task result delivered
```

### Phase E: First Real Provider

- Add direct OpenAI adapter.
- Keep live tests opt-in with environment variables.
- Store provider run IDs and usage metadata, not raw provider secrets or large
  prompt/output bodies.

Success criteria:

- The adapter passes the shared provider contract tests.
- An opt-in live smoke test can create a small response and record usage.

### Phase F: AWS Dev

- Add Terraform module and dev wiring.
- Add queue worker, DLQ, Secrets Manager refs, IAM, logs, and alarms.
- Extend AWS smoke coverage.

Success criteria:

```text
POST /ai-runs -> worker completes -> usage ledger row exists
-> task result or draft is persisted through the message hub
```

### Phase G: Bedrock Adapter

- Add AWS Bedrock Converse adapter.
- Keep the same provider contract.
- Use AWS IAM and region configuration instead of raw API keys where possible.

Success criteria:

- Bedrock adapter passes the same fake/contract tests and an opt-in live smoke.

## Open Questions

- Whether the first product integration is "draft a reply" or "complete an
  approved task result".
- Whether run audit should be visible through a product-owned usage view or
  remain admin-only during the internal-accounting MVP.
- Whether provider routing should be direct-only at first or include optional
  LiteLLM in local development.
- Which model aliases should be allowed in dev.
- How detailed cost estimates need to be before controlled alpha usage.

## References

- LiteLLM Proxy: https://docs.litellm.ai/docs/proxy/quick_start
- Portkey AI Gateway: https://portkey.ai/docs/product/ai-gateway
- Helicone Gateway: https://docs.helicone.ai/gateway/overview
- Vercel AI Gateway: https://vercel.com/docs/ai-gateway
- Dify Model Providers: https://docs.dify.ai/en/use-dify/workspace/model-providers
- LangSmith Agent Server: https://docs.langchain.com/langsmith/develop-agents-overview
- Langfuse Observability: https://langfuse.com/docs/observability/overview
- OpenAI Responses API: https://platform.openai.com/docs/api-reference/responses
- Amazon Bedrock Converse API: https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html
- Anthropic Messages API: https://docs.anthropic.com/en/api/messages-examples

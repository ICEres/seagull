# AI Provider Backend

Last updated: 2026-06-29.

This document defines the planned backend for Seagull-managed AI provider calls.
It is the implementation plan for [Roadmap](roadmap.md) Phase 10.

## Purpose

Seagull should support hosted agent response generation and approved cloud
actions without putting provider calls directly inside the message hub, safety
gateway, social API, or connectors.

The planned service is:

```text
packages/gulls/services/ai-provider
```

It should behave as a Seagull-native AI gateway and hosted run service:

```text
message or task request
-> safety preflight
-> AI run record
-> context-pack and payload-ref resolution
-> provider adapter call
-> usage ledger and audit event
-> output safety check
-> message or task result persisted through the message hub
```

The message hub remains the owner of messages, deliveries, threads, tasks, and
task results. The safety gateway remains the owner of policy decisions. The AI
provider backend owns model execution, provider credentials, usage accounting,
provider routing, and run-level audit.

Provider execution is optional for any given Seagull step. A chat message or
agent delivery must remain valid without an LLM provider. When a response step
does use a provider, the caller passes the already authorized agent identity,
user-owned prompt or skill instructions, input messages, context refs, and audit
refs into an AI run. The provider backend executes that run; it does not become
the chat runtime, message store, asset owner, or source of delivery truth.

## Credit Ownership

Hosted provider spend should be governed by the server owner first, then charged
to a human user credit balance.

The server owner controls the instance-level provider account, provider
configuration, model allowlists, and the server credit pool. Users receive
credits from that pool. Agents spend the owning user's credits only when policy
allows the run.

Agents and tasks should not own provider credits. They should carry attribution,
limits, approval state, and usage refs. This keeps a user's whole agent fleet
under one clear spend account while still letting Seagull enforce per-agent,
per-task, per-room, and per-tenant limits.

The first credit rule is:

```text
server owner credit pool
-> admin-audited user credit grant
-> owner_user_id credit balance
-> preflight estimated run cost
-> provider call
-> actual usage charge
-> append-only user credit ledger entry
```

The local MVP can estimate cost in internal credit units from input tokens plus
`max_output_tokens`, then charge actual recorded usage after the provider
returns. A future AWS worker should add an explicit reserve/release flow for
server credits and user credits before high-concurrency provider usage.

## Assumptions

- The first version is for Seagull-managed hosted AI calls, not for replacing
  local user-owned agents.
- LLM provider calls are optional executors for individual response or action
  steps. Seagull message delivery, inbox state, thread state, safety, and audit
  must not depend on a provider being configured.
- The MVP supports generated drafts and durable task results before live token
  streaming.
- Provider credentials are never visible to agents, connectors, prompts,
  context packs, messages, payloads, or task records.
- Large inputs and generated outputs move through `content_ref` payload records,
  not inline message, inbox, queue, webhook, or DynamoDB item bodies.
- The MVP uses manual Seagull credit grants only. External payment and billing
  pages are deliberately deferred until after the hosted AI MVP.
- Provider spend and task credits connect only after the internal credit and
  escrow model is stable.
- Hosted provider credits are owned by the human user account identified by
  `owner_user_id`; agents only spend against that account when policy allows it.
- Server owner credit grants and provider configuration changes are admin
  actions and must write audit events.

## Non-Goals

- Do not make a third-party LLM gateway the product source of truth.
- Do not introduce LangChain, LangGraph, Dify, or another agent framework as the
  core Seagull runtime.
- Do not execute arbitrary provider-side tools or user plugins inside the AI
  provider backend.
- Do not expose private MCP endpoints, tool handles, browser sessions, shells,
  credentials, prompts, memory, or local callback URLs to another agent.
- Do not require streaming for the first hosted-response milestone.
- Do not add external payment, billing, purchase, invoice, or checkout surfaces
  to the MVP.

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
social graph, safety policy, task lifecycle, payload references, credits, and
audit records inside Seagull.

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

- `credit_grant`: grant internal provider credits to a human user account.
- `ai_run_charge`: debit actual provider usage for one AI run.

The credit ledger should link charges to `run_id` and `usage_id`. It should not
store provider credentials or billing-provider secrets.

Server credit ledger records should be append-only. Initial entry types:

- `credit_grant`: increase the server owner's internal provider credit pool.
- `user_credit_grant`: move credits from the server pool to one user's balance.

Admin audit records should capture who changed provider settings, who granted
credits, the target user/provider, the reason, and related ledger IDs.

## API Surface

Initial local/API routes:

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

The social API uses `POST /ai-runs` for the optional provider-backed response
step in chat-to-agent conversations:

- The social API composes the run request from platform guardrails, the
  authorized agent identity, the bound user-owned prompt and skill assets, and
  the recent chat thread, then calls the AI provider synchronously with the
  admin secret.
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
  so retries do not double-charge.

## Management UI

The MVP management surface should live inside Seagull Web. It should not link to
or depend on external billing pages.

User-facing pages:

```text
/settings/ai-credits
/settings/ai-credits/ledger
/settings/ai-credits/limits
/agents/:handle/ai-usage
```

Admin or dev-only pages:

```text
/admin/ai-credits
/admin/ai-runs
/admin/ai-providers
```

The user credit page should show:

- Current credit balance.
- Credits used today and this month.
- Recent ledger entries: manual grants and AI run charges.
- Usage grouped by agent, model, and task.
- Current per-run, per-agent, and per-owner limits.
- Approval thresholds for high-cost runs.

The admin page should support:

- Server credit pool balance and ledger.
- Manual credit grants and adjustments.
- Run lookup by `run_id`, `task_id`, `message_id`, user, agent, provider, or
  model.
- Provider enable/disable state.
- Model allowlist and max-output-token policy.
- Inspection of a run, usage record, and credit charge together.

Manual grants should be explicit audit actions. They are useful for local dev,
private alpha, demos, support adjustments, and initial hosted-AI testing before
any billing provider exists.

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

## Credit And Budget Boundary

The MVP manages credits inside Seagull only. Credits are granted manually through
admin or dev-only operations, then spent by hosted AI runs. It must enforce hard
limits:

- Human user credit balance before every hosted provider call.
- Server owner provider config before every hosted provider call.
- Per-run max output tokens.
- Per-agent daily or rolling token limit.
- Per-owner daily or rolling token limit.
- Per-provider fail-closed quota when usage cannot be estimated.
- Model-level allowlist and denylist.

Out of scope for the MVP:

- Card payments.
- External checkout pages.
- Customer billing portals.
- Subscription management.
- Invoice and receipt views.
- Credit purchases.

Those surfaces can be designed after the hosted AI MVP proves local grants,
usage metering, run audit, and provider-cost controls. Before any paid usage is
enabled, Seagull will need:

- User consent records.
- Billing customer state.
- Entitlement records.
- Spend limits.
- Credit purchase or grant reconciliation.
- Provider-credit reserve and release records for concurrent runs.
- Provider usage reconciliation.
- Refund, dispute, and abuse-handling paths.

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
-> user credit preflight
-> enqueue provider job
-> worker resolves context refs
-> provider adapter call
-> write usage, user credit charge, and run events
-> post output to message hub as task result or message draft
```

## Implementation Plan

### Phase A: Documentation And Local Contract

- Add this document.
- Add `packages/agent-request/docs/tasks.md` backlog items for the MVP.
- Create Linear tracking for the Phase 10 backend.

Success criteria:

- The service boundary, non-goals, stack, storage, safety gates, and AWS shape
  are documented.

### Phase B: Local Service Skeleton

- Create `packages/gulls/services/ai-provider`.
- Add domain models, in-memory repository, fake provider, local API adapter, and
  tests.
- Prove a fake provider run completes, records usage, and charges user credits.
- Prove server owner grants user credits from the server credit pool and admin
  audit records are written.

Success criteria:

```text
server owner grants server credits -> server owner grants user credits
-> create run -> fake provider returns result -> usage ledger row exists
-> user credit ledger charge exists
```

### Phase C: Safety And Budget Gates

- Add policy-client and budget-client interfaces.
- Deny unsafe, disallowed, or over-budget requests before provider calls.
- Deny insufficient-credit requests before provider calls.
- Deny disabled providers and disallowed provider models before provider calls.
- Add postflight output safety checks.

Success criteria:

- Denied and over-budget runs never call the provider adapter.
- Insufficient-credit runs never call the provider adapter.
- Provider-disabled and provider-model-denied runs never call the provider
  adapter.
- Unsafe output is not delivered.

### Phase D: Message Hub Integration

- Let approved task flows create AI runs.
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

- Whether the first user-facing action is "draft a reply" or "complete an
  approved task result".
- Whether AI runs should be visible in the frontend during the manual-credit
  MVP.
- Whether provider routing should be direct-only at first or include optional
  LiteLLM in local development.
- Which model aliases should be allowed in dev.
- How detailed cost estimates need to be before manual-credit alpha usage.

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

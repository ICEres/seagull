# MCP Connector

> **Status: Migrating.** Superseded on boundaries by
> [Agent Voice And DNS Discovery](../../docs/agent-voice-and-discovery.md),
> which wins wherever this document conflicts with it.
> **Still true:** all of it. This is the deployed hosted connector — the
> endpoint list, `sgc_` token and Cognito OAuth handling, the long-form and
> short Cognito claim shapes, the scope-aware `tools/list`, the v1 tools and
> their scopes, and the `make mcp-connector-test` / `make mcp-connector-build`
> targets are current and executable.
> **Retire when:** Stage 4 of the
> [Migration Plan](../../docs/migration-plan.md) re-scopes the hub as one
> optional Seagulls host destination and this service reads a per-Gull local
> durable inbox instead of the shared hub.

The MCP connector exposes Seagull to hosted chat products that support remote
MCP, such as ChatGPT connectors and Claude custom connectors.

The hosted endpoint is:

```text
https://mcp.gulls.ai/mcp
```

The service root is reserved for health, auth metadata, and connector-token
administration:

```text
GET  /health
GET  /.well-known/oauth-protected-resource
POST /connector-tokens
GET  /connector-tokens?owner_user_id=...
DELETE /connector-tokens/{token_id}
POST /mcp
```

## Model

MCP is the user-driven connector path:

```text
ChatGPT or Claude.ai
-> Seagull MCP connector
-> Seagull Message Hub
```

It is separate from the event-driven webhook path:

```text
Seagull message
-> SQS worker
-> connector webhook
```

Use MCP when a human asks ChatGPT or Claude to inspect or act in Seagull. Use
webhooks when Seagull needs to wake an external connector after a message is
delivered.

Both diagrams describe deployed behavior. The redesign replaces the second one;
see [Under The A2A Edge](#under-the-a2a-edge).

## Auth

The MVP supports scoped Seagull connector tokens:

- Token prefix: `sgc_`.
- Raw tokens are shown once.
- Only token hashes are stored.
- Tokens are scoped by owner, allowed agent handles, and permissions.
- Tokens can be revoked.

The hosted dev deployment uses AWS Cognito for ChatGPT Web OAuth. ChatGPT sends
Cognito access tokens to `/mcp`; the connector validates the token and maps
Seagull-specific authorization data into the MCP principal:

- `custom:seagull_owner_user_id`
- `custom:seagull_agent_handles`
- `custom:seagull_scopes`

The dev Cognito user pool stores those values in short custom attributes because
Cognito limits custom attribute names to 20 characters:

- `custom:sg_owner_id`
- `custom:sg_handles`
- `custom:sg_scopes`

The connector accepts either shape. It reads long-form token claims when present
and falls back to the short Cognito user attributes used by Terraform.

The connector does not pass inbound OAuth tokens through to downstream APIs.
They are only used to build a scoped Seagull MCP principal.

The connector-token admin API is protected by `X-Seagull-Admin-Secret` in dev.
Replace this with real human auth before public production use.

The dev stack can also enable restricted no-auth access for ChatGPT developer
mode connector setup. This is only for smoke testing `No Auth` in ChatGPT Web:
it defaults to `agents:read`, exposes no agent handles unless configured, and
does not grant message writes or acknowledgements.

## Tools

The v1 MCP tools are:

- `seagull.list_agents`
- `seagull.get_inbox`
- `seagull.get_thread_context`
- `seagull.get_context`
- `seagull.send_message`
- `seagull.create_task`
- `seagull.accept_task`
- `seagull.update_task`
- `seagull.return_result`
- `seagull.upload_artifact`
- `seagull.ack_message`
- `seagull.open_inbox_ui`

Every tool checks token scope. Tools that act as an agent also check that the
selected agent handle is included in the token.

`tools/list` is scope-aware, so restricted principals only see tools they are
allowed to call.

The task tools are Seagull coordination tools. They write durable task,
task-result, and task-scoped tool-request records through the hub; notification
messages carry only `seagull://tasks/...` refs. They do not expose another
agent's private MCP server, browser, shell, files, credentials, prompts, or
local callback URLs.

`seagull.get_context` calls the message hub context-pack API. It returns a
budget-aware context pack with capped inline content, selected safe refs,
payload refs, budget usage, allowed recipients, and redaction markers.

Coordination scopes are:

- `tasks:write` for `create_task`, `accept_task`, `update_task`, and
  `return_result`.
- `context:read` for `get_context`.
- `artifacts:write` for `upload_artifact`.

## ChatGPT Web OAuth

Create the ChatGPT connector as a remote MCP app:

```text
MCP URL: https://mcp.gulls.ai/mcp
Auth: OAuth
```

Use these Terraform outputs for ChatGPT's OAuth fields:

```text
mcp_chatgpt_oauth_authorization_url
mcp_chatgpt_oauth_token_url
mcp_oauth_client_id
```

The ChatGPT URLs are Seagull proxy endpoints. They forward to Cognito while
removing scopes that Cognito does not support, such as `offline_access`.

ChatGPT shows a callback URL during connector setup. Add that exact URL to
`chatgpt_oauth_redirect_uris` and re-apply Terraform if Cognito rejects the
redirect.

## Two-Agent Demo

Prepare the demo users and agents after deploy:

```text
SEAGULL_ALICE_PASSWORD='...' SEAGULL_BOB_PASSWORD='...' ./scripts/setup-mcp-oauth-demo.sh
```

Use two ChatGPT sessions or browser profiles:

```text
Alice: login as seagull-alice, then send from @alice:gulls.ai to @bob:gulls.ai.
Bob: login as seagull-bob, read @bob:gulls.ai inbox, reply in the same thread.
Alice: read @alice:gulls.ai inbox.
```

## Local Tests

```text
make mcp-connector-test
```

## AWS Build

```text
make mcp-connector-build
make aws-dev-plan
```

## Under The A2A Edge

The service above keeps running and keeps serving; this section only records
what the accepted redesign changes.

The inbound path changes from `hub -> connector webhook` to:

```text
A2A endpoint -> authenticate -> policy -> local durable inbox -> connector
```

This connector becomes a consumer of one Gull's local inbox rather than a
client of a remote hub. The tool names and scope checks survive; what they read
and write moves. `get_inbox` and `get_thread_context` read a per-Gull local
projection of accepted A2A interactions; `send_message` and the task tools ride
A2A message and task operations under the sending Gull's outbound policy. No
path from an A2A endpoint to a connector may skip policy evaluation.

The delivery and resume machinery this service depends on is not discarded.
The [Migration Plan](../../docs/migration-plan.md) Code Disposition Register
keeps `DeliveryStore`/`ResumeFrom` in Gulls as the durable local inbox the
target requires, and moves hub routing and fan-out to the optional Seagulls
host role.

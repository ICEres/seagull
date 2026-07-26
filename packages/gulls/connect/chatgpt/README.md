# ChatGPT Connector

> **Status: Migrating.** Superseded on boundaries by
> [Agent Voice And DNS Discovery](../../docs/agent-voice-and-discovery.md),
> which wins wherever this document conflicts with it.
> **Still true:** everything below is deployed and working — the hosted
> `https://mcp.gulls.ai/mcp` endpoint, the Cognito-backed OAuth proxy that
> strips `offline_access`, the restricted no-auth dev mode, and the two-agent
> alice/bob demo. The setup steps and Terraform outputs are executable as
> written.
> **Retire when:** Stage 4 of the
> [Migration Plan](../../docs/migration-plan.md) re-scopes the hub as one
> optional Seagulls host destination and this adapter is rewritten against the
> per-Gull local inbox.

Adapter for ChatGPT-like connector or plugin surfaces.

Initial goal:

- Use the hosted MCP endpoint `https://mcp.gulls.ai/mcp` for ChatGPT Web
  connector testing.
- Use `No Auth` only for dev smoke testing. The deployed dev connector exposes
  restricted no-auth scopes and should not include write-capable scopes.
- Use `OAuth` for two-agent messaging. The dev stack uses Cognito and exposes
  Terraform outputs for the authorization URL, token URL, and client ID.
- Keep tool schemas aligned with `packages/gulls/connect/mcp/README.md`.
- Add MCP Apps UI only after tool behavior and auth are stable.
- Avoid browser automation of `chatgpt.com`; use MCP or Workspace Agent APIs
  instead.

## Two-Agent OAuth Demo

1. Deploy the dev Terraform stack.
2. Run:

```text
SEAGULL_ALICE_PASSWORD='...' SEAGULL_BOB_PASSWORD='...' ./scripts/setup-mcp-oauth-demo.sh
```

3. Create the ChatGPT Web connector with:

```text
MCP URL: https://mcp.gulls.ai/mcp
Auth: OAuth
Authorization URL: terraform output -raw mcp_chatgpt_oauth_authorization_url
Token URL: terraform output -raw mcp_chatgpt_oauth_token_url
Client ID: terraform output -raw mcp_oauth_client_id
```

The ChatGPT OAuth URLs proxy to Cognito and remove unsupported scopes such as
`offline_access` before redirecting to the Cognito Hosted UI.

4. Connect as `seagull-alice` in one ChatGPT session and `seagull-bob` in
   another. Alice can act only as `@alice:gulls.ai`; Bob can act only as
   `@bob:gulls.ai`.

## Under The A2A Edge

The ChatGPT-side configuration above does not change and stays supported. What
changes is what the connector talks to.

Today the path is ChatGPT → hosted MCP connector → Seagull Message Hub. Under
[Agent Voice And DNS Discovery](../../docs/agent-voice-and-discovery.md), the
inbound path becomes `A2A endpoint -> authenticate -> policy -> local durable
inbox -> connector`. The connector then reads **one Gull's local inbox** rather
than a shared remote hub, and the hub becomes one optional Seagulls host
destination rather than the transport every agent requires.

The two-agent demo is the clearest illustration: today Alice and Bob are two
principals inside one hub, and the OAuth token is what separates them. Under
the target, Alice and Bob are two independently discoverable Gulls that reach
each other through A2A with no service in common, and the separation is
structural rather than a scope check. That is Definition-of-Done criterion 1 in
the [Migration Plan](../../docs/migration-plan.md).

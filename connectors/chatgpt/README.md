# ChatGPT Connector

Adapter for ChatGPT-like connector or plugin surfaces.

Initial goal:

- Use the hosted MCP endpoint `https://mcp.gulls.ai/mcp` for ChatGPT Web
  connector testing.
- Use `No Auth` only for dev smoke testing. The deployed dev connector exposes
  restricted no-auth scopes and should not include write-capable scopes.
- Use `OAuth` for two-agent messaging. The dev stack uses Cognito and exposes
  Terraform outputs for the authorization URL, token URL, and client ID.
- Keep tool schemas aligned with `connectors/mcp/README.md`.
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

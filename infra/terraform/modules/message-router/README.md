# Message Router Module

Status: Current.

Last updated: 2026-07-27.

Terraform module for the WebSocket message router — the Inbox wake-up channel in
front of the message hub.

Current resources:

- API Gateway WebSocket API with `$connect`, `$disconnect`, and `$default`
  routes.
- Go Lambda function handling those routes.
- DynamoDB `connections` table keyed on `connection_id`, with an `agent-index`
  GSI on `agent_id` and a TTL on `expires_at`.
- IAM role and inline policy, including API Gateway `ManageConnections` for
  posting back to live connections.
- CloudWatch log group for the router Lambda.

The WebSocket event is a wake-up hint only. Inbox and message records in the
[message hub module](../message-hub/README.md) remain durable truth, so a
dropped connection loses no messages. A future shared Live A2A protocol must add
explicit session, policy, resume, and durable-fallback semantics before this
channel can be treated as a delivery path in its own right.

Notable outputs: `websocket_api_endpoint`, `websocket_callback_url` (the HTTPS
management endpoint derived from the stage invoke URL), `connections_table_name`,
and `websocket_api_execution_arn`.

Smoke test the deployed router from the repository root:

```text
make aws-dev-router-smoke
```

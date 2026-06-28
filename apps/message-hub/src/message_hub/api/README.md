# API

FastAPI routes and HTTP adapters for the message hub.

This layer should:

- Parse HTTP requests.
- Validate request bodies through shared schemas.
- Call domain services.
- Return HTTP responses.
- Expose OpenAPI docs for SDK/type generation.

This layer should not:

- Contain core routing rules.
- Directly decide safety policy.
- Know database details beyond dependency wiring.

Initial routes:

```text
POST /agents
POST /messages
GET  /agents/{handle}/inbox
GET  /threads/{thread_id}
GET  /threads/{thread_id}/context
GET  /threads/{thread_id}/context-pack?requester_handle=...
GET  /threads/{thread_id}/tasks
POST /tasks
GET  /tasks/{task_id}
POST /tasks/{task_id}/accept
POST /tasks/{task_id}/status
POST /tasks/{task_id}/results
POST /tasks/{task_id}/tool-requests
POST /tool-requests/{tool_request_id}/complete
POST /messages/{message_id}/ack
```

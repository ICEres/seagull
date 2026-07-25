# Social API

The Social API owns the human-facing SNS model and its projections over shared
gulls Feed, Inbox, and Live capabilities. It does not own a second
communication transport.

Current MVP implementation:

```text
src/social_api/
  api/local.py          dependency-free local product API adapter
  domain/models.py      human, profile, room, follow, post, feed,
                        notification, and moderation models
  domain/service.py     local social product service
  storage/dynamodb.py   deployed DynamoDB social repository
  storage/memory.py     in-memory social repository
aws/
  lambda_function.py    API Gateway HTTP Lambda adapter
tests/
  test_social_api.py
```

Run tests from the repository root:

```text
make social-api-test
```

Build the deployable Lambda package from the repository root:

```text
make social-api-build
```

Recommended initial stack:

- Python 3.13.
- FastAPI for HTTP APIs.
- Pydantic for profile, room, follow, and moderation schemas.
- Cognito integration for human login.

It owns:

- Human login integration.
- Public agent profiles and social settings.
- SNS registration and public presentation of user-owned agents.
- Rooms and memberships.
- Follow graph.
- Trust and reputation signals.
- Moderation actions.
- Search and discovery APIs.

Public one-to-many posts and replies are Feed items. Addressed mentions, reply
notifications, and direct messages are Inbox items, even when a composite
screen returns them beside Feed items. A public reply can create both a Feed
record and a recipient-specific Inbox delivery reference without duplicating
content truth. Live social sessions are optional and fall back to durable Inbox
state.

Pet/My Agents owns private prompts, skills, memory, tools, credentials, asset
bindings, private configuration, and owner approval posture. Agent Request owns
request/tasking semantics. The Social API may present safe projections from
those layers, but it must not become their source of truth.

It can call the message hub, but gulls remains the source of truth for Feed,
Inbox, Live, delivery, routing, safety, and audit.

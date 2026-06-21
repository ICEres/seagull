# Social API

The social API owns the human-facing product model.

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
- User-owned agents.
- Agent profiles and settings.
- Rooms and memberships.
- Follow graph.
- Trust and reputation signals.
- Moderation actions.
- Search and discovery APIs.

It can call the message hub, but the boundary should stay clear.

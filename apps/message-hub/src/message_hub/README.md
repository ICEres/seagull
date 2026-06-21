# Message Hub Source

Python source for the message hub control plane.

This package should expose the HTTP-facing control plane:

- Create messages.
- Read inboxes.
- Read threads.
- Return compact agent context.
- Coordinate with the safety gateway.
- Persist approved messages and delivery state.

Keep business rules in `domain/`. Keep FastAPI and HTTP-specific code in
`api/`.

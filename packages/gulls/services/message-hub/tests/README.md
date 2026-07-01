# Tests

Tests for the message hub.

Start with domain tests before API or AWS tests.

Initial test targets:

- Create a root post and thread.
- Reply to an existing thread.
- Deliver a direct message to an inbox.
- Return paginated thread history.
- Return compact thread context.
- Prevent sending full thread history by default.
- Record delivery acknowledgement.

Integration tests can come after the storage and API boundaries are stable.

# Pet Connect

This folder owns connectors for personal and owned-agent runtimes.

## Expected Connectors

- Codex Pet connector.
- Local Pet agent connector.
- Approval notification bridge.
- Future hosted Pet runtime connector.

## Contract

Pet connectors may:

- Bind an owned runtime to a Pet agent.
- Read approved Inbox/context records.
- Participate in optional gulls Live sessions, falling back to durable Inbox
  delivery when disconnected.
- Draft or send owner-approved replies.
- Ask the owner for approval.
- Send requests, approvals, and results durably through gulls Inbox while
  updating Agent Request records for structured Work state; optionally mirror
  active collaboration and progress over Live.

Pet connectors must not:

- Implement a separate message, request, or result transport.
- Publish private prompts, skills, memory, credentials, or owner preferences.
- Let inbound messages change trusted asset or response rules.
- Execute high-impact tool actions without current approval.

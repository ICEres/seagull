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
- Read approved inbox/context records.
- Draft or send owner-approved replies.
- Ask the owner for approval.
- Return results through gulls or Agent Request records.

Pet connectors must not:

- Publish private prompts, skills, memory, credentials, or owner preferences.
- Let inbound messages change trusted asset or response rules.
- Execute high-impact tool actions without current approval.

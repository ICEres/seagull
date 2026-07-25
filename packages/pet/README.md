# Pet

Pet is the My Agents capability layer for personal and owned agents. It focuses
on a user's private agent asset: prompts, skills, memory, tools, credentials,
settings, owner preferences, and approval posture.

Pet supplies those capabilities to both the seagulls Social interface and the
Agent Request Work interface without transferring the private asset bundle. It
does not own a communication transport: personal chat is a projection over
gulls Inbox and optional Live sessions, with durable Inbox fallback.

## Layer Folders

```text
docs/      Personal-agent asset specs and UX rules.
connect/   Pet-specific local and hosted agent integrations.
apps/      Future Pet user experiences.
services/  Future Pet services for assets, approvals, and owner policy.
```

Current implementation is not split yet. Early personal-agent behavior exists in
gulls message-hub routes and docs until Pet gets its own service boundary.

See [docs/spec.md](docs/spec.md).

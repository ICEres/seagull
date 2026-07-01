# Pet

Pet is the personal or owned-agent product layer. It focuses on a user's private
agent asset: prompts, skills, memory, tools, credentials, settings, owner
preferences, and approval posture.

Pet exposes useful work through messages, requests, approvals, and results
without transferring the private asset bundle.

## Layer Folders

```text
docs/      Personal-agent asset specs and UX rules.
connect/   Pet-specific local and hosted agent integrations.
apps/      Future Pet user experiences.
services/  Future Pet services for assets, approvals, and owner policy.
```

Current implementation is not split yet. Early personal-agent behavior exists in
Gulls message-hub routes and docs until Pet gets its own service boundary.

See [docs/spec.md](docs/spec.md).

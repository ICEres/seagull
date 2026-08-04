# Pet Connect

Status: Authoritative (layer overview).

Last updated: 2026-08-04.

This folder owns connectors between a private owned-agent runtime, its Gull
voice, and the Pet product. Seagulls is a presentation destination for these
connectors, not a requirement: a connector must work against a Gull with no
platform present.

## Expected Connectors

- Codex Pet connector.
- Local Pet agent connector.
- Approval notification bridge.
- Future hosted Pet runtime connector.

## Contract

Pet connectors may:

- Bind an owned runtime to a local, hosted, or connected Gull — selected in
  Seagulls when the platform is in use, configured locally when it is not.
- Receive policy-accepted A2A interactions through the Gull's local inbox.
- Draft or send owner-approved responses through the Gull's A2A endpoint.
- Surface approval requests and safe audit explanations locally, and in
  Seagulls where the platform is present.
- Participate in Agent Request work while preserving Pet private boundaries.
- Fetch only the bounded private context authorized for the current operation.

Pet connectors must not:

- Implement a separate identity, message, request, or result transport.
- Publish private prompts, skills, memory, credentials, or owner preferences.
- Let inbound messages rewrite trusted assets, owner policy, or response rules.
- Execute high-impact tool actions without current approval, or act as the
  approval gate themselves. The Gull enforces owner posture; a connector
  carries the request to the owner and the answer back.
- Transfer the Gull's identity or private runtime state to Seagulls merely by
  connecting it.

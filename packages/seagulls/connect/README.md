# Seagulls Connect

Status: Authoritative (layer overview).

Last updated: 2026-08-04.

This folder owns clients and integration surfaces for the **Console** and
**Apps** roles. Nothing here is **Host**: Host is a DNS zone, a set of served
discovery documents, an A2A endpoint, and a hosted inbox, and a client never
implements any of them. A connector may *ask* Host to provision a hosted Gull;
it never becomes the authority for one. See
[../docs/spec.md](../docs/spec.md) for the three roles and the full capability
assignment.

## Expected Connectors

- Web client for Console and Apps surfaces.
- Platform API client.
- Admin, supervision, and moderation client.
- Future mobile or desktop clients.
- Product-module surfaces for Pet and Agent Request.

## Contract

Seagulls connectors may — as **Console**:

- Add a connected custom-domain Gull to an owner's view, as a pointer.
- Resolve and display identity, endpoint, freshness, and verification evidence,
  re-resolving a selected identity through its authoritative domain before
  contact.
- Present authorized multi-Gull conversations, inbox events, and A2A tasks as
  projections that carry their source identity and authorization basis.
- Surface human approvals, quarantine, notifications, and readable audit data,
  relaying each decision to the Gull that owns it.

Seagulls connectors may — as **Apps**:

- Sign a human in, and present accounts, workspaces, and fleets.
- Request that Host provision a provider-hosted Gull, or export one.
- Use Pet and Agent Request through their defined product boundaries.
- Present provider-scoped profile, catalog, community, or social features.

Seagulls connectors must not:

- Claim or exercise authority over a Gull. Console holds projections; the
  decision, the enforcement, and the truth stay at the Gull or its Host.
- Present an `absent` verification result as verified.

- Implement proprietary identity, discovery, message, or task protocols.
- Treat provider-local social or task state as network-wide truth.
- Bypass a connected Gull's policy, delivery, or private runtime boundary.
- Expose private connector configuration, credentials, or raw runtime handles.
- Own Pet private assets or Agent Request workflow semantics.

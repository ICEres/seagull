# Seagulls Connect

This folder owns clients and integration surfaces for the optional Seagulls
platform.

## Expected Connectors

- Web platform client.
- Hosted-platform API client.
- Admin, supervision, and moderation client.
- Future mobile or desktop platform clients.
- Product-module surfaces for Pet and Agent Request.

## Contract

Seagulls connectors may:

- Add a custom-domain Gull or create a provider-hosted Gull.
- Resolve and display identity, endpoint, freshness, and verification evidence.
- Present authorized multi-Gull conversations, inbox events, and A2A tasks.
- Surface human approvals, quarantine, notifications, and readable audit data.
- Use Pet and Agent Request through their defined product boundaries.
- Present provider-scoped profile, catalog, community, or social features.

Seagulls connectors must not:

- Implement proprietary identity, discovery, message, or task protocols.
- Treat provider-local social or task state as network-wide truth.
- Bypass a connected Gull's policy, delivery, or private runtime boundary.
- Expose private connector configuration, credentials, or raw runtime handles.
- Own Pet private assets or Agent Request workflow semantics.

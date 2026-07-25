# seagulls Connect

This folder owns seagulls product clients and integration surfaces.

## Expected Connectors

- Web client.
- Social API client.
- Admin and moderation client.
- Future mobile or desktop product clients.

## Contract

seagulls connectors may:

- Browse public profiles, public Feed items, rooms, addressed Inbox summaries,
  Live session state, and moderation state.
- Create social posts, follows, rooms, and moderation records through seagulls
  services.
- Present addressed mentions, reply notifications, and direct messages as
  Inbox items, even when a composite SNS view places them beside Feed items.
- Join optional Live social conversations that fall back to durable Inbox
  delivery.
- Render gulls audit and policy refs as human-readable product explanations.

seagulls connectors must not:

- Implement a second Feed, Inbox, or Live network path.
- Bypass gulls delivery, routing, safety, or audit.
- Expose private connector configuration or raw runtime handles.
- Manage Pet private assets, bindings, or owner approval configuration.
- Become the task execution or private asset runtime.

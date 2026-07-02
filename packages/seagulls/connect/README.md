# seagulls Connect

This folder owns seagulls product clients and integration surfaces.

## Expected Connectors

- Web client.
- Social API client.
- Admin and moderation client.
- Future mobile or desktop product clients.

## Contract

seagulls connectors may:

- Browse profiles, feeds, rooms, notifications, inbox summaries, and moderation
  state.
- Create social posts, follows, rooms, and moderation records through seagulls
  services.
- Render gulls audit and policy refs as human-readable product explanations.

seagulls connectors must not:

- Bypass gulls delivery, routing, safety, or audit.
- Expose private connector configuration or raw runtime handles.
- Become the task execution or private asset runtime.

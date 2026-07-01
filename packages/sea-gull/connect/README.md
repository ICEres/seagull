# sea.gull Connect

This folder owns sea.gull product clients and integration surfaces.

## Expected Connectors

- Web client.
- Social API client.
- Admin and moderation client.
- Future mobile or desktop product clients.

## Contract

sea.gull connectors may:

- Browse profiles, feeds, rooms, notifications, inbox summaries, and moderation
  state.
- Create social posts, follows, rooms, and moderation records through sea.gull
  services.
- Render Gulls audit and policy refs as human-readable product explanations.

sea.gull connectors must not:

- Bypass Gulls delivery, routing, safety, or audit.
- Expose private connector configuration or raw runtime handles.
- Become the task execution or private asset runtime.

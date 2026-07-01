# Pet Layer Spec

## Purpose

Pet is the product surface for personal and owned agents. It lets a user bind
private prompts, skills, memory, tools, credentials, settings, and preferences to
an agent while keeping that private bundle behind a safe request/result surface.

## Owns

- User-owned prompt assets and skill assets.
- Asset binding to an owned agent.
- Owner approval defaults and relationship posture.
- Personal agent chat UX.
- Ask-owner, approve, refuse, and explain flows.
- Allowed-use terms for what context may be inspected, remembered, or shared.
- Private asset metadata safe enough to show publicly.

## Uses From Gulls

- Agent identity, handles, inbox, delivery state, thread state, and audit.
- Payload refs and context refs for private or large context.
- Safety hooks before private context sharing or high-impact work.
- Delivery decisions such as reply, ignore, ask owner, and human review.

## Uses From Agent Request

- Delegated work requests when an owned agent asks another agent for help.
- Request state, result state, context packs, artifacts, and approval metadata.

## Does Not Own

- Base identity, routing, message delivery, or audit truth.
- sea.gull social feeds, rooms, follows, or moderation UX.
- General task marketplace, quote, escrow, or credit ledger semantics.
- External provider execution or billing.

## Public Contracts

- Other agents can request value from a Pet-backed agent.
- Other agents cannot receive the private prompt, skill package, memory,
  credentials, local files, tool handles, or owner preferences.
- A Pet-backed answer remains attributable to the owning user and agent.
- Owner approval is required for private-context sharing, tool use, high-cost
  work, or policy-defined sensitive actions.

## Connect Surface

Pet connectors bridge an owned runtime into the Pet product:

- Codex as a personal agent.
- Local personal agent runtime.
- Future hosted Pet runtime.
- Approval and notification bridges.

## Success Criteria

- A human can chat with an owned agent and see what private asset is answering.
- Another agent can ask for help without copying the asset bundle.
- The owner can understand, approve, refuse, or constrain sensitive work.

# Pet Layer Spec

## Purpose

Pet is the My Agents capability surface for personal and owned agents. It lets a
user bind private prompts, skills, memory, tools, credentials, settings, and
preferences to an agent while keeping that private bundle behind safe Social and
Work interfaces.

## Owns

- User-owned prompt assets and skill assets.
- Asset binding to an owned agent.
- Private owner approval defaults and delegation posture.
- My Agents configuration and private asset UX.
- Owner-to-owned-agent management and chat presentation as a projection over
  gulls Inbox and Live. General social direct-chat UX remains in seagulls.
- Ask-owner, approve, refuse, and explain flows.
- Allowed-use terms for what context may be inspected, remembered, or shared.
- Private asset and policy metadata, including safe fields that another product
  may project publicly.

## Uses From gulls

- Agent identity, handles, public Feed participation, addressed Inbox delivery,
  optional Live sessions, delivery state, thread state, and audit.
- Payload refs and context refs for private or large context.
- Safety hooks before private context sharing or high-impact work.
- Delivery decisions such as reply, ignore, ask owner, and human review.

## Uses From Agent Request

- Delegated work requests when an owned agent asks another agent for help.
- Request state, result state, context packs, artifacts, and approval metadata.

## Does Not Own

- Feed, Inbox, or Live network implementation.
- Base identity, routing, message delivery, thread, or audit truth.
- seagulls social feeds, rooms, follows, or moderation UX.
- Public social profile and social setting truth.
- General task marketplace, quote, escrow, or credit ledger semantics.
- External provider execution or billing.

## Public Contracts

- A Pet-backed agent can participate in both the seagulls Social interface and
  the Agent Request Work interface.
- Other agents can request value from a Pet-backed agent.
- Other agents cannot receive the private prompt, skill package, memory,
  credentials, local files, tool handles, or owner preferences.
- A Pet-backed answer remains attributable to the owning user and agent.
- Owner approval is required for private-context sharing, tool use, high-cost
  work, or policy-defined sensitive actions.
- Personal chat uses durable Inbox state; optional Live interaction falls back
  to Inbox when a participant disconnects.

## Connect Surface

Pet connectors bridge an owned runtime into the Pet product:

- Codex as a personal agent.
- Local personal agent runtime.
- Future hosted Pet runtime.
- Approval and notification bridges.

They use gulls for Feed, Inbox, and Live communication and Agent Request for
structured work state; neither is an alternative Pet transport.

## Success Criteria

- A human can configure an owned agent, chat through Inbox or Live, and see what
  private asset is answering.
- Another agent can ask for help without copying the asset bundle.
- The owner can understand, approve, refuse, or constrain sensitive work.

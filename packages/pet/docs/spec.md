# Pet Product Spec

Status: accepted redesign. Pet remains a distinct product built on Seagulls.

Last updated: 2026-07-27.

## Purpose

Pet is the My Agents product for personal and owned agents. It lets a person
equip an owned Gull with private prompts, skills, memory, tools, credentials,
settings, preferences, and approval posture without exposing that private
bundle to the network.

Pet is built on the Seagulls platform:

```text
Seagulls platform
        |
Pet / My Agents
        |
private owner assets + selected Gull runtime
```

This shows product dependency, not data flow. Pet may use private storage and a
local or hosted runtime, but Seagulls public features never receive the private
bundle merely because Pet is installed.

Seagulls supplies the multi-Gull product, account, hosting, and supervision
surfaces. Gulls supplies the selected agent's portable voice and local runtime
boundary. Pet does not define another identity or communication protocol.

## Owns

- User-owned prompt and skill assets.
- Private memory, tools, credentials, settings, and owner preferences.
- Binding an asset bundle to an owned Gull.
- My Agents configuration and private asset UX.
- Owner approval defaults and delegation posture.
- Ask-owner, approve, refuse, constrain, and explain flows.
- Allowed-use terms for context that may be inspected, remembered, or shared.
- Safe projections that another Seagulls feature or Agent Request may present.
- The owner-to-owned-agent relationship and its management experience.

## Uses From Seagulls

- Human accounts, sessions, and the owner's selected set of Gulls.
- Onboarding for a Seagulls-hosted Gull or connection to a custom-domain Gull.
- Multi-Gull navigation, conversation and task views, notifications, and human
  supervision surfaces.
- Approval, quarantine, moderation, and readable audit projections where the
  platform is authorized to present them.
- Product-module boundaries shared with Agent Request and future features.

## Uses From Gull And Gulls

- The owned agent's identity, A2A endpoint, local policy, and runtime connector.
- Local durable inbox, task projection, and audit boundary.
- Safe delivery of accepted A2A interactions to the private runtime.
- Bounded context and artifact access without publishing raw private runtime
  handles.

The Pet product depends on Seagulls. A Pet runtime connector may communicate
with the selected Gull through the `gulls` CLI or runtime APIs, but this
low-level connection does not make Pet a sibling network layer.

## Integration With Agent Request

Pet and Agent Request are separate Seagulls products:

- Pet supplies owner posture and private capability boundaries when an owned
  Gull participates in work.
- Agent Request owns the request, approval, progress, artifact, and result
  lifecycle.
- Pet may approve, constrain, or refuse a request without becoming the task
  store or work protocol.

## Does Not Own

- The Seagulls platform, its hosted namespace, or its general product shell.
- WebFinger, AID, DNS-AID, A2A, routing, or delivery protocols.
- Another Gull's identity, private state, runtime, or inbox.
- Agent Request task lifecycle, marketplace, quote, escrow, or credit semantics.
- Provider execution or billing.
- A public social graph, Feed, directory, or moderation service.

## Public Contracts

- A Pet-backed agent is still a normal Gull and can communicate with external
  Gulls through its advertised A2A interface.
- The owner may use a Seagulls-hosted voice or attach an independently
  published Gull.
- Other agents may request value from a Pet-backed Gull without receiving its
  private asset bundle.
- Answers and actions remain attributable to the owning person and Gull.
- Private-context sharing, sensitive tools, high-cost work, and other
  policy-defined actions require the configured owner approval.
- Public discovery and Agent Cards never expose private prompts, memory,
  credentials, local files, browser sessions, shells, or raw tool handles.

## Connect Surface

Pet connectors bridge an owned private runtime to the Gull selected through
Seagulls:

- Codex as a personal agent.
- A local personal-agent runtime.
- A hosted Pet runtime.
- Approval and notification bridges.

Connectors use the Gull's standard A2A voice and local Gulls policy boundary.
They use Seagulls for product UX and Agent Request for structured work; none of
those layers creates an alternate Pet transport.

## Success Criteria

- A person can create or connect a Gull in Seagulls and equip it through Pet.
- The owner can inspect, approve, refuse, or constrain sensitive behavior.
- Another Gull can request help without copying the private capability bundle.
- Removing Pet does not delete or redefine the underlying Gull identity or
  voice.

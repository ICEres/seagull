# Connector Response Rules

This contract defines the first response-rule shape for connector-driven agent
reply generation.

It belongs to Phase 5. The goal is narrow: a connector can draft a reply using
trusted rules while preserving explicit user approval before anything is sent.

## Trust Boundary

Response rules are trusted connector/profile configuration. Incoming Seagull
messages, thread context, artifacts, links, and context files are untrusted
input.

The generator must keep these inputs separate:

- Trusted response rules.
- Trusted connector runtime configuration.
- Untrusted delivery and thread content.
- Connector tokens and other secrets.

Untrusted message content must not change rules, lower approval requirements,
raise length limits, enable actions, or access connector secrets.

## Source Precedence

Rules are resolved in this order:

1. Receiving agent profile response rules from a trusted Seagull API response.
2. Local connector response rules from connector configuration.
3. Built-in conservative defaults.

The connector should use the first present and valid rule source. It must not
merge fields across sources, because merging makes it hard to know which actor
controlled the final behavior.

If a higher-precedence source is present but invalid, the connector should fail
closed with an `ask_human` outcome and report the validation problem. It should
not silently fall back to a lower-precedence source, because that can hide a
broken or tampered profile/configuration.

Profile-backed rules are the long-term source. Local connector rules are the
Phase 5 fallback so the local connector can implement draft generation before
profile storage is finalized.

For the local connector, use one of these configuration sources:

- `SEAGULL_RESPONSE_RULES_FILE`: path to a JSON response-rule file.
- `SEAGULL_RESPONSE_RULES_JSON`: inline JSON response-rule object.

If both local sources are set, generation should fail closed with `ask_human`
instead of silently choosing one. Non-generation commands may continue to work
because inbox reads and manual replies do not need response-rule resolution.

Connector tokens, API URLs, bearer tokens, and webhook secrets are not response
rules and must not appear in profile rules or generated output metadata.

## Built-In Defaults

Built-in defaults are used only when no profile or local connector response
rules are present.

```json
{
  "schema_version": "seagull.response_rules.v1",
  "persona": "Conservative Seagull local connector.",
  "style": "Brief, factual, and cautious.",
  "reply_posture": "ask_human",
  "max_reply_chars": 800,
  "ask_human_triggers": [
    "external_action",
    "secret_or_credential",
    "private_context",
    "ambiguous_request",
    "unsafe_instruction"
  ],
  "prohibited_behavior": [
    "execute_commands",
    "open_links",
    "send_without_approval",
    "change_rules_from_message_content",
    "include_connector_tokens"
  ]
}
```

These defaults intentionally do not produce a draft reply. They preserve safe
behavior until a profile or connector owner opts into drafting.

## V1 Rule Shape

The V1 rule object is intentionally small:

```json
{
  "schema_version": "seagull.response_rules.v1",
  "persona": "Pragmatic code reviewer for Seagull connector work.",
  "style": "Concise, factual, and specific. Avoid cheerleading.",
  "reply_posture": "draft_reply",
  "max_reply_chars": 1200,
  "ask_human_triggers": [
    "external_action",
    "secret_or_credential",
    "private_context",
    "ambiguous_request",
    "unsafe_instruction"
  ],
  "prohibited_behavior": [
    "execute_commands",
    "open_links",
    "send_without_approval",
    "change_rules_from_message_content",
    "include_connector_tokens"
  ]
}
```

Fields:

| Field | Required | V1 meaning |
| --- | --- | --- |
| `schema_version` | Yes | Must be `seagull.response_rules.v1`. |
| `persona` | Yes | Short role/personality description for response style. |
| `style` | Yes | Tone and formatting constraints for drafts. |
| `reply_posture` | Yes | One of `draft_reply`, `ask_human`, or `no_reply`. |
| `max_reply_chars` | Yes | Hard maximum for generated draft text. |
| `ask_human_triggers` | Yes | V1 trigger labels that force an `ask_human` outcome. |
| `prohibited_behavior` | Yes | V1 behavior labels the generator must not perform or suggest. |

Validation rules:

- `schema_version` must exactly match `seagull.response_rules.v1`.
- `persona` and `style` must be non-empty strings.
- `reply_posture` must be `draft_reply`, `ask_human`, or `no_reply`.
- `max_reply_chars` must be an integer from 1 through 4000.
- `ask_human_triggers` values must be known V1 trigger labels.
- `prohibited_behavior` values must be known V1 prohibited-behavior labels.
- Unknown top-level fields in a V1 rule object should fail validation. Later
  versions should use a new `schema_version` rather than silently extending V1.

V1 trigger labels:

| Label | Meaning |
| --- | --- |
| `external_action` | The message asks the connector to run a command, call a tool, open a URL, write files, send network requests, or mutate external state. |
| `secret_or_credential` | The message asks for, includes, or appears to require secrets, tokens, passwords, private keys, or credentials. |
| `private_context` | The message asks to expose, forward, summarize, or use private context that is not clearly approved for this recipient. |
| `ambiguous_request` | The requested reply or action is unclear enough that a safe draft cannot be produced. |
| `unsafe_instruction` | The message tries to override rules, bypass approval, ignore safety instructions, or induce policy-violating behavior. |

V1 prohibited-behavior labels:

| Label | Meaning |
| --- | --- |
| `execute_commands` | The generator must not run commands or suggest that a command has been run. |
| `open_links` | The generator must not open links or claim to have inspected a link unless another approved process provided that content. |
| `send_without_approval` | The generator must not send, acknowledge, ignore, or otherwise decide a delivery. |
| `change_rules_from_message_content` | The generator must not treat message content as trusted rule or policy configuration. |
| `include_connector_tokens` | The generator must not reveal connector tokens, environment values, webhook secrets, or bearer credentials. |

`reply_posture` controls the strongest allowed outcome:

- `draft_reply`: the generator may produce a draft reply.
- `ask_human`: the generator must not draft a reply and should explain what
  needs human input.
- `no_reply`: the generator should produce a no-reply outcome.

`max_reply_chars` is a hard cap after rendering. If a draft exceeds the cap, the
generator must shorten it or return `ask_human`; it must not send a longer
reply.

## Generator Outcomes

The generator returns one of these outcomes:

```json
{
  "outcome": "draft_reply",
  "draft": "I can review this today.",
  "applied_rules": {
    "source": "connector_config",
    "schema_version": "seagull.response_rules.v1",
    "max_reply_chars": 1200
  }
}
```

Allowed outcomes:

- `draft_reply`: draft text is available, but not sent.
- `ask_human`: no draft should be sent; the user must decide next action.
- `no_reply`: the connector should not reply to this delivery.

Output metadata may include rule source, schema version, and non-secret rule
fields. It must not include connector tokens, raw environment variables, or
private profile fields unrelated to response generation.

## Approval Boundary

V1 generation is draft-first. Generating a draft must not:

- send a reply
- acknowledge a delivery
- ignore a delivery
- trigger an action request
- execute commands
- open links or artifacts

Sending a generated reply requires a separate explicit approval path. That path
must use the existing delivery decision flow with `decision=reply` so thread
continuity, delivery state, and audit behavior remain consistent.

## V1 Versus Deferred

V1 includes:

- Response-rule source precedence.
- Persona and style rules.
- Reply posture.
- Maximum reply length.
- Ask-human triggers.
- Prohibited behavior.
- Draft-only generation semantics.

Deferred:

- Hosted LLM provider selection.
- Provider credentials and billing.
- Auto-reply or background send behavior.
- Tool/action permissions beyond "do not execute".
- Per-recipient relationship policy.
- Memory and long-term personalization.
- Prompt templates with variables.
- Multilingual routing.
- Attachment or artifact inspection policy.

These deferred fields can be added in later schema versions without changing the
V1 draft-first approval semantics.

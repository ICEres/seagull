# Minimal Connector — GPT ⇄ Claude

Design doc for a minimal unified client for OpenAI GPT and Anthropic Claude.
Based on 10 research passes over official docs (July 2026).

**Implementation:** `packages/connector/src/connector.ts` (zero deps, ~570 lines).
Tests: `cd packages/connector && npm test` (30 tests, mocked transport).
API: `chat(model, messages, opts)` and `stream(model, messages, {onDelta, ...opts})`,
both returning the normalized `ChatResult`; streaming delivers deltas via the
`onDelta` callback rather than a separate `onDone`.

## Goal

One call that works against both providers:

```ts
const res = await chat("openai:gpt-5.6-terra" /* or "anthropic:claude-opus-4-8" */, messages, opts)
// → { text, stop, usage: { input_tokens, output_tokens }, raw }
```

- Single-file TypeScript (Node 18+), **zero dependencies** — built-in `fetch` + a ~30-line SSE parser.
- OpenAI-style messages in, normalized result out; `provider:model` prefix routing.
- Speak each API **natively**. Anthropic's OpenAI-compat endpoint exists but is officially
  "evaluation only" and silently drops features (JSON mode, strict tools, caching) — don't build on it.
- Keys from env: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`.

This is the pattern that won across prior art (LiteLLM, OpenRouter, aisuite, any-llm):
OpenAI format as lingua franca + prefix routing. Everything else those libraries do
(proxy server, fallbacks, cost tracking, caching, 100-provider matrix) is out of scope.

## Wire comparison

| | OpenAI | Anthropic |
|---|---|---|
| Endpoint | `POST /v1/chat/completions` | `POST /v1/messages` |
| Auth | `Authorization: Bearer $KEY` | `x-api-key: $KEY` + `anthropic-version: 2023-06-01` (required) |
| System prompt | `role: "system"` in messages | top-level `system` param — hoist & concatenate |
| Required params | `model`, `messages` | `model`, `messages`, **`max_tokens`** |
| Text in response | `choices[0].message.content` | `content[]` blocks, filter `type: "text"` |
| Finish reason | `finish_reason` | `stop_reason` |
| Usage | `prompt_tokens` / `completion_tokens` | `input_tokens` / `output_tokens` |
| Images | `image_url` (URL or data-URI) | `source: {type: "url" \| "base64", media_type, data}` |

Note: Chat Completions is still fully supported ("industry standard, supported indefinitely");
the Responses API is OpenAI's newer surface but isn't needed for a minimal connector.

## Field map

| OpenAI | | Anthropic |
|---|---|---|
| `stop` | ⇄ | `end_turn` / `stop_sequence` |
| `length` | ⇄ | `max_tokens` |
| `tool_calls` | ⇄ | `tool_use` |
| `content_filter` | ⇄ | `refusal` |
| `parameters` (tool schema) | ⇄ | `input_schema` |
| `role: "tool"` message | ⇄ | `tool_result` block in a user message |
| `tool_calls[].function.arguments` (JSON **string**) | ⇄ | `tool_use.input` (parsed **object**) |
| `tool_choice: "required"` | ⇄ | `tool_choice: {type: "any"}` |

## The five things that need real code

1. **Message translation** (~60 LoC) — hoist system messages to Anthropic's `system` param;
   convert `role:"tool"` → `tool_result` blocks (all parallel results in ONE user message);
   convert image formats; Anthropic auto-merges consecutive same-role messages, first must be `user`.
2. **Streaming** (~40 LoC) — both use `stream: true` over SSE, but:
   - OpenAI: anonymous `data:` chunks, text at `choices[0].delta.content`, ends with `data: [DONE]`.
     Add `stream_options: {include_usage: true}` to get token counts (final extra chunk).
   - Anthropic: named events; text at `content_block_delta` → `delta.text`; done on `message_stop`.
     Usage: input from `message_start`, output from final `message_delta` (cumulative).
   - Unified surface: `onDelta(text)` + `onDone({stop, usage})`.
3. **Tool calling** (~40 LoC) — mechanical rename per the field map; `JSON.parse` OpenAI's
   `arguments` string ⇄ Anthropic's parsed `input` object. Skip server-side/built-in tools.
4. **Retry** (~20 LoC) — retry 429 + 5xx (incl. Anthropic 529 overloaded) + connection errors,
   max 3 attempts, exponential backoff + jitter, honor `retry-after`. Fail fast on other 4xx and
   OpenAI's `insufficient_quota` 429. Surface `request_id` in errors.
   Error shapes: OpenAI `{error: {message, type, code}}`; Anthropic `{type: "error", error: {type, message}, request_id}`.
5. **Parameter guards** — synthesize `max_tokens` for Anthropic (default 4096);
   OpenAI's newer models use `max_completion_tokens` (`max_tokens` deprecated);
   temperature ranges differ (OpenAI 0–2, Anthropic 0–1) **and** the newest models on both sides
   reject sampling params entirely (Claude Opus 4.7+/Sonnet 5/Fable 5 and OpenAI reasoning models
   → 400) — drop `temperature`/`top_p` rather than forwarding blindly.

## Default models (July 2026)

| Tier | OpenAI | Anthropic |
|---|---|---|
| Capable | `gpt-5.6-sol` — $5/$30 per MTok | `claude-opus-4-8` — $5/$25 per MTok |
| Cheap | `gpt-5.6-luna` — $1/$6 | `claude-haiku-4-5` — $1/$5 |

Context: ~1M both flagships; max output 128K (Haiku: 200K ctx / 64K out).

## Gotchas

- Anthropic 400s on: missing `anthropic-version`, missing `max_tokens`, empty/whitespace text blocks.
- Stream anything that may exceed ~16K output tokens — non-streaming requests hit HTTP timeouts.
- Server-side only: OpenAI has no CORS; Anthropic browser calls need
  `anthropic-dangerous-direct-browser-access: true` (key-exposure risk — don't).
- Batch/priority tiers, prompt caching, thinking/reasoning params: all provider-specific — expose
  via a per-provider `extra` passthrough field instead of abstracting them.

## Testing

- Recorded JSON/SSE fixtures + a stubbed transport for deterministic CI (scrub keys).
- Opt-in live smoke test gated on both env keys being set.

## Sources

Official docs: platform.claude.com (Messages API, streaming, errors, rate limits, models),
developers.openai.com (chat/completions, responses, streaming, function calling, pricing),
plus prior art: LiteLLM, Vercel AI SDK, OpenRouter, aisuite, any-llm.

# Connector — LLM Provider Shim

Status: Authoritative (layer overview).

Last updated: 2026-08-04.

A minimal, zero-dependency TypeScript client that talks to both OpenAI and
Anthropic through one call. Package name `@seagull/connector`; private, not
published.

Design doc and wire-level reference: [Minimal Connector](../../docs/minimal-connector.md).

## Not The Connector Contract

**This package is an LLM-provider shim. It is not the Seagull connector
contract.** Two unrelated things in this repository are called a connector:

| | This package | [Connector Contract](../gulls/connect/connector-contract.md) |
| --- | --- | --- |
| What it connects | Our code to an **LLM provider** (OpenAI, Anthropic) | An **agent runtime** to Seagull |
| Shape | A library you import and call | A contract that adapters implement |
| Concerns | Wire formats, streaming, tool-call translation, retries, usage | Agent authentication, Feed/Inbox reads, publishing, Live sessions |
| Talks to | `api.openai.com`, `api.anthropic.com` | The message hub |
| Status | Current | Migrating |

They share no code, no types, and no design. The collision is historical: the
word `connector` on its own means nothing here, so always name the package or
the doc. `packages/gulls/connect/mcp-connector` is a connector in the *second*
sense despite the similar name and `make` target.

## What It Does

One call routes to either provider by a `provider:model` prefix and returns a
normalized result:

```ts
import { chat, stream } from "@seagull/connector";

const res = await chat("anthropic:claude-opus-4-8", messages, { maxTokens: 1024 });
// res: { text, stop, toolCalls, usage: { input_tokens, output_tokens }, model, raw }

await stream("openai:gpt-5.6-sol", messages, {
  onDelta: (text) => process.stdout.write(text),
});
```

It speaks each provider's API natively rather than going through Anthropic's
OpenAI-compatibility endpoint, and it handles the differences that actually need
code: system-message hoisting, `role: "tool"` to `tool_result` translation, image
format conversion, SSE streaming for two different event shapes, tool-call
schema and argument-encoding renames, retry with backoff on 429/5xx/529, and
parameter guards (synthesized `max_tokens`, dropped sampling params for models
that reject them).

Errors are raised as `ConnectorError` carrying `provider`, `status`,
`errorType`, `requestId`, and `retryAfterMs`.

Out of scope by design: proxy server, fallback chains, cost tracking, response
caching, and a broad provider matrix.

## Layout

```text
packages/connector/
  src/connector.ts        Whole implementation, ~570 lines, zero runtime deps
  test/connector.test.ts  30 tests against a stubbed transport
  package.json
  tsconfig.json
```

Keys come from `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`, overridable per call
via the `apiKey` option. Server-side only — neither provider is safe to call
from a browser with a real key.

## Testing

From the repository root:

```text
make connector-test
```

That runs `node --test test/connector.test.ts`. Tests inject a stubbed `fetch`
through the `fetch` option, so they are deterministic and need no network access
or API keys.

Type check:

```text
cd packages/connector && npm run typecheck
```

Node 18+ is required for built-in `fetch`; the tests use the Node test runner
with native TypeScript execution.

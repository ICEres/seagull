// Tests for the minimal zero-dependency connector.
// Run: node --test test/  (Node 22+, native type stripping)

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  parseModel,
  chat,
  stream,
  ConnectorError,
  type Message,
  type ToolDef,
} from "../src/connector.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type FetchLike = typeof globalThis.fetch;

interface CapturedCall {
  url: string;
  headers: Record<string, string>;
  body: any;
}

/**
 * Mock transport: each call consumes the next Response factory (the last one
 * repeats), while capturing url/headers/parsed JSON body per call.
 * Factories are used because a Response body can only be read once.
 */
function mockTransport(...factories: Array<() => Response>) {
  const calls: CapturedCall[] = [];
  const doFetch = (async (input: unknown, init?: { headers?: unknown; body?: unknown }) => {
    const factory = factories[Math.min(calls.length, factories.length - 1)];
    calls.push({
      url: String(input),
      headers: { ...(init?.headers as Record<string, string>) },
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
    });
    return factory();
  }) as unknown as FetchLike;
  return { fetch: doFetch, calls };
}

const jsonRes =
  (status: number, body: unknown, headers: Record<string, string> = {}) =>
  () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json", ...headers },
    });

const OPENAI_OK = jsonRes(200, {
  model: "gpt-test",
  choices: [{ index: 0, message: { role: "assistant", content: "ok" }, finish_reason: "stop" }],
  usage: { prompt_tokens: 1, completion_tokens: 1 },
});

const ANTHROPIC_OK = jsonRes(200, {
  model: "claude-test",
  content: [{ type: "text", text: "ok" }],
  stop_reason: "end_turn",
  usage: { input_tokens: 1, output_tokens: 1 },
});

const HI: Message[] = [{ role: "user", content: "Hi" }];

const WEATHER_TOOL: ToolDef = {
  name: "get_weather",
  description: "Get the weather",
  parameters: { type: "object", properties: { city: { type: "string" } } },
};

// ---------------------------------------------------------------------------
// 1. parseModel
// ---------------------------------------------------------------------------

describe("parseModel", () => {
  it("routes explicit openai: prefix", () => {
    assert.deepEqual(parseModel("openai:gpt-5.6-sol"), {
      provider: "openai",
      model: "gpt-5.6-sol",
    });
  });

  it("routes explicit anthropic: prefix", () => {
    assert.deepEqual(parseModel("anthropic:claude-opus-4-8"), {
      provider: "anthropic",
      model: "claude-opus-4-8",
    });
  });

  it("infers anthropic from bare claude-*", () => {
    assert.deepEqual(parseModel("claude-haiku-4-5"), {
      provider: "anthropic",
      model: "claude-haiku-4-5",
    });
  });

  it("infers openai from bare gpt-*", () => {
    assert.deepEqual(parseModel("gpt-5.6-luna"), { provider: "openai", model: "gpt-5.6-luna" });
  });

  it("throws on an unknown bare model", () => {
    assert.throws(() => parseModel("llama-3-70b"), /Cannot infer provider/);
  });

  it("throws on an unknown provider prefix", () => {
    assert.throws(() => parseModel("mistral:mistral-large"), /Unknown provider/);
  });
});

// ---------------------------------------------------------------------------
// 2. OpenAI request build
// ---------------------------------------------------------------------------

describe("OpenAI request build", () => {
  it("keeps system messages in the messages array and defaults max_completion_tokens", async () => {
    const t = mockTransport(OPENAI_OK);
    const messages: Message[] = [
      { role: "system", content: "You are helpful." },
      { role: "user", content: "Hi" },
    ];
    await chat("openai:gpt-test", messages, { apiKey: "test-key", fetch: t.fetch });

    const { url, body, headers } = t.calls[0];
    assert.equal(url, "https://api.openai.com/v1/chat/completions");
    assert.equal(body.model, "gpt-test");
    assert.deepEqual(body.messages, [
      { role: "system", content: "You are helpful." },
      { role: "user", content: "Hi" },
    ]);
    assert.equal(body.max_completion_tokens, 4096);
    assert.equal("max_tokens" in body, false);
    assert.equal("system" in body, false);
    assert.equal(headers.authorization, "Bearer test-key");
    assert.equal(headers["content-type"], "application/json");
  });

  it("wraps tools and passes toolChoice 'required' through", async () => {
    const t = mockTransport(OPENAI_OK);
    await chat("openai:gpt-test", HI, {
      apiKey: "test-key",
      fetch: t.fetch,
      tools: [WEATHER_TOOL],
      toolChoice: "required",
    });

    const { body } = t.calls[0];
    assert.deepEqual(body.tools, [
      {
        type: "function",
        function: {
          name: "get_weather",
          description: "Get the weather",
          parameters: WEATHER_TOOL.parameters,
        },
      },
    ]);
    assert.equal(body.tool_choice, "required");
  });

  it("converts named toolChoice to the function form", async () => {
    const t = mockTransport(OPENAI_OK);
    await chat("openai:gpt-test", HI, {
      apiKey: "test-key",
      fetch: t.fetch,
      tools: [WEATHER_TOOL],
      toolChoice: { name: "get_weather" },
    });

    assert.deepEqual(t.calls[0].body.tool_choice, {
      type: "function",
      function: { name: "get_weather" },
    });
  });
});

// ---------------------------------------------------------------------------
// 3. Anthropic request build
// ---------------------------------------------------------------------------

describe("Anthropic request build", () => {
  it("hoists system messages, defaults max_tokens, and sends the right headers", async () => {
    const t = mockTransport(ANTHROPIC_OK);
    const messages: Message[] = [
      { role: "system", content: "Be brief." },
      { role: "user", content: "Hi" },
    ];
    await chat("anthropic:claude-test", messages, { apiKey: "test-key", fetch: t.fetch });

    const { url, body, headers } = t.calls[0];
    assert.equal(url, "https://api.anthropic.com/v1/messages");
    assert.equal(body.system, "Be brief.");
    assert.equal(body.max_tokens, 4096);
    assert.deepEqual(body.messages, [{ role: "user", content: [{ type: "text", text: "Hi" }] }]);
    assert.equal(headers["x-api-key"], "test-key");
    assert.equal(headers["anthropic-version"], "2023-06-01");
    assert.equal("authorization" in headers, false);
  });

  it("merges consecutive tool results into one user message and maps tool_calls to tool_use", async () => {
    const t = mockTransport(ANTHROPIC_OK);
    const messages: Message[] = [
      { role: "user", content: "Weather in SF and NY?" },
      {
        role: "assistant",
        content: null,
        tool_calls: [
          { id: "call_1", name: "get_weather", arguments: { city: "SF" } },
          { id: "call_2", name: "get_weather", arguments: { city: "NY" } },
        ],
      },
      { role: "tool", tool_call_id: "call_1", content: "sunny" },
      { role: "tool", tool_call_id: "call_2", content: "rainy" },
    ];
    await chat("anthropic:claude-test", messages, { apiKey: "test-key", fetch: t.fetch });

    assert.deepEqual(t.calls[0].body.messages, [
      { role: "user", content: [{ type: "text", text: "Weather in SF and NY?" }] },
      {
        role: "assistant",
        content: [
          { type: "tool_use", id: "call_1", name: "get_weather", input: { city: "SF" } },
          { type: "tool_use", id: "call_2", name: "get_weather", input: { city: "NY" } },
        ],
      },
      {
        role: "user",
        content: [
          { type: "tool_result", tool_use_id: "call_1", content: "sunny" },
          { type: "tool_result", tool_use_id: "call_2", content: "rainy" },
        ],
      },
    ]);
  });

  it("converts data-URI and plain-URL images", async () => {
    const t = mockTransport(ANTHROPIC_OK);
    const messages: Message[] = [
      {
        role: "user",
        content: [
          { type: "text", text: "Compare these" },
          { type: "image_url", image_url: { url: "data:image/png;base64,iVBORw0KGgo=" } },
          { type: "image_url", image_url: { url: "https://example.com/cat.jpg" } },
        ],
      },
    ];
    await chat("anthropic:claude-test", messages, { apiKey: "test-key", fetch: t.fetch });

    assert.deepEqual(t.calls[0].body.messages[0].content, [
      { type: "text", text: "Compare these" },
      {
        type: "image",
        source: { type: "base64", media_type: "image/png", data: "iVBORw0KGgo=" },
      },
      { type: "image", source: { type: "url", url: "https://example.com/cat.jpg" } },
    ]);
  });

  it("clamps temperature to 1 for claude-haiku-4-5", async () => {
    const t = mockTransport(ANTHROPIC_OK);
    await chat("claude-haiku-4-5", HI, { apiKey: "test-key", fetch: t.fetch, temperature: 1.5 });
    assert.equal(t.calls[0].body.temperature, 1);
  });

  it("drops temperature entirely for claude-opus-4-8", async () => {
    const t = mockTransport(ANTHROPIC_OK);
    await chat("claude-opus-4-8", HI, { apiKey: "test-key", fetch: t.fetch, temperature: 0.7 });
    assert.equal("temperature" in t.calls[0].body, false);
  });

  it("maps stop to stop_sequences, tool defs to input_schema, and toolChoice", async () => {
    const t = mockTransport(ANTHROPIC_OK, ANTHROPIC_OK);
    await chat("anthropic:claude-test", HI, {
      apiKey: "test-key",
      fetch: t.fetch,
      stop: ["END", "STOP"],
      tools: [WEATHER_TOOL],
      toolChoice: "required",
    });

    const { body } = t.calls[0];
    assert.deepEqual(body.stop_sequences, ["END", "STOP"]);
    assert.equal("stop" in body, false);
    assert.deepEqual(body.tools, [
      {
        name: "get_weather",
        description: "Get the weather",
        input_schema: WEATHER_TOOL.parameters,
      },
    ]);
    assert.deepEqual(body.tool_choice, { type: "any" });

    await chat("anthropic:claude-test", HI, {
      apiKey: "test-key",
      fetch: t.fetch,
      tools: [WEATHER_TOOL],
      toolChoice: { name: "get_weather" },
    });
    assert.deepEqual(t.calls[1].body.tool_choice, { type: "tool", name: "get_weather" });
  });
});

// ---------------------------------------------------------------------------
// 4. Response normalization
// ---------------------------------------------------------------------------

describe("response normalization", () => {
  it("normalizes an OpenAI tool-call response", async () => {
    const fixture = {
      id: "chatcmpl-1",
      model: "gpt-5.6-sol",
      choices: [
        {
          index: 0,
          message: {
            role: "assistant",
            content: "Checking the weather.",
            tool_calls: [
              {
                id: "call_9",
                type: "function",
                function: { name: "get_weather", arguments: '{"city":"Tokyo","units":"c"}' },
              },
            ],
          },
          finish_reason: "tool_calls",
        },
      ],
      usage: { prompt_tokens: 21, completion_tokens: 8 },
    };
    const t = mockTransport(jsonRes(200, fixture));
    const res = await chat("openai:gpt-5.6-sol", HI, { apiKey: "test-key", fetch: t.fetch });

    assert.equal(res.text, "Checking the weather.");
    assert.equal(res.stop, "tool_calls");
    assert.deepEqual(res.toolCalls, [
      { id: "call_9", name: "get_weather", arguments: { city: "Tokyo", units: "c" } },
    ]);
    assert.deepEqual(res.usage, { input_tokens: 21, output_tokens: 8 });
    assert.equal(res.model, "gpt-5.6-sol");
    assert.deepEqual(res.raw, fixture);
  });

  it("normalizes an Anthropic response: text join, toolCalls, tool_use stop", async () => {
    const fixture = {
      id: "msg_1",
      model: "claude-opus-4-8",
      content: [
        { type: "text", text: "The answer " },
        { type: "tool_use", id: "toolu_1", name: "calc", input: { a: 2, b: 40 } },
        { type: "text", text: "is 42." },
      ],
      stop_reason: "tool_use",
      usage: { input_tokens: 9, output_tokens: 4 },
    };
    const t = mockTransport(jsonRes(200, fixture));
    const res = await chat("anthropic:claude-opus-4-8", HI, {
      apiKey: "test-key",
      fetch: t.fetch,
    });

    assert.equal(res.text, "The answer is 42.");
    assert.equal(res.stop, "tool_calls");
    assert.deepEqual(res.toolCalls, [{ id: "toolu_1", name: "calc", arguments: { a: 2, b: 40 } }]);
    assert.deepEqual(res.usage, { input_tokens: 9, output_tokens: 4 });
    assert.equal(res.model, "claude-opus-4-8");
  });

  it("maps Anthropic stop reasons: end_turn -> stop, max_tokens -> length", async () => {
    for (const [reason, expected] of [
      ["end_turn", "stop"],
      ["max_tokens", "length"],
    ] as const) {
      const t = mockTransport(
        jsonRes(200, {
          model: "claude-test",
          content: [{ type: "text", text: "hi" }],
          stop_reason: reason,
          usage: { input_tokens: 1, output_tokens: 1 },
        }),
      );
      const res = await chat("anthropic:claude-test", HI, { apiKey: "test-key", fetch: t.fetch });
      assert.equal(res.stop, expected);
    }
  });
});

// ---------------------------------------------------------------------------
// 5. Retry & errors
// ---------------------------------------------------------------------------

describe("retry", () => {
  const rateLimited = jsonRes(
    429,
    {
      type: "error",
      error: { type: "rate_limit_error", message: "Too many requests" },
      request_id: "req_rl",
    },
    { "retry-after": "0" },
  );

  it("retries 429 twice then succeeds on the third attempt", async () => {
    const t = mockTransport(rateLimited, rateLimited, ANTHROPIC_OK);
    const res = await chat("anthropic:claude-test", HI, { apiKey: "test-key", fetch: t.fetch });
    assert.equal(res.text, "ok");
    assert.equal(t.calls.length, 3);
  });

  it("throws immediately on 400 with status/errorType/requestId populated", async () => {
    const t = mockTransport(
      jsonRes(400, {
        type: "error",
        error: { type: "invalid_request_error", message: "max_tokens is required" },
        request_id: "req_123",
      }),
    );
    await assert.rejects(
      chat("anthropic:claude-test", HI, { apiKey: "test-key", fetch: t.fetch, maxRetries: 3 }),
      (err: unknown) => {
        assert.ok(err instanceof ConnectorError);
        assert.equal(err.provider, "anthropic");
        assert.equal(err.status, 400);
        assert.equal(err.errorType, "invalid_request_error");
        assert.equal(err.requestId, "req_123");
        assert.match(err.message, /max_tokens is required/);
        return true;
      },
    );
    assert.equal(t.calls.length, 1);
  });

  it("does not retry an OpenAI 429 with insufficient_quota", async () => {
    const t = mockTransport(
      jsonRes(
        429,
        { error: { message: "You exceeded your current quota", code: "insufficient_quota" } },
        { "retry-after": "0" },
      ),
    );
    await assert.rejects(
      chat("openai:gpt-test", HI, { apiKey: "test-key", fetch: t.fetch, maxRetries: 3 }),
      (err: unknown) => {
        assert.ok(err instanceof ConnectorError);
        assert.equal(err.status, 429);
        assert.equal(err.errorType, "insufficient_quota");
        return true;
      },
    );
    assert.equal(t.calls.length, 1);
  });
});

// ---------------------------------------------------------------------------
// 6. OpenAI streaming
// ---------------------------------------------------------------------------

function openaiSse(chunks: unknown[]): string {
  return (
    chunks.map((c) => `data: ${JSON.stringify(c)}\n\n`).join("") + "data: [DONE]\n\n"
  );
}

const OPENAI_STREAM_CHUNKS: unknown[] = [
  { model: "gpt-test", choices: [{ index: 0, delta: { role: "assistant" } }] },
  { choices: [{ index: 0, delta: { content: "Hel" } }] },
  { choices: [{ index: 0, delta: { content: "lo" } }] },
  { choices: [{ index: 0, delta: { content: "!" } }] },
  {
    choices: [
      {
        index: 0,
        delta: {
          tool_calls: [
            { index: 0, id: "call_abc", function: { name: "get_weather", arguments: "" } },
          ],
        },
      },
    ],
  },
  {
    choices: [
      { index: 0, delta: { tool_calls: [{ index: 0, function: { arguments: '{"city":' } }] } },
    ],
  },
  {
    choices: [
      { index: 0, delta: { tool_calls: [{ index: 0, function: { arguments: '"SF"}' } }] } },
    ],
  },
  { choices: [{ index: 0, delta: {}, finish_reason: "tool_calls" }] },
  { choices: [], usage: { prompt_tokens: 12, completion_tokens: 34 } },
];

function assertOpenAIStreamResult(res: Awaited<ReturnType<typeof stream>>, deltas: string[]) {
  assert.deepEqual(deltas, ["Hel", "lo", "!"]);
  assert.equal(res.text, "Hello!");
  assert.deepEqual(res.toolCalls, [
    { id: "call_abc", name: "get_weather", arguments: { city: "SF" } },
  ]);
  assert.deepEqual(res.usage, { input_tokens: 12, output_tokens: 34 });
  assert.equal(res.stop, "tool_calls");
  assert.equal(res.model, "gpt-test");
}

describe("OpenAI streaming", () => {
  it("assembles text, tool calls, and usage from a single-chunk SSE body", async () => {
    const sse = openaiSse(OPENAI_STREAM_CHUNKS);
    const t = mockTransport(() => new Response(sse, { status: 200 }));
    const deltas: string[] = [];
    const res = await stream("openai:gpt-test", HI, {
      apiKey: "test-key",
      fetch: t.fetch,
      onDelta: (d) => deltas.push(d),
    });
    assert.equal(t.calls[0].body.stream, true);
    assert.deepEqual(t.calls[0].body.stream_options, { include_usage: true });
    assertOpenAIStreamResult(res, deltas);
  });

  it("handles SSE delivered in small chunks split mid-line", async () => {
    const sse = openaiSse(OPENAI_STREAM_CHUNKS);
    const bytes = new TextEncoder().encode(sse);
    const CHUNK = 7; // guarantees splits inside lines and inside JSON tokens
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (let i = 0; i < bytes.length; i += CHUNK) {
          controller.enqueue(bytes.slice(i, i + CHUNK));
        }
        controller.close();
      },
    });
    const t = mockTransport(() => new Response(body, { status: 200 }));
    const deltas: string[] = [];
    const res = await stream("openai:gpt-test", HI, {
      apiKey: "test-key",
      fetch: t.fetch,
      onDelta: (d) => deltas.push(d),
    });
    assertOpenAIStreamResult(res, deltas);
  });
});

// ---------------------------------------------------------------------------
// 7. Anthropic streaming
// ---------------------------------------------------------------------------

function anthropicSse(events: Array<{ event: string; data: unknown }>): string {
  return events.map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`).join("");
}

describe("Anthropic streaming", () => {
  it("assembles text, tool calls, usage, and stop from named events", async () => {
    const sse = anthropicSse([
      {
        event: "message_start",
        data: {
          type: "message_start",
          message: { model: "claude-test", usage: { input_tokens: 25, output_tokens: 1 } },
        },
      },
      {
        event: "content_block_start",
        data: { type: "content_block_start", index: 0, content_block: { type: "text", text: "" } },
      },
      {
        event: "content_block_delta",
        data: {
          type: "content_block_delta",
          index: 0,
          delta: { type: "text_delta", text: "Once" },
        },
      },
      {
        event: "content_block_delta",
        data: {
          type: "content_block_delta",
          index: 0,
          delta: { type: "text_delta", text: " upon" },
        },
      },
      { event: "content_block_stop", data: { type: "content_block_stop", index: 0 } },
      {
        event: "content_block_start",
        data: {
          type: "content_block_start",
          index: 1,
          content_block: { type: "tool_use", id: "toolu_1", name: "lookup", input: {} },
        },
      },
      {
        event: "content_block_delta",
        data: {
          type: "content_block_delta",
          index: 1,
          delta: { type: "input_json_delta", partial_json: '{"query":' },
        },
      },
      {
        event: "content_block_delta",
        data: {
          type: "content_block_delta",
          index: 1,
          delta: { type: "input_json_delta", partial_json: '"cats"}' },
        },
      },
      { event: "content_block_stop", data: { type: "content_block_stop", index: 1 } },
      {
        event: "message_delta",
        data: {
          type: "message_delta",
          delta: { stop_reason: "tool_use", stop_sequence: null },
          usage: { output_tokens: 42 },
        },
      },
      { event: "message_stop", data: { type: "message_stop" } },
    ]);
    const t = mockTransport(() => new Response(sse, { status: 200 }));
    const deltas: string[] = [];
    const res = await stream("anthropic:claude-test", HI, {
      apiKey: "test-key",
      fetch: t.fetch,
      onDelta: (d) => deltas.push(d),
    });

    assert.equal(t.calls[0].body.stream, true);
    assert.deepEqual(deltas, ["Once", " upon"]);
    assert.equal(res.text, "Once upon");
    assert.deepEqual(res.toolCalls, [{ id: "toolu_1", name: "lookup", arguments: { query: "cats" } }]);
    assert.deepEqual(res.usage, { input_tokens: 25, output_tokens: 42 });
    assert.equal(res.stop, "tool_calls");
    assert.equal(res.model, "claude-test");
  });

  it("rejects with ConnectorError on a mid-stream error event", async () => {
    const sse = anthropicSse([
      {
        event: "message_start",
        data: {
          type: "message_start",
          message: { model: "claude-test", usage: { input_tokens: 5 } },
        },
      },
      {
        event: "content_block_delta",
        data: {
          type: "content_block_delta",
          index: 0,
          delta: { type: "text_delta", text: "part" },
        },
      },
      {
        event: "error",
        data: { type: "error", error: { type: "overloaded_error", message: "Overloaded" } },
      },
    ]);
    const t = mockTransport(() => new Response(sse, { status: 200 }));
    await assert.rejects(
      stream("anthropic:claude-test", HI, { apiKey: "test-key", fetch: t.fetch }),
      (err: unknown) => {
        assert.ok(err instanceof ConnectorError);
        assert.equal(err.provider, "anthropic");
        assert.equal(err.errorType, "overloaded_error");
        assert.match(err.message, /Overloaded/);
        return true;
      },
    );
  });
});

// ---------------------------------------------------------------------------
// 8. Review fixes (regression)
// ---------------------------------------------------------------------------

describe("review fixes", () => {
  it("OpenAI mid-stream error chunk rejects with ConnectorError", async () => {
    const sse =
      `data: ${JSON.stringify({ error: { message: "The server had an error", type: "server_error" } })}\n\n` +
      "data: [DONE]\n\n";
    const t = mockTransport(() => new Response(sse, { status: 200 }));
    await assert.rejects(
      stream("openai:gpt-test", HI, { apiKey: "test-key", fetch: t.fetch }),
      (err: unknown) => {
        assert.ok(err instanceof ConnectorError);
        assert.equal(err.provider, "openai");
        assert.equal(err.errorType, "server_error");
        return true;
      },
    );
  });

  it("SSE parser keeps a final line without a trailing newline", async () => {
    // Truncated stream: usage chunk arrives with no trailing newline, no [DONE].
    const sse =
      `data: ${JSON.stringify({ choices: [{ index: 0, delta: { content: "hi" }, finish_reason: "stop" }] })}\n\n` +
      `data: ${JSON.stringify({ choices: [], usage: { prompt_tokens: 12, completion_tokens: 34 } })}`;
    const t = mockTransport(() => new Response(sse, { status: 200 }));
    const res = await stream("openai:gpt-test", HI, { apiKey: "test-key", fetch: t.fetch });
    assert.equal(res.text, "hi");
    assert.deepEqual(res.usage, { input_tokens: 12, output_tokens: 34 });
  });

  it("prepends a user turn when an Anthropic conversation starts with assistant", async () => {
    const t = mockTransport(ANTHROPIC_OK);
    await chat(
      "anthropic:claude-test",
      [
        { role: "assistant", content: "How can I help?" },
        { role: "user", content: "hello" },
      ],
      { apiKey: "test-key", fetch: t.fetch },
    );
    const msgs = t.calls[0].body.messages;
    assert.equal(msgs[0].role, "user");
    assert.deepEqual(msgs[0].content, [{ type: "text", text: "(continue)" }]);
    assert.equal(msgs[1].role, "assistant");
  });

  it("filters empty text parts from Anthropic array content", async () => {
    const t = mockTransport(ANTHROPIC_OK);
    await chat(
      "anthropic:claude-test",
      [
        {
          role: "user",
          content: [
            { type: "text", text: "  " },
            { type: "image_url", image_url: { url: "https://x/cat.jpg" } },
          ],
        },
      ],
      { apiKey: "test-key", fetch: t.fetch },
    );
    const content = t.calls[0].body.messages[0].content;
    assert.deepEqual(content, [{ type: "image", source: { type: "url", url: "https://x/cat.jpg" } }]);
  });

  it("aborts promptly during retry backoff", async () => {
    const t = mockTransport(
      jsonRes(429, { type: "error", error: { type: "rate_limit_error", message: "slow down" } }, {
        "retry-after": "60",
      }),
    );
    const controller = new AbortController();
    const started = Date.now();
    const pending = assert.rejects(
      chat("anthropic:claude-test", HI, {
        apiKey: "test-key",
        fetch: t.fetch,
        signal: controller.signal,
      }),
      (err: unknown) => {
        assert.ok(err instanceof Error);
        assert.equal(err.name, "AbortError");
        return true;
      },
    );
    setTimeout(() => controller.abort(), 20);
    await pending;
    assert.ok(Date.now() - started < 5000, "abort should not wait out the 60s retry-after");
  });
});

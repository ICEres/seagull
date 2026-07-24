// Minimal zero-dependency connector for OpenAI GPT and Anthropic Claude.
// Spec: docs/minimal-connector.md — OpenAI-style messages in, normalized result out.

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type Role = "system" | "user" | "assistant" | "tool";

export interface TextPart {
  type: "text";
  text: string;
}
export interface ImagePart {
  type: "image_url";
  image_url: { url: string };
}
export type ContentPart = TextPart | ImagePart;

/** Normalized tool call: `arguments` is always a parsed object. */
export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface Message {
  role: Role;
  content: string | ContentPart[] | null;
  tool_calls?: ToolCall[]; // on assistant messages
  tool_call_id?: string; // on role:"tool" messages
}

export interface ToolDef {
  name: string;
  description?: string;
  parameters: Record<string, unknown>; // JSON Schema
}

export type ToolChoice = "auto" | "none" | "required" | { name: string };

export interface ChatOptions {
  maxTokens?: number; // default 4096 (Anthropic requires one)
  temperature?: number;
  stop?: string[];
  tools?: ToolDef[];
  toolChoice?: ToolChoice;
  apiKey?: string; // overrides env var
  baseUrl?: string; // overrides provider default
  maxRetries?: number; // extra attempts after the first; default 2 (= 3 total)
  signal?: AbortSignal;
  /** Provider-specific fields merged into the request body verbatim. */
  extra?: Record<string, unknown>;
  /** Injectable transport, for tests. */
  fetch?: typeof globalThis.fetch;
}

export type StopReason = "stop" | "length" | "tool_calls" | "refusal" | "other";

export interface ChatUsage {
  input_tokens: number;
  output_tokens: number;
}

export interface ChatResult {
  text: string;
  stop: StopReason;
  toolCalls: ToolCall[];
  usage: ChatUsage;
  model: string;
  raw: unknown;
}

export class ConnectorError extends Error {
  provider: Provider;
  status?: number;
  errorType?: string;
  requestId?: string;
  retryAfterMs?: number;

  constructor(
    message: string,
    info: {
      provider: Provider;
      status?: number;
      errorType?: string;
      requestId?: string;
      retryAfterMs?: number;
    },
  ) {
    super(message);
    this.name = "ConnectorError";
    this.provider = info.provider;
    this.status = info.status;
    this.errorType = info.errorType;
    this.requestId = info.requestId;
    this.retryAfterMs = info.retryAfterMs;
  }
}

// ---------------------------------------------------------------------------
// Routing
// ---------------------------------------------------------------------------

export type Provider = "openai" | "anthropic";

const DEFAULTS = {
  openai: { baseUrl: "https://api.openai.com/v1", envKey: "OPENAI_API_KEY" },
  anthropic: { baseUrl: "https://api.anthropic.com/v1", envKey: "ANTHROPIC_API_KEY" },
} as const;

const ANTHROPIC_VERSION = "2023-06-01";
const DEFAULT_MAX_TOKENS = 4096;

export function parseModel(spec: string): { provider: Provider; model: string } {
  const idx = spec.indexOf(":");
  if (idx > 0) {
    const prefix = spec.slice(0, idx);
    const model = spec.slice(idx + 1);
    if (prefix === "openai" || prefix === "anthropic") return { provider: prefix, model };
    throw new Error(`Unknown provider "${prefix}" — use "openai:<model>" or "anthropic:<model>"`);
  }
  // Bare model convenience: infer from the model family.
  if (spec.startsWith("claude-")) return { provider: "anthropic", model: spec };
  if (/^(gpt-|o\d)/.test(spec)) return { provider: "openai", model: spec };
  throw new Error(`Cannot infer provider from model "${spec}" — use "openai:…" or "anthropic:…"`);
}

function apiKey(provider: Provider, opts: ChatOptions): string {
  const key = opts.apiKey ?? process.env[DEFAULTS[provider].envKey];
  if (!key) {
    throw new Error(`Missing API key: set ${DEFAULTS[provider].envKey} or pass opts.apiKey`);
  }
  return key;
}

// Newest Claude models reject sampling params (temperature/top_p/top_k → 400).
const CLAUDE_NO_SAMPLING = /^claude-(opus-4-[78]|sonnet-5|fable-5|mythos-5)/;

// ---------------------------------------------------------------------------
// Request translation — OpenAI
// ---------------------------------------------------------------------------

type Json = Record<string, unknown>;

function toOpenAIMessages(messages: Message[]): Json[] {
  return messages.map((m) => {
    if (m.role === "tool") {
      return { role: "tool", tool_call_id: m.tool_call_id, content: contentToString(m.content) };
    }
    const out: Json = { role: m.role, content: m.content };
    if (m.role === "assistant" && m.tool_calls?.length) {
      out.tool_calls = m.tool_calls.map((c) => ({
        id: c.id,
        type: "function",
        function: { name: c.name, arguments: JSON.stringify(c.arguments) },
      }));
      if (m.content === null || m.content === "") out.content = null;
    }
    return out;
  });
}

function buildOpenAIBody(model: string, messages: Message[], opts: ChatOptions): Json {
  const body: Json = {
    model,
    messages: toOpenAIMessages(messages),
    max_completion_tokens: opts.maxTokens ?? DEFAULT_MAX_TOKENS,
  };
  if (opts.temperature !== undefined) body.temperature = opts.temperature;
  if (opts.stop?.length) body.stop = opts.stop;
  if (opts.tools?.length) {
    body.tools = opts.tools.map((t) => ({
      type: "function",
      function: { name: t.name, description: t.description, parameters: t.parameters },
    }));
    if (opts.toolChoice !== undefined) {
      body.tool_choice =
        typeof opts.toolChoice === "string"
          ? opts.toolChoice
          : { type: "function", function: { name: opts.toolChoice.name } };
    }
  }
  return { ...body, ...opts.extra };
}

// ---------------------------------------------------------------------------
// Request translation — Anthropic
// ---------------------------------------------------------------------------

function contentToString(content: Message["content"]): string {
  if (content === null) return "";
  if (typeof content === "string") return content;
  return content
    .filter((p): p is TextPart => p.type === "text")
    .map((p) => p.text)
    .join("\n");
}

function toAnthropicContentParts(content: string | ContentPart[]): unknown {
  if (typeof content === "string") return content;
  return content.map((p) => {
    if (p.type === "text") return { type: "text", text: p.text };
    const url = p.image_url.url;
    const dataUri = /^data:(?<mime>[^;]+);base64,(?<data>.*)$/s.exec(url);
    if (dataUri?.groups) {
      return {
        type: "image",
        source: { type: "base64", media_type: dataUri.groups.mime, data: dataUri.groups.data },
      };
    }
    return { type: "image", source: { type: "url", url } };
  });
}

function toAnthropicMessages(messages: Message[]): { system: string | undefined; out: Json[] } {
  const systemParts: string[] = [];
  const out: Json[] = [];

  const pushBlocks = (role: "user" | "assistant", blocks: unknown[]) => {
    const last = out[out.length - 1];
    // Parallel tool results must land in ONE user message; merging consecutive
    // same-role messages also satisfies Anthropic's turn rules.
    if (last && last.role === role && Array.isArray(last.content)) {
      (last.content as unknown[]).push(...blocks);
    } else {
      out.push({ role, content: blocks });
    }
  };

  for (const m of messages) {
    if (m.role === "system") {
      systemParts.push(contentToString(m.content));
      continue;
    }
    if (m.role === "tool") {
      pushBlocks("user", [
        { type: "tool_result", tool_use_id: m.tool_call_id, content: contentToString(m.content) },
      ]);
      continue;
    }
    if (m.role === "assistant" && m.tool_calls?.length) {
      const blocks: unknown[] = [];
      const text = contentToString(m.content);
      if (text) blocks.push({ type: "text", text });
      for (const c of m.tool_calls) {
        blocks.push({ type: "tool_use", id: c.id, name: c.name, input: c.arguments });
      }
      pushBlocks("assistant", blocks);
      continue;
    }
    if (m.content === null || m.content === "") continue;
    // Anthropic rejects empty/whitespace-only text blocks — filter them out.
    const blocks = (
      typeof m.content === "string"
        ? [{ type: "text", text: m.content }]
        : (toAnthropicContentParts(m.content) as unknown[])
    ).filter((b: any) => b.type !== "text" || (typeof b.text === "string" && b.text.trim() !== ""));
    if (!blocks.length) continue;
    pushBlocks(m.role, blocks);
  }

  // Anthropic requires the first message to be a user turn (and a non-empty array).
  if (!out.length || out[0].role !== "user") {
    out.unshift({ role: "user", content: [{ type: "text", text: "(continue)" }] });
  }

  return { system: systemParts.length ? systemParts.join("\n\n") : undefined, out };
}

function buildAnthropicBody(model: string, messages: Message[], opts: ChatOptions): Json {
  const { system, out } = toAnthropicMessages(messages);
  const body: Json = {
    model,
    messages: out,
    max_tokens: opts.maxTokens ?? DEFAULT_MAX_TOKENS, // required by the API
  };
  if (system !== undefined) body.system = system;
  if (opts.temperature !== undefined && !CLAUDE_NO_SAMPLING.test(model)) {
    body.temperature = Math.max(0, Math.min(1, opts.temperature)); // Anthropic range is 0–1
  }
  if (opts.stop?.length) body.stop_sequences = opts.stop;
  if (opts.tools?.length) {
    body.tools = opts.tools.map((t) => ({
      name: t.name,
      description: t.description,
      input_schema: t.parameters,
    }));
    if (opts.toolChoice !== undefined) {
      const tc = opts.toolChoice;
      body.tool_choice =
        tc === "auto" || tc === "none"
          ? { type: tc }
          : tc === "required"
            ? { type: "any" }
            : { type: "tool", name: tc.name };
    }
  }
  return { ...body, ...opts.extra };
}

// ---------------------------------------------------------------------------
// Response normalization
// ---------------------------------------------------------------------------

const OPENAI_STOP: Record<string, StopReason> = {
  stop: "stop",
  length: "length",
  tool_calls: "tool_calls",
  function_call: "tool_calls",
  content_filter: "refusal",
};

const ANTHROPIC_STOP: Record<string, StopReason> = {
  end_turn: "stop",
  stop_sequence: "stop",
  max_tokens: "length",
  model_context_window_exceeded: "length",
  tool_use: "tool_calls",
  refusal: "refusal",
};

function normalizeOpenAI(raw: any): ChatResult {
  const msg = raw.choices?.[0]?.message ?? {};
  const toolCalls: ToolCall[] = (msg.tool_calls ?? []).map((c: any) => ({
    id: c.id,
    name: c.function?.name,
    arguments: safeParse(c.function?.arguments),
  }));
  return {
    text: msg.content ?? "",
    stop: OPENAI_STOP[raw.choices?.[0]?.finish_reason] ?? "other",
    toolCalls,
    usage: {
      input_tokens: raw.usage?.prompt_tokens ?? 0,
      output_tokens: raw.usage?.completion_tokens ?? 0,
    },
    model: raw.model ?? "",
    raw,
  };
}

function normalizeAnthropic(raw: any): ChatResult {
  const blocks: any[] = raw.content ?? [];
  return {
    text: blocks
      .filter((b) => b.type === "text")
      .map((b) => b.text)
      .join(""),
    stop: ANTHROPIC_STOP[raw.stop_reason] ?? "other",
    toolCalls: blocks
      .filter((b) => b.type === "tool_use")
      .map((b) => ({ id: b.id, name: b.name, arguments: b.input ?? {} })),
    usage: {
      input_tokens: raw.usage?.input_tokens ?? 0,
      output_tokens: raw.usage?.output_tokens ?? 0,
    },
    model: raw.model ?? "",
    raw,
  };
}

function safeParse(s: unknown): Record<string, unknown> {
  if (typeof s !== "string" || s === "") return {};
  try {
    return JSON.parse(s);
  } catch {
    return {};
  }
}

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------

interface Endpoint {
  url: string;
  headers: Record<string, string>;
  body: Json;
}

function endpoint(spec: string, messages: Message[], opts: ChatOptions): { provider: Provider } & Endpoint {
  const { provider, model } = parseModel(spec);
  const base = opts.baseUrl ?? DEFAULTS[provider].baseUrl;
  const key = apiKey(provider, opts);
  if (provider === "openai") {
    return {
      provider,
      url: `${base}/chat/completions`,
      headers: { authorization: `Bearer ${key}`, "content-type": "application/json" },
      body: buildOpenAIBody(model, messages, opts),
    };
  }
  return {
    provider,
    url: `${base}/messages`,
    headers: {
      "x-api-key": key,
      "anthropic-version": ANTHROPIC_VERSION,
      "content-type": "application/json",
    },
    body: buildAnthropicBody(model, messages, opts),
  };
}

async function throwHttpError(provider: Provider, res: Response): Promise<never> {
  let type: string | undefined;
  let message = `${provider} HTTP ${res.status}`;
  let requestId = res.headers.get("request-id") ?? res.headers.get("x-request-id") ?? undefined;
  try {
    const body: any = await res.json();
    const err = body?.error ?? {};
    type = err.type ?? err.code ?? undefined;
    if (err.message) message = `${message}: ${err.message}`;
    requestId = body?.request_id ?? requestId;
  } catch {
    // non-JSON error body — keep the status-only message
  }
  throw new ConnectorError(message, {
    provider,
    status: res.status,
    errorType: type,
    requestId,
    retryAfterMs: parseRetryAfter(res.headers.get("retry-after")),
  });
}

function parseRetryAfter(value: string | null): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds)) return Math.max(0, seconds * 1000);
  const date = Date.parse(value); // retry-after can also be an HTTP date
  return Number.isNaN(date) ? undefined : Math.max(0, date - Date.now());
}

// ---------------------------------------------------------------------------
// chat()
// ---------------------------------------------------------------------------

export async function chat(
  model: string,
  messages: Message[],
  opts: ChatOptions = {},
): Promise<ChatResult> {
  const ep = endpoint(model, messages, opts);
  const res = await requestWithRetry(ep, opts);
  const raw = await res.json();
  return ep.provider === "openai" ? normalizeOpenAI(raw) : normalizeAnthropic(raw);
}

// ---------------------------------------------------------------------------
// Streaming — SSE on both sides; onDelta receives text chunks, the returned
// promise resolves to the same normalized ChatResult as chat().
// ---------------------------------------------------------------------------

export interface StreamOptions extends ChatOptions {
  onDelta?: (text: string) => void;
}

interface SseEvent {
  event: string | undefined;
  data: string;
}

/** Parse a text/event-stream body into events (handles \n and \r\n framing). */
async function* sseEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const decoder = new TextDecoder();
  let buf = "";
  let event: string | undefined;
  let data: string[] = [];

  const flush = function* (): Generator<SseEvent> {
    if (data.length) yield { event, data: data.join("\n") };
    event = undefined;
    data = [];
  };

  const feedLine = function* (raw: string): Generator<SseEvent> {
    const line = raw.replace(/\r$/, "");
    if (line === "") {
      yield* flush();
    } else if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      data.push(line.slice(5).replace(/^ /, ""));
    }
    // comments (":...") and other fields are ignored
  };

  for await (const chunk of body as unknown as AsyncIterable<Uint8Array>) {
    buf += decoder.decode(chunk, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf("\n")) !== -1) {
      const line = buf.slice(0, nl);
      buf = buf.slice(nl + 1);
      yield* feedLine(line);
    }
  }
  // A truncated stream can end without a trailing newline — don't drop that line.
  buf += decoder.decode();
  if (buf !== "") yield* feedLine(buf);
  yield* flush();
}

export async function stream(
  model: string,
  messages: Message[],
  opts: StreamOptions = {},
): Promise<ChatResult> {
  const ep = endpoint(model, messages, opts);
  ep.body.stream = true;
  if (ep.provider === "openai") ep.body.stream_options = { include_usage: true };

  const res = await requestWithRetry(ep, opts);
  if (!res.body) throw new ConnectorError("empty stream body", { provider: ep.provider });

  return ep.provider === "openai"
    ? consumeOpenAIStream(res.body, opts)
    : consumeAnthropicStream(res.body, opts);
}

async function consumeOpenAIStream(
  body: ReadableStream<Uint8Array>,
  opts: StreamOptions,
): Promise<ChatResult> {
  let text = "";
  let finish: string | undefined;
  let model = "";
  let usage: ChatUsage = { input_tokens: 0, output_tokens: 0 };
  // Tool-call arguments arrive as string fragments keyed by index.
  const calls = new Map<number, { id: string; name: string; args: string }>();
  const events: unknown[] = [];

  for await (const ev of sseEvents(body)) {
    if (ev.data === "[DONE]") break;
    const chunk: any = JSON.parse(ev.data);
    events.push(chunk);
    if (chunk.error) {
      throw new ConnectorError(`openai stream error: ${chunk.error.message ?? "unknown"}`, {
        provider: "openai",
        errorType: chunk.error.type ?? chunk.error.code,
      });
    }
    if (chunk.model) model = chunk.model;
    if (chunk.usage) {
      usage = {
        input_tokens: chunk.usage.prompt_tokens ?? 0,
        output_tokens: chunk.usage.completion_tokens ?? 0,
      };
    }
    const choice = chunk.choices?.[0];
    if (!choice) continue;
    if (choice.finish_reason) finish = choice.finish_reason;
    const delta = choice.delta ?? {};
    if (typeof delta.content === "string" && delta.content !== "") {
      text += delta.content;
      opts.onDelta?.(delta.content);
    }
    for (const tc of delta.tool_calls ?? []) {
      const slot = calls.get(tc.index) ?? { id: "", name: "", args: "" };
      if (tc.id) slot.id = tc.id;
      if (tc.function?.name) slot.name = tc.function.name;
      if (tc.function?.arguments) slot.args += tc.function.arguments;
      calls.set(tc.index, slot);
    }
  }

  return {
    text,
    stop: OPENAI_STOP[finish ?? ""] ?? "other",
    toolCalls: [...calls.values()].map((c) => ({
      id: c.id,
      name: c.name,
      arguments: safeParse(c.args),
    })),
    usage,
    model,
    raw: events,
  };
}

async function consumeAnthropicStream(
  body: ReadableStream<Uint8Array>,
  opts: StreamOptions,
): Promise<ChatResult> {
  let text = "";
  let stopReason: string | undefined;
  let model = "";
  const usage: ChatUsage = { input_tokens: 0, output_tokens: 0 };
  const blocks = new Map<number, { id: string; name: string; json: string }>();
  const events: unknown[] = [];

  for await (const ev of sseEvents(body)) {
    const e: any = JSON.parse(ev.data);
    events.push(e);
    switch (e.type) {
      case "message_start":
        model = e.message?.model ?? "";
        usage.input_tokens = e.message?.usage?.input_tokens ?? 0;
        break;
      case "content_block_start":
        if (e.content_block?.type === "tool_use") {
          blocks.set(e.index, { id: e.content_block.id, name: e.content_block.name, json: "" });
        }
        break;
      case "content_block_delta":
        if (e.delta?.type === "text_delta") {
          text += e.delta.text;
          opts.onDelta?.(e.delta.text);
        } else if (e.delta?.type === "input_json_delta") {
          const slot = blocks.get(e.index);
          if (slot) slot.json += e.delta.partial_json;
        }
        break;
      case "message_delta":
        if (e.delta?.stop_reason) stopReason = e.delta.stop_reason;
        if (e.usage?.output_tokens !== undefined) usage.output_tokens = e.usage.output_tokens;
        break;
      case "error":
        throw new ConnectorError(`anthropic stream error: ${e.error?.message ?? "unknown"}`, {
          provider: "anthropic",
          errorType: e.error?.type,
        });
    }
    if (e.type === "message_stop") break;
  }

  return {
    text,
    stop: ANTHROPIC_STOP[stopReason ?? ""] ?? "other",
    toolCalls: [...blocks.values()].map((b) => ({
      id: b.id,
      name: b.name,
      arguments: safeParse(b.json || "{}"),
    })),
    usage,
    model,
    raw: events,
  };
}

// ---------------------------------------------------------------------------
// Retry — 429/5xx/network up to `maxRetries` extra attempts (default 2, i.e. 3
// total), exponential backoff with jitter, honoring retry-after when present.
// ---------------------------------------------------------------------------

const DEFAULT_MAX_RETRIES = 2;
const BACKOFF_BASE_MS = 1000;
const BACKOFF_CAP_MS = 60_000;

function isRetryable(e: unknown): boolean {
  if (e instanceof ConnectorError) {
    if (e.status === undefined) return false;
    // OpenAI reports exhausted quota as a 429; retrying it is pointless.
    if (e.status === 429 && e.errorType === "insufficient_quota") return false;
    return e.status === 408 || e.status === 409 || e.status === 429 || e.status >= 500;
  }
  // fetch() rejection = network failure — retryable unless it was an abort.
  return e instanceof Error && e.name !== "AbortError";
}

function backoffMs(attempt: number, retryAfterMs?: number): number {
  if (retryAfterMs !== undefined) return Math.min(BACKOFF_CAP_MS, retryAfterMs);
  const exp = BACKOFF_BASE_MS * 2 ** attempt;
  return Math.min(BACKOFF_CAP_MS, exp * (0.5 + Math.random() * 0.5));
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      reject(new DOMException("This operation was aborted", "AbortError"));
    };
    if (signal?.aborted) return abort();
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", abort, { once: true });
  });
}

async function requestWithRetry(
  ep: { provider: Provider } & Endpoint,
  opts: ChatOptions,
): Promise<Response> {
  const doFetch = opts.fetch ?? globalThis.fetch;
  const maxRetries = opts.maxRetries ?? DEFAULT_MAX_RETRIES;

  for (let attempt = 0; ; attempt++) {
    try {
      const res = await doFetch(ep.url, {
        method: "POST",
        headers: ep.headers,
        body: JSON.stringify(ep.body),
        signal: opts.signal,
      });
      if (!res.ok) await throwHttpError(ep.provider, res);
      return res;
    } catch (e) {
      if (attempt >= maxRetries || opts.signal?.aborted || !isRetryable(e)) throw e;
      const retryAfterMs = e instanceof ConnectorError ? e.retryAfterMs : undefined;
      await sleep(backoffMs(attempt, retryAfterMs), opts.signal);
    }
  }
}

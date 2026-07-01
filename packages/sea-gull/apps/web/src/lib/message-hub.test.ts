import { afterEach, describe, expect, it, vi } from "vitest";

import { configuredMessageApiUrl, MessageHubClient, MessageHubError } from "./message-hub";

afterEach(() => {
  window.SEAGULL_CONFIG = undefined;
  vi.restoreAllMocks();
});

describe("message hub client", () => {
  it("reads runtime message API config", () => {
    window.SEAGULL_CONFIG = {
      socialApiUrl: "https://social.example.test",
      messageApiUrl: "https://message.example.test/",
      auth: { mode: "local" },
    };

    expect(configuredMessageApiUrl()).toBe("https://message.example.test");
  });

  it("submits lifecycle hook and decision requests", async () => {
    const calls: Array<{ path: string; body: unknown }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input));
        const body = init?.body ? JSON.parse(String(init.body)) : undefined;
        calls.push({ path: url.pathname, body });
        return new Response(JSON.stringify({ delivery: { delivery_id: "delivery_1", status: "replied" } }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }),
    );

    const client = new MessageHubClient("https://message.example.test/");
    await client.submitHookResult("delivery_1", {
      hook: "receive.before",
      runtime: "cloud_node",
      content: "Prepared",
    });
    await client.submitDecision("delivery_1", {
      agent_handle: "@agent:seagull.local",
      decision: "reply",
      content: "Done",
    });
    await client.explainContact("delivery_1");

    expect(calls).toEqual([
      {
        path: "/deliveries/delivery_1/hook-results",
        body: { hook: "receive.before", runtime: "cloud_node", content: "Prepared" },
      },
      {
        path: "/deliveries/delivery_1/decision",
        body: { agent_handle: "@agent:seagull.local", decision: "reply", content: "Done" },
      },
      {
        path: "/deliveries/delivery_1/contact-explanation",
        body: undefined,
      },
    ]);
  });

  it("submits payload refs without inline message content", async () => {
    const calls: Array<{ path: string; search: string; body: unknown }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input));
        const body = init?.body ? JSON.parse(String(init.body)) : undefined;
        calls.push({ path: url.pathname, search: url.search, body });
        const responseBody = url.pathname === "/payloads"
          ? {
              content_ref: "payload://payload_1",
              payload: {
                content_ref: "payload://payload_1",
                media_type: "text/markdown",
                byte_length: 9000,
                hash: "sha256:plain",
                compression: "gzip",
                compressed_byte_length: 3000,
                compressed_hash: "sha256:gzip",
                retention_state: "ready",
                access_scope: "thread",
                storage_provider: "local_node",
                storage_ref: "payload://payload_1",
                created_at: "2026-06-28T00:00:00+00:00",
              },
            }
          : { message: { message_id: "message_1", content_ref: "payload://payload_1" }, deliveries: [] };
        return new Response(JSON.stringify(responseBody), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }),
    );

    const client = new MessageHubClient("https://message.example.test/");
    const payload = await client.createPayload({
      content: "large",
      media_type: "text/markdown",
      access_scope: "thread",
    });
    await client.createMessage({
      sender_handle: "@agent:seagull.local",
      recipient_handles: ["@reviewer:seagull.local"],
      content_ref: payload.content_ref,
    });
    await client.readPayload(payload.content_ref);

    expect(calls).toEqual([
      {
        path: "/payloads",
        search: "",
        body: { content: "large", media_type: "text/markdown", access_scope: "thread" },
      },
      {
        path: "/messages",
        search: "",
        body: {
          sender_handle: "@agent:seagull.local",
          recipient_handles: ["@reviewer:seagull.local"],
          content_ref: "payload://payload_1",
        },
      },
      {
        path: "/payloads",
        search: "?content_ref=payload%3A%2F%2Fpayload_1",
        body: undefined,
      },
    ]);
  });

  it("sends bearer auth when configured", async () => {
    let authorization = "";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        authorization = new Headers(init?.headers).get("authorization") ?? "";
        return new Response(JSON.stringify({ ok: true, app: "message-hub", storage: "dynamodb" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }),
    );

    const client = new MessageHubClient("https://message.example.test", "message-token");
    await client.health();

    expect(authorization).toBe("Bearer message-token");
  });

  it("raises typed API errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ error: "bad_request", message: "Nope" }), { status: 400 })),
    );

    const client = new MessageHubClient("https://message.example.test");
    await expect(client.listRoutingRules()).rejects.toMatchObject({
      status: 400,
      code: "bad_request",
      message: "Nope",
    });
  });
});

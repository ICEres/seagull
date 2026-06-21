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

    expect(calls).toEqual([
      {
        path: "/deliveries/delivery_1/hook-results",
        body: { hook: "receive.before", runtime: "cloud_node", content: "Prepared" },
      },
      {
        path: "/deliveries/delivery_1/decision",
        body: { agent_handle: "@agent:seagull.local", decision: "reply", content: "Done" },
      },
    ]);
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

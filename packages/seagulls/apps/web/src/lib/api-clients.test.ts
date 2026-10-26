import { afterEach, describe, expect, it, vi } from "vitest";

import { AiProviderApiError, AiProviderClient } from "./ai-provider";
import { MessageHubClient, MessageHubError } from "./message-hub";
import { SocialApiClient, SocialApiError } from "./api";

describe("API clients", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("rejects invalid JSON responses", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("not-json", { status: 200 }));

    await expect(new SocialApiClient("https://social.example.test").health()).rejects.toMatchObject({
      name: "SocialApiError",
      code: "invalid_json",
      status: 200,
    } satisfies Partial<SocialApiError>);
    await expect(new MessageHubClient("https://message.example.test").health()).rejects.toMatchObject({
      name: "MessageHubError",
      code: "invalid_json",
      status: 200,
    } satisfies Partial<MessageHubError>);
    await expect(new AiProviderClient("https://ai.example.test", "token").health()).rejects.toMatchObject({
      name: "AiProviderApiError",
      code: "invalid_json",
      status: 200,
    } satisfies Partial<AiProviderApiError>);
  });

  it("encodes owner-scoped agent-network reads and sends", async () => {
    const requests: Array<{ url: string; method: string; body: string | null; authorization: string | null }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const headers = new Headers(init?.headers);
      requests.push({
        url: String(input),
        method: init?.method ?? "GET",
        body: typeof init?.body === "string" ? init.body : null,
        authorization: headers.get("authorization"),
      });
      return new Response(JSON.stringify({}), { status: 200 });
    });
    const client = new SocialApiClient("https://social.example.test", "token-1");

    await client.getAgentNetworkInbox("user 1", "@mine:gulls.ai", { limit: 20, cursor: "in box/next" });
    await client.getAgentNetworkSent("user 1", "@mine:gulls.ai", { limit: 100, cursor: "sent/next" });
    await client.getAgentNetworkThread("user 1", "@mine:gulls.ai", "thread/1", { cursor: "older" });
    await client.sendAgentNetworkMessage({
      owner_user_id: "user 1",
      sender_handle: "@mine:gulls.ai",
      recipient_handles: ["@other:gulls.ai"],
      content: "Hello",
      thread_id: "thread/1",
      idempotency_key: "send-1",
    });

    expect(requests.map((request) => request.url)).toEqual([
      "https://social.example.test/agent-network/inbox?owner_user_id=user+1&agent_handle=%40mine%3Agulls.ai&limit=20&cursor=in+box%2Fnext",
      "https://social.example.test/agent-network/sent?owner_user_id=user+1&agent_handle=%40mine%3Agulls.ai&limit=100&cursor=sent%2Fnext",
      "https://social.example.test/agent-network/threads/thread%2F1?owner_user_id=user+1&agent_handle=%40mine%3Agulls.ai&limit=50&cursor=older",
      "https://social.example.test/agent-network/messages",
    ]);
    expect(requests.every((request) => request.authorization === "Bearer token-1")).toBe(true);
    expect(JSON.parse(requests[3].body ?? "{}")).toMatchObject({
      owner_user_id: "user 1",
      sender_handle: "@mine:gulls.ai",
      recipient_handles: ["@other:gulls.ai"],
      thread_id: "thread/1",
      idempotency_key: "send-1",
    });
  });

  it("resolves an exact Gull handle through the Message Hub", async () => {
    const request = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ agent: { handle: "@other:gulls.ai" } }), { status: 200 }),
    );
    await new MessageHubClient("https://hub.example.test", "hub-token").getAgent("@other:gulls.ai");
    expect(request).toHaveBeenCalledWith(
      "https://hub.example.test/agents/%40other%3Agulls.ai",
      expect.objectContaining({ method: "GET" }),
    );
  });
});

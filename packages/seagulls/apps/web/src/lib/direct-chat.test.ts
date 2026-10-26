import { beforeEach, describe, expect, it } from "vitest";

import {
  collectDirectConversations,
  loadDirectNetwork,
  readDirectAttempts,
  writeDirectAttempts,
  type DirectNetworkSnapshot,
} from "./direct-chat";
import type { HubDelivery, HubMessage } from "./message-hub";

const message = (overrides: Partial<HubMessage>): HubMessage => ({
  message_id: "m-1",
  thread_id: "t-1",
  sender_agent_id: "a-1",
  sender_handle: "@mine:gulls.ai",
  recipient_handles: ["@other:gulls.ai"],
  intent: "direct",
  visibility: "direct",
  content_inline: "hello",
  schema_version: "1",
  safety_status: "ok",
  created_at: "2026-10-27T00:00:00Z",
  ...overrides,
});

const delivery = (id: string, messageId: string): HubDelivery => ({
  delivery_id: id,
  message_id: messageId,
  thread_id: "t-1",
  sender_agent_id: "a-1",
  recipient_agent_id: "a-2",
  status: "delivered",
  retry_count: 0,
  created_at: "2026-10-27T00:00:00Z",
  updated_at: "2026-10-27T00:00:00Z",
});

describe("direct chat helpers", () => {
  beforeEach(() => window.localStorage.clear());

  it("loads all inbox and sent pages, merging duplicate messages and deliveries", async () => {
    const calls: Array<{ route: string; cursor?: string }> = [];
    const api = {
      getAgentNetworkInbox: async (_owner: string, _handle: string, options: { cursor?: string }) => {
        calls.push({ route: "inbox", cursor: options.cursor });
        return options.cursor
          ? { items: [{ message: message({ message_id: "m-2" }), delivery: delivery("d-2", "m-2") }], next_cursor: null }
          : { items: [{ message: message({ message_id: "m-1" }), delivery: delivery("d-1", "m-1") }], next_cursor: "inbox-2" };
      },
      getAgentNetworkSent: async (_owner: string, _handle: string, options: { cursor?: string }) => {
        calls.push({ route: "sent", cursor: options.cursor });
        return options.cursor
          ? { messages: [message({ message_id: "m-3" })], deliveries: [delivery("d-3", "m-3")], next_cursor: null }
          : { messages: [message({ message_id: "m-1" })], deliveries: [delivery("d-1", "m-1")], next_cursor: "sent-2" };
      },
    };

    const snapshot = await loadDirectNetwork(api, "owner-1", "@mine:gulls.ai");
    expect(calls).toEqual([
      { route: "inbox" },
      { route: "inbox", cursor: "inbox-2" },
      { route: "sent" },
      { route: "sent", cursor: "sent-2" },
    ]);
    expect(snapshot.messages.map((item) => item.message_id)).toEqual(["m-1", "m-2", "m-3"]);
    expect(snapshot.deliveries.map((item) => item.delivery_id)).toEqual(["d-1", "d-2", "d-3"]);
    expect(snapshot.historyLoaded).toBe(true);
  });

  it("stops a refresh after the first known newest-page record", async () => {
    const calls: string[] = [];
    const previous: DirectNetworkSnapshot = {
      messages: [message({ message_id: "known" })],
      deliveries: [delivery("known-delivery", "known")],
      historyLoaded: true,
    };
    const api = {
      getAgentNetworkInbox: async (_owner: string, _handle: string, options: { cursor?: string }) => {
        calls.push(`inbox:${options.cursor ?? "head"}`);
        return {
          items: [
            { message: message({ message_id: "new" }), delivery: delivery("new-delivery", "new") },
            { message: message({ message_id: "known" }), delivery: delivery("known-delivery", "known") },
          ],
          next_cursor: "older-that-should-not-load",
        };
      },
      getAgentNetworkSent: async (_owner: string, _handle: string, options: { cursor?: string }) => {
        calls.push(`sent:${options.cursor ?? "head"}`);
        return { messages: [message({ message_id: "known" })], deliveries: [], next_cursor: "older" };
      },
    };

    const snapshot = await loadDirectNetwork(api, "owner-1", "@mine:gulls.ai", previous);
    expect(calls).toEqual(["inbox:head", "sent:head"]);
    expect(snapshot.messages.map((item) => item.message_id)).toEqual(["known", "new"]);
  });

  it("loads older pages when a send populated the cache before history loaded", async () => {
    const calls: string[] = [];
    const previous: DirectNetworkSnapshot = {
      messages: [message({ message_id: "just-sent" })],
      deliveries: [delivery("just-delivered", "just-sent")],
      historyLoaded: false,
    };
    const api = {
      getAgentNetworkInbox: async (_owner: string, _handle: string, options: { cursor?: string }) => {
        calls.push(`inbox:${options.cursor ?? "head"}`);
        return options.cursor
          ? { items: [{ message: message({ message_id: "older-inbox" }), delivery: delivery("older-delivery", "older-inbox") }], next_cursor: null }
          : { items: [{ message: message({ message_id: "just-sent" }), delivery: delivery("just-delivered", "just-sent") }], next_cursor: "older" };
      },
      getAgentNetworkSent: async (_owner: string, _handle: string, options: { cursor?: string }) => {
        calls.push(`sent:${options.cursor ?? "head"}`);
        return options.cursor
          ? { messages: [message({ message_id: "older-sent" })], next_cursor: null }
          : { messages: [message({ message_id: "just-sent" })], next_cursor: "older" };
      },
    };

    const snapshot = await loadDirectNetwork(api, "owner-1", "@mine:gulls.ai", previous);
    expect(calls).toEqual(["inbox:head", "inbox:older", "sent:head", "sent:older"]);
    expect(snapshot.messages.map((item) => item.message_id)).toEqual(["just-sent", "older-inbox", "older-sent"]);
    expect(snapshot.historyLoaded).toBe(true);
  });

  it("rejects incomplete sent history and cursor loops", async () => {
    const incompleteApi = {
      getAgentNetworkInbox: async () => ({ items: [], next_cursor: null }),
      getAgentNetworkSent: async () => ({ messages: [], truncated: true }),
    };
    await expect(loadDirectNetwork(incompleteApi, "owner-1", "@mine:gulls.ai")).rejects.toThrow(
      "history is incomplete",
    );

    let first = true;
    const loopApi = {
      getAgentNetworkInbox: async (_owner: string, _handle: string, options: { cursor?: string }) => {
        if (!options.cursor) return { items: [], next_cursor: "loop" };
        if (first) {
          first = false;
          return { items: [], next_cursor: "loop" };
        }
        return { items: [], next_cursor: null };
      },
      getAgentNetworkSent: async () => ({ messages: [], next_cursor: null }),
    };
    await expect(loadDirectNetwork(loopApi, "owner-1", "@mine:gulls.ai")).rejects.toThrow(
      "history is incomplete",
    );
  });

  it("keeps only one-to-one direct conversations and excludes private threads", () => {
    const snapshot: DirectNetworkSnapshot = {
      messages: [
        message({ message_id: "old", created_at: "2026-10-27T00:00:00Z", content_inline: "old" }),
        message({ message_id: "new", created_at: "2026-10-27T01:00:00Z", content_inline: "new" }),
        message({ message_id: "in", sender_handle: "@other:gulls.ai", recipient_handles: ["@mine:gulls.ai"], thread_id: "t-2", content_inline: "reply" }),
        message({ message_id: "group", recipient_handles: ["@other:gulls.ai", "@third:gulls.ai"], thread_id: "t-3" }),
        message({ message_id: "post", intent: "post", thread_id: "t-4" }),
        message({ message_id: "private", thread_id: "assistant-1" }),
        message({ message_id: "reply", thread_id: "t-2", intent: "reply", created_at: "2026-10-27T02:00:00Z", content_inline: "reply again" }),
        message({ message_id: "mixed", thread_id: "t-5", content_inline: "one" }),
        message({ message_id: "mixed-group", thread_id: "t-5", recipient_handles: ["@other:gulls.ai", "@third:gulls.ai"] }),
      ],
      deliveries: [],
      historyLoaded: true,
    };

    expect(collectDirectConversations(snapshot, "@mine:gulls.ai", new Set(["assistant-1"]))).toEqual([
      {
        threadId: "t-2",
        senderHandle: "@mine:gulls.ai",
        recipientHandle: "@other:gulls.ai",
        updatedAt: "2026-10-27T02:00:00Z",
        snippet: "reply again",
      },
      {
        threadId: "t-1",
        senderHandle: "@mine:gulls.ai",
        recipientHandle: "@other:gulls.ai",
        updatedAt: "2026-10-27T01:00:00Z",
        snippet: "new",
      },
    ]);
  });

  it("isolates attempts by API and owner and restores sending as unconfirmed", () => {
    writeDirectAttempts("https://api.example.test/", "owner-a", [
      {
        id: "attempt-1",
        senderHandle: "@mine:gulls.ai",
        recipientHandle: "@other:gulls.ai",
        content: "hello",
        createdAt: "2026-10-27T00:00:00Z",
        status: "sending",
      },
    ]);
    writeDirectAttempts("https://api.example.test", "owner-b", []);

    expect(readDirectAttempts("https://api.example.test", "owner-a")[0].status).toBe("unconfirmed");
    expect(readDirectAttempts("https://api.example.test", "owner-b")).toEqual([]);
    expect(readDirectAttempts("https://other.example.test", "owner-a")).toEqual([]);
  });
});

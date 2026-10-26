import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DirectChatThread } from "./direct-chat";
import { SocialApiClient } from "../lib/api";
import { readDirectAttempts } from "../lib/direct-chat";
import type { AgentProfile } from "../lib/social";

function profile(overrides: Partial<AgentProfile> = {}): AgentProfile {
  return {
    agent_id: "agent-scout",
    owner_user_id: "owner-1",
    handle: "@scout:gulls.ai",
    display_name: "Scout",
    bio: null,
    capabilities: [],
    relationship_posture: "needs_approval",
    approval_required_for: [],
    allowed_use_terms: [],
    contact_explanation: null,
    protocols: ["seagull"],
    status: "active",
    node_id: null,
    delivery_mode: "pull",
    last_seen_at: null,
    created_at: "2026-10-27T00:00:00Z",
    updated_at: "2026-10-27T00:00:00Z",
    ...overrides,
  };
}

function responseMessage(overrides: Record<string, unknown> = {}) {
  return {
    message_id: "message-1",
    thread_id: "thread-1",
    sender_agent_id: "agent-scout",
    sender_handle: "@scout:gulls.ai",
    recipient_agent_ids: ["agent-mira"],
    recipient_handles: ["@mira:gulls.ai"],
    intent: "direct",
    visibility: "direct",
    content_inline: "hello",
    content_ref: null,
    refs: [],
    schema_version: "seagull.message.v1",
    safety_status: "approved",
    runtime_mode: "cloud",
    created_at: "2026-10-27T00:00:00Z",
    ...overrides,
  };
}

function renderThread(
  api: SocialApiClient,
  options: Partial<React.ComponentProps<typeof DirectChatThread>> = {},
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <DirectChatThread
          api={api}
          ownerUserId="owner-1"
          profiles={[
            profile(),
            profile({ agent_id: "agent-researcher", handle: "@researcher:gulls.ai", display_name: "Researcher" }),
            profile({ agent_id: "agent-foreign", owner_user_id: "other-owner", handle: "@foreign:gulls.ai", display_name: "Foreign" }),
          ]}
          senderHandle="@scout:gulls.ai"
          recipientHandle="@mira:gulls.ai"
          onSelect={() => {}}
          onNotice={() => {}}
          {...options}
        />
      </QueryClientProvider>,
    );
  });
  return { container, root };
}

function messageBox(container: HTMLElement): HTMLTextAreaElement {
  const textarea = container.querySelector('textarea[aria-label="Message"]');
  if (!(textarea instanceof HTMLTextAreaElement)) throw new Error("message textarea missing");
  return textarea;
}

function setDraft(textarea: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
  setter?.call(textarea, value);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

let roots: Array<{ root: Root; container: HTMLElement }> = [];

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  window.localStorage.clear();
});

afterEach(() => {
  for (const item of roots.splice(0)) {
    act(() => item.root.unmount());
    item.container.remove();
  }
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("DirectChatThread", () => {
  it("restricts the sender picker to owned gulls and locks the sender after the first send", async () => {
    const api = new SocialApiClient("https://social.example.test");
    vi.spyOn(api, "sendAgentNetworkMessage").mockResolvedValue({
      message: responseMessage(),
      message_id: "message-1",
      thread_id: "thread-1",
      deliveries: [],
    });
    const rendered = renderThread(api);
    roots.push(rendered);

    const sender = rendered.container.querySelector('select[aria-label="Send as"]');
    expect(sender).toBeInstanceOf(HTMLSelectElement);
    expect(Array.from((sender as HTMLSelectElement).options).map((option) => option.value)).toEqual([
      "@scout:gulls.ai",
      "@researcher:gulls.ai",
    ]);
    expect(Array.from((sender as HTMLSelectElement).options).some((option) => option.value.includes("mira"))).toBe(false);

    await act(async () => {
      setDraft(messageBox(rendered.container), "hello");
      rendered.container.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
    });
    expect(rendered.container.querySelector('select[aria-label="Send as"]')).toBeNull();
    expect(rendered.container.textContent).toContain("@scout");
  });

  it("reuses one idempotency key and thread id when a send result is uncertain", async () => {
    const api = new SocialApiClient("https://social.example.test");
    vi.spyOn(api, "getAgentNetworkThread").mockResolvedValue({
      thread_id: "thread-1",
      messages: [],
      has_more: false,
    });
    const send = vi.spyOn(api, "sendAgentNetworkMessage");
    send.mockRejectedValueOnce(new Error("network interrupted"));
    send.mockResolvedValueOnce({
      message: responseMessage({ message_id: "message-retried" }),
      message_id: "message-retried",
      thread_id: "thread-1",
      deliveries: [],
    });
    const rendered = renderThread(api, { threadId: "thread-1" });
    roots.push(rendered);

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    await act(async () => {
      setDraft(messageBox(rendered.container), "retry me");
      rendered.container.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    const retry = Array.from(rendered.container.querySelectorAll("button")).find((button) => /retry/i.test(button.textContent ?? ""));
    expect(retry).toBeTruthy();
    await act(async () => retry?.click());

    expect(send).toHaveBeenCalledTimes(2);
    const first = send.mock.calls[0][0];
    const second = send.mock.calls[1][0];
    expect(second.idempotency_key).toBe(first.idempotency_key);
    expect(second.thread_id).toBe("thread-1");
    expect(second.content).toBe("retry me");
  });

  it("renders a returned reply while preserving a newly typed draft", async () => {
    const api = new SocialApiClient("https://social.example.test");
    let resolveSend: ((value: Awaited<ReturnType<SocialApiClient["sendAgentNetworkMessage"]>>) => void) | null = null;
    vi.spyOn(api, "sendAgentNetworkMessage").mockImplementation(
      () => new Promise((resolve) => { resolveSend = resolve; }),
    );
    const rendered = renderThread(api);
    roots.push(rendered);

    await act(async () => {
      setDraft(messageBox(rendered.container), "first");
      rendered.container.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
    });
    await act(async () => setDraft(messageBox(rendered.container), "second draft"));
    await act(async () => resolveSend?.({
      message: responseMessage({ content_inline: "first" }),
      message_id: "message-1",
      thread_id: "thread-1",
      deliveries: [],
    }));

    expect(rendered.container.textContent).toContain("first");
    expect(messageBox(rendered.container).value).toBe("second draft");
  });

  it("locks the returned thread id into the next message", async () => {
    const api = new SocialApiClient("https://social.example.test");
    const send = vi.spyOn(api, "sendAgentNetworkMessage");
    send
      .mockResolvedValueOnce({
        message: responseMessage({ message_id: "message-1" }),
        message_id: "message-1",
        thread_id: "thread-locked",
        deliveries: [],
      })
      .mockResolvedValueOnce({
        message: responseMessage({ message_id: "message-2", content_inline: "second" }),
        message_id: "message-2",
        thread_id: "thread-locked",
        deliveries: [],
      });
    const rendered = renderThread(api);
    roots.push(rendered);

    await act(async () => {
      setDraft(messageBox(rendered.container), "first");
      rendered.container.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
    });
    await act(async () => {
      setDraft(messageBox(rendered.container), "second");
      rendered.container.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
    });

    expect(send).toHaveBeenCalledTimes(2);
    expect(send.mock.calls[1][0].thread_id).toBe("thread-locked");
  });

  it("restores an uncertain first send after a refresh", async () => {
    const api = new SocialApiClient("https://social.example.test");
    vi.spyOn(api, "sendAgentNetworkMessage").mockRejectedValue(new Error("network interrupted"));
    const first = renderThread(api);
    roots.push(first);

    await act(async () => {
      setDraft(messageBox(first.container), "keep after refresh");
      first.container.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(first.container.textContent).toContain("Unconfirmed");

    await act(async () => first.root.unmount());
    first.container.remove();
    roots = roots.filter((item) => item !== first);

    const restored = renderThread(api);
    roots.push(restored);
    expect(restored.container.textContent).toContain("keep after refresh");
    expect(restored.container.textContent).toContain("Unconfirmed");
  });

  it("does not send when the selected sender is not owned by the account", async () => {
    const api = new SocialApiClient("https://social.example.test");
    const send = vi.spyOn(api, "sendAgentNetworkMessage").mockResolvedValue({
      message: responseMessage(),
      message_id: "message-1",
      thread_id: "thread-1",
      deliveries: [],
    });
    const rendered = renderThread(api, { senderHandle: "@foreign:gulls.ai" });
    roots.push(rendered);

    const textarea = messageBox(rendered.container);
    await act(async () => {
      setDraft(textarea, "must not leave this account");
    });
    expect(rendered.container.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled).toBe(true);
    expect(rendered.container.textContent).toContain("Sender unavailable");
    expect(send).not.toHaveBeenCalled();
  });

  it("rejects a thread whose participants do not match the selected Gull pair", async () => {
    const api = new SocialApiClient("https://social.example.test");
    vi.spyOn(api, "getAgentNetworkThread").mockResolvedValue({
      thread_id: "thread-forged",
      has_more: false,
      messages: [responseMessage({
        thread_id: "thread-forged",
        sender_handle: "@someone-else:gulls.ai",
        recipient_handles: ["@another:gulls.ai"],
      })],
    });
    const rendered = renderThread(api, { threadId: "thread-forged" });
    roots.push(rendered);

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(rendered.container.textContent).toContain("Could not open this chat");
    expect(rendered.container.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled).toBe(true);
  });

  it("keeps the new recipient draft when an old recipient send resolves", async () => {
    const api = new SocialApiClient("https://social.example.test");
    let resolveSend: ((value: Awaited<ReturnType<SocialApiClient["sendAgentNetworkMessage"]>>) => void) | null = null;
    vi.spyOn(api, "sendAgentNetworkMessage").mockImplementation(
      () => new Promise((resolve) => { resolveSend = resolve; }),
    );
    const onSelect = vi.fn();
    const rendered = renderThread(api, { onSelect });
    roots.push(rendered);

    await act(async () => {
      setDraft(messageBox(rendered.container), "message for Mira");
      rendered.container.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
    });
    await act(async () => {
      rendered.root.render(
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <DirectChatThread
            api={api}
            ownerUserId="owner-1"
            profiles={[profile(), profile({ agent_id: "agent-researcher", handle: "@researcher:gulls.ai", display_name: "Researcher" })]}
            senderHandle="@scout:gulls.ai"
            recipientHandle="@nova:gulls.ai"
            onSelect={onSelect}
            onNotice={() => {}}
          />
        </QueryClientProvider>,
      );
    });
    await act(async () => setDraft(messageBox(rendered.container), "new Nova draft"));
    await act(async () => resolveSend?.({
      message: responseMessage(),
      message_id: "message-1",
      thread_id: "thread-mira",
      deliveries: [],
    }));

    expect(messageBox(rendered.container).value).toBe("new Nova draft");
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("keeps another recipient's pending attempt when an unmounted send resolves", async () => {
    const api = new SocialApiClient("https://social.example.test");
    type SendResult = Awaited<ReturnType<SocialApiClient["sendAgentNetworkMessage"]>>;
    const pending = {
      mira: {} as { resolve?: (value: SendResult) => void },
      nova: {} as { resolve?: (value: SendResult) => void },
    };
    vi.spyOn(api, "sendAgentNetworkMessage").mockImplementation((request) => new Promise((resolve) => {
      if (request.content === "Mira pending") pending.mira.resolve = resolve;
      else pending.nova.resolve = resolve;
    }));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const first = renderThread(api, {}, queryClient);
    roots.push(first);
    await act(async () => {
      setDraft(messageBox(first.container), "Mira pending");
      first.container.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
    });

    await act(async () => first.root.unmount());
    first.container.remove();
    roots = roots.filter((item) => item !== first);

    const second = renderThread(api, { recipientHandle: "@nova:gulls.ai" }, queryClient);
    roots.push(second);
    await act(async () => {
      setDraft(messageBox(second.container), "Nova pending");
      second.container.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
    });
    expect(readDirectAttempts(api.baseUrl, "owner-1").map((attempt) => attempt.content).sort()).toEqual([
      "Mira pending",
      "Nova pending",
    ]);

    await act(async () => pending.mira.resolve?.({
      message: responseMessage({ content_inline: "Mira pending" }),
      message_id: "message-mira",
      thread_id: "thread-mira",
      deliveries: [],
    }));

    expect(readDirectAttempts(api.baseUrl, "owner-1").map((attempt) => attempt.content)).toEqual(["Nova pending"]);
    pending.nova.resolve?.({ message: responseMessage({ content_inline: "Nova pending" }), message_id: "message-nova", thread_id: "thread-nova", deliveries: [] });
  });
});

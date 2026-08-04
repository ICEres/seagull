import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatPage } from "./chat-page";
import { SocialApiClient } from "../lib/api";
import { emptyLoopState } from "../lib/state";
import type { AgentChatSession, AgentProfile, LoopState } from "../lib/social";

function agent(overrides: Partial<AgentProfile> = {}): AgentProfile {
  return {
    agent_id: "agent_1",
    owner_user_id: "user_1",
    handle: "@researcher:seagull.local",
    display_name: "Researcher",
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
    created_at: "2026-06-13T00:00:00Z",
    updated_at: "2026-06-13T00:00:00Z",
    ...overrides,
  } as AgentProfile;
}

function chat(overrides: Partial<AgentChatSession> = {}): AgentChatSession {
  return {
    chat_id: "chat_a",
    owner_user_id: "user_1",
    agent_id: "agent_1",
    agent_handle: "@researcher:seagull.local",
    title: "Chat with Researcher",
    sender_agent_id: null,
    sender_handle: null,
    prompt_asset_id: null,
    skill_asset_id: null,
    hub_thread_id: null,
    created_at: "2026-06-13T00:00:00Z",
    updated_at: "2026-06-13T00:00:00Z",
    ...overrides,
  };
}

// Built from emptyLoopState so a new LoopState field cannot silently leave
// this fixture incomplete; only what the chat screen reads is overridden.
function loopState(): LoopState {
  return {
    ...emptyLoopState(),
    apiUrl: "https://social.example.test",
    activeUser: {
      user_id: "user_1",
      provider: "local",
      subject: "alice",
      email: "alice@example.com",
      display_name: "Alice",
      created_at: "2026-06-13T00:00:00Z",
      updated_at: "2026-06-13T00:00:00Z",
    },
  };
}

function setNativeValue(element: HTMLTextAreaElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
  if (!setter) {
    throw new Error("Native value setter unavailable.");
  }
  setter.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

async function waitForText(container: HTMLElement, text: string): Promise<void> {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    if (container.textContent?.includes(text)) {
      return;
    }
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
  throw new Error(`Expected to find "${text}" in: ${container.textContent ?? ""}`);
}

async function waitForPlaceholder(container: HTMLElement, placeholder: string): Promise<HTMLTextAreaElement> {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const textarea = container.querySelector('textarea[aria-label="Message"]');
    if (textarea instanceof HTMLTextAreaElement && textarea.placeholder.includes(placeholder)) {
      return textarea;
    }
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
  throw new Error(`Expected a message textarea with placeholder including "${placeholder}".`);
}

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  vi.unstubAllGlobals();
});

describe("ChatPage", () => {
  it("does not clear a chat's draft with a stale send response from another chat", async () => {
    const chatA = chat({ chat_id: "chat_a", agent_handle: "@a:seagull.local", title: "Chat with A" });
    const chatB = chat({ chat_id: "chat_b", agent_handle: "@b:seagull.local", title: "Chat with B" });
    const profiles = [
      agent({ agent_id: "agent_a", handle: "@a:seagull.local", display_name: "A" }),
      agent({ agent_id: "agent_b", handle: "@b:seagull.local", display_name: "B" }),
    ];

    let resolveSend: ((response: Response) => void) | null = null;
    const sendResponse = new Promise<Response>((resolve) => {
      resolveSend = resolve;
    });

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input));
        const key = `${url.pathname}${url.search}`;
        if (init?.method === "POST" && url.pathname === "/agent-chats/chat_a/messages") {
          return sendResponse;
        }
        if (key === "/agent-chats?owner_user_id=user_1") {
          return new Response(JSON.stringify({ items: [chatA, chatB] }), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        }
        if (
          key === "/agent-chats/chat_a/messages?owner_user_id=user_1" ||
          key === "/agent-chats/chat_b/messages?owner_user_id=user_1"
        ) {
          return new Response(JSON.stringify({ items: [] }), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        }
        return new Response(JSON.stringify({ error: "not_found" }), { status: 404 });
      }),
    );

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const api = new SocialApiClient("https://social.example.test");

    await act(async () => {
      root?.render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/chat/chat_a"]}>
            <Routes>
              <Route
                path="/chat/:chatId"
                element={<ChatPage api={api} state={loopState()} profiles={profiles} onNotice={() => {}} />}
              />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>,
      );
    });

    await waitForText(container, "Say hello");

    const textarea = container.querySelector('textarea[aria-label="Message"]');
    if (!(textarea instanceof HTMLTextAreaElement)) {
      throw new Error("Message textarea not found.");
    }

    // Start a send from Chat A. The request is left pending deliberately.
    await act(async () => {
      setNativeValue(textarea, "hello from A");
    });
    await act(async () => {
      textarea.form!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    // Navigate to Chat B while the send from Chat A is still in flight.
    const chatBButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Chat with B"),
    );
    if (!chatBButton) {
      throw new Error("Chat B sidebar entry not found.");
    }
    await act(async () => {
      chatBButton.click();
    });
    const chatBTextarea = await waitForPlaceholder(container, "@b");
    await act(async () => {
      setNativeValue(chatBTextarea, "hello from B");
    });
    expect(chatBTextarea.value).toBe("hello from B");

    // Now let Chat A's send resolve. Its onSuccess must not wipe Chat B's draft.
    await act(async () => {
      resolveSend?.(
        new Response(
          JSON.stringify({
            message: {
              chat_message_id: "chatmsg_a",
              chat_id: "chat_a",
              owner_user_id: "user_1",
              sender_type: "human",
              content: "hello from A",
              hub_message_id: null,
              hub_thread_id: null,
              delivery_status: "delivered",
              delivery_error: null,
              ai_run_id: null,
              ai_run_state: null,
              ai_error: null,
              created_at: "2026-06-13T00:01:00Z",
              updated_at: "2026-06-13T00:01:00Z",
            },
            reply: null,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      );
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });

    const finalTextarea = container.querySelector('textarea[aria-label="Message"]');
    expect(finalTextarea instanceof HTMLTextAreaElement && finalTextarea.value).toBe("hello from B");
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type {
  AgentChatMessage,
  AgentChatSession,
  AgentProfile,
  HumanIdentity,
  ModerationRecord,
  Notification,
  Post,
} from "./lib/social";

const STORAGE_KEY = "seagull.web.phase4.loop";

const identity: HumanIdentity = {
  user_id: "user_1",
  provider: "local",
  subject: "alice",
  email: "alice@example.com",
  display_name: "Alice",
  created_at: "2026-06-13T00:00:00Z",
  updated_at: "2026-06-13T00:00:00Z",
};

const profile: AgentProfile = {
  agent_id: "agent_1",
  owner_user_id: "user_1",
  handle: "@researcher:seagull.local",
  display_name: "Researcher",
  bio: "Research agent",
  capabilities: ["research", "planning"],
  relationship_posture: "needs_approval",
  approval_required_for: ["private_context", "tool_use", "high_cost_work"],
  allowed_use_terms: ["inspect_shared_context"],
  contact_explanation: "Researcher responds to shared planning requests.",
  protocols: ["seagull"],
  status: "active",
  node_id: null,
  delivery_mode: "pull",
  last_seen_at: null,
  created_at: "2026-06-13T00:00:00Z",
  updated_at: "2026-06-13T00:00:00Z",
};

const post: Post = {
  post_id: "post_1",
  author_agent_id: "agent_1",
  content: "Planning the first social loop.",
  text: "Planning the first social loop.",
  refs: [],
  visibility: "public",
  room_id: null,
  reply_to_post_id: null,
  mention_agent_ids: [],
  created_at: "2026-06-13T00:00:10Z",
};

const notification: Notification = {
  notification_id: "notification_1",
  recipient_agent_id: "agent_1",
  notification_type: "mention",
  actor_agent_id: null,
  post_id: "post_1",
  room_id: null,
  read_at: null,
  created_at: "2026-06-13T00:00:11Z",
};

const moderation: ModerationRecord = {
  moderation_id: "moderation_1",
  created_by_user_id: "user_1",
  target_type: "post",
  target_id: "post_1",
  action: "review",
  reason: "Needs human review",
  status: "open",
  created_at: "2026-06-13T00:00:12Z",
  resolved_at: null,
};

const chat: AgentChatSession = {
  chat_id: "chat_1",
  owner_user_id: "user_1",
  agent_id: "agent_1",
  agent_handle: "@researcher:seagull.local",
  title: "Chat with Researcher",
  sender_agent_id: null,
  sender_handle: null,
  prompt_asset_id: "asset_prompt_1",
  skill_asset_id: "asset_skill_1",
  hub_thread_id: null,
  created_at: "2026-06-13T00:00:20Z",
  updated_at: "2026-06-13T00:00:20Z",
};

const chatMessage: AgentChatMessage = {
  chat_message_id: "chatmsg_1",
  chat_id: "chat_1",
  owner_user_id: "user_1",
  sender_type: "human",
  content: "Can you review the landing page plan?",
  hub_message_id: null,
  hub_thread_id: null,
  delivery_status: "stored",
  delivery_error: null,
  ai_run_id: null,
  ai_run_state: null,
  ai_error: null,
  created_at: "2026-06-13T00:00:21Z",
  updated_at: "2026-06-13T00:00:21Z",
};

const chatReply: AgentChatMessage = {
  chat_message_id: "chatmsg_2",
  chat_id: "chat_1",
  owner_user_id: "user_1",
  sender_type: "agent",
  content: "The plan looks solid; tighten the hero copy.",
  hub_message_id: null,
  hub_thread_id: null,
  delivery_status: "stored",
  delivery_error: null,
  ai_run_id: "airun_1",
  ai_run_state: "completed",
  ai_error: null,
  created_at: "2026-06-13T00:00:22Z",
  updated_at: "2026-06-13T00:00:22Z",
};

const inboxResponse = {
  agent: {
    agent_id: "agent_1",
    handle: "@researcher:seagull.local",
    display_name: "Researcher",
    capabilities: [],
    status: "active",
    trigger_mode: "manual",
    webhook_enabled: false,
    created_at: "2026-06-13T00:00:00Z",
    updated_at: "2026-06-13T00:00:00Z",
  },
  items: [
    {
      delivery: {
        delivery_id: "delivery_1",
        message_id: "message_1",
        thread_id: "thread_1",
        sender_agent_id: "agent_sender",
        sender_handle: "@sender:seagull.local",
        recipient_agent_id: "agent_1",
        recipient_handle: "@researcher:seagull.local",
        status: "delivered",
        retry_count: 0,
        current_content_inline: "Prepared map question",
        refs: [{ type: "url", url: "https://maps.google.com/example", find: "identify_place" }],
        workflow_trace: [
          {
            hook: "receive.before",
            runtime: "cloud_node",
            action: "continue",
            changed: ["current_content_inline"],
            created_at: "2026-06-13T00:00:01Z",
          },
        ],
        current_stage: "agent.wait",
        created_at: "2026-06-13T00:00:00Z",
        updated_at: "2026-06-13T00:00:01Z",
      },
      message: {
        message_id: "message_1",
        thread_id: "thread_1",
        sender_agent_id: "agent_sender",
        sender_handle: "@sender:seagull.local",
        recipient_agent_ids: ["agent_1"],
        recipient_handles: ["@researcher:seagull.local"],
        intent: "message",
        visibility: "direct",
        content_inline: "Original map question",
        refs: [],
        schema_version: "seagull.message.v1",
        safety_status: "approved",
        created_at: "2026-06-13T00:00:00Z",
      },
      current_message: {
        content_inline: "Prepared map question",
        refs: [{ type: "url", url: "https://maps.google.com/example", find: "identify_place" }],
      },
    },
  ],
};

const roots: Root[] = [];

afterEach(async () => {
  for (const root of roots.splice(0)) {
    await act(async () => {
      root.unmount();
    });
  }
  document.body.innerHTML = "";
  document.documentElement.classList.remove("dark");
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.SEAGULL_CONFIG = undefined;
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("App", () => {
  it("keeps unauthenticated users on the login sky", async () => {
    window.SEAGULL_CONFIG = { socialApiUrl: "https://api.example.test", auth: { mode: "local" } };
    mockApi({
      "/health": { ok: true, app: "social-api", storage: "memory" },
    });

    const container = renderApp("/");
    await waitForText(container, "Your sky is waiting");

    expect(container.querySelector('input[aria-label="Email"]')).not.toBeNull();
    expect(container.querySelector('input[aria-label="Display name"]')).toBeNull();
    expect(container.querySelector('button[aria-label="Sign in"]')).not.toBeNull();
    expect(container.textContent).toContain("New here? Create your flock");
    expect(container.textContent).not.toContain("The stream");
    expect(container.querySelector('button[aria-label="Sign out"]')).toBeNull();
  });

  it("renders the email-only registration design", async () => {
    window.SEAGULL_CONFIG = { socialApiUrl: "https://api.example.test", auth: { mode: "local" } };
    mockApi({
      "/health": { ok: true, app: "social-api", storage: "memory" },
    });

    const container = renderApp("/register");
    await waitForText(container, "Join the flock");

    expect(container.textContent).toContain("One email — and your gull takes wing.");
    expect(container.querySelector('input[aria-label="Email"]')).not.toBeNull();
    expect(container.querySelector('button[aria-label="Create your flock"]')).not.toBeNull();
    expect(container.textContent).toContain("Already flocked? Sign in");
  });

  it("shows the first-gull call to action on an empty sky", async () => {
    window.SEAGULL_CONFIG = { socialApiUrl: "https://api.example.test", auth: { mode: "local" } };
    saveLoopState({ activeUser: identity });
    mockApi({
      "/health": { ok: true, app: "social-api", storage: "memory" },
      "/profiles?owner_user_id=user_1": { items: [] },
      "/feed?owner_user_id=user_1&limit=50": { items: [] },
      "/moderation?limit=50": { items: [] },
    });

    const container = renderApp("/sky");
    await waitForText(container, "Register your first gull");

    expect(container.textContent).toContain("The stream");
    expect(container.textContent).toContain("all clear");
  });

  it("shows stream posts, mention state, and the flock summary", async () => {
    window.SEAGULL_CONFIG = { socialApiUrl: "https://api.example.test", auth: { mode: "local" } };
    saveLoopState({ activeUser: identity, activeProfile: profile, ownedProfiles: [profile] });
    mockApi({
      "/health": { ok: true, app: "social-api", storage: "memory" },
      "/profiles?owner_user_id=user_1": { items: [profile] },
      "/feed?owner_user_id=user_1&limit=50": { items: [post] },
      "/profiles/%40researcher%3Aseagull.local/notifications?owner_user_id=user_1&limit=50": {
        items: [notification],
      },
      "/moderation?limit=50": { items: [moderation] },
    });

    const container = renderApp("/sky");
    await waitForText(container, "Planning the first social loop.");

    expect(container.textContent).toContain("Researcher");
    expect(container.textContent).toContain("1 gull in your flock");
    expect(container.textContent).toContain("waiting on you");
    expect(container.querySelector('[aria-label="unread"]')).not.toBeNull();
    expect(container.textContent).toContain("Mentions");
  });

  it("opens personal AI Usage from the account settings button", async () => {
    window.SEAGULL_CONFIG = { socialApiUrl: "https://api.example.test", auth: { mode: "local" } };
    vi.stubGlobal("scrollTo", vi.fn());
    saveLoopState({ activeUser: identity, activeProfile: profile, ownedProfiles: [profile] });
    mockApi({
      "/health": { ok: true, app: "social-api", storage: "memory" },
      "/profiles?owner_user_id=user_1": { items: [profile] },
      "/feed?owner_user_id=user_1&limit=50": { items: [] },
      "/profiles/%40researcher%3Aseagull.local/notifications?owner_user_id=user_1&limit=50": {
        items: [],
      },
      "/moderation?limit=50": { items: [] },
      "/me/ai-usage?owner_user_id=user_1": {
        owner_user_id: "user_1",
        balance: { owner_user_id: "user_1", available_credits: 9800 },
        usage: [
          {
            usage_id: "usage_1",
            run_id: "run_1",
            provider: "openai",
            model: "gpt-6-luna",
            owner_user_id: "user_1",
            agent_id: "agent_1",
            input_tokens: 100,
            output_tokens: 40,
            cached_tokens: 20,
            estimated_cost_units: 140,
            created_at: "2026-10-17T09:00:00Z",
          },
        ],
        entries: [],
      },
    });

    const container = renderApp("/sky");
    await waitForText(container, "The sky");
    const primaryButtons = Array.from(container.querySelectorAll('nav[aria-label="Primary"] button'));
    expect(primaryButtons.some((item) => /usage/i.test(item.textContent ?? ""))).toBe(false);
    const settingsButton = container.querySelector('button[aria-label="Settings"]');
    expect(settingsButton).toBeInstanceOf(HTMLButtonElement);
    expect(container.querySelector('[aria-controls="account-menu"]')).toBeNull();
    expect(container.querySelector("#account-menu")).toBeNull();
    await act(async () => {
      (settingsButton as HTMLButtonElement).click();
    });
    await waitForText(container, "9,800");
    expect(container.textContent).toContain("Settings");
    expect(container.textContent).toContain("AI Usage");
    expect(container.textContent).toContain("Researcher");
    expect(container.querySelector('button[aria-label="Settings"]')?.getAttribute("aria-current")).toBe("page");

    const usageCall = vi.mocked(fetch).mock.calls.find(([input]) =>
      String(input).includes("/me/ai-usage?owner_user_id=user_1"),
    );
    expect(usageCall).toBeDefined();
  });

  it("redirects unauthenticated settings access to login", async () => {
    window.SEAGULL_CONFIG = { socialApiUrl: "https://api.example.test", auth: { mode: "local" } };
    mockApi({
      "/health": { ok: true, app: "social-api", storage: "memory" },
    });

    const container = renderApp("/settings");
    await waitForText(container, "Your sky is waiting");
    expect(container.querySelector('input[aria-label="Email"]')).not.toBeNull();
    expect(container.textContent).not.toContain("Available tokens");
  });

  it("redirects legacy routes into the new screens", async () => {
    window.SEAGULL_CONFIG = { socialApiUrl: "https://api.example.test", auth: { mode: "local" } };
    saveLoopState({ activeUser: identity, activeProfile: profile, ownedProfiles: [profile] });
    mockApi({
      "/health": { ok: true, app: "social-api", storage: "memory" },
      "/profiles?owner_user_id=user_1": { items: [profile] },
      "/feed?owner_user_id=user_1&limit=50": { items: [post] },
      "/profiles/%40researcher%3Aseagull.local/notifications?owner_user_id=user_1&limit=50": {
        items: [],
      },
      "/moderation?limit=50": { items: [] },
    });

    const container = renderApp("/dashboard");
    await waitForText(container, "The sky");

    expect(container.textContent).toContain("The stream");
  });

  it("renders message routing rules on the server screen", async () => {
    window.SEAGULL_CONFIG = {
      socialApiUrl: "https://api.example.test",
      messageApiUrl: "https://message.example.test",
      auth: { mode: "local" },
    };
    saveLoopState({ activeUser: identity, activeProfile: profile, ownedProfiles: [profile] });
    mockApi({
      "/health": { ok: true, app: "api", storage: "memory" },
      "/profiles?owner_user_id=user_1": { items: [profile] },
      "/feed?owner_user_id=user_1&limit=50": { items: [] },
      "/profiles/%40researcher%3Aseagull.local/notifications?owner_user_id=user_1&limit=50": {
        items: [],
      },
      "/moderation?limit=50": { items: [] },
      "/routing-rules": {
        items: [
          {
            rule_id: "rule_1",
            name: "Map links",
            mode: "copy",
            route_to_handles: ["@researcher:seagull.local"],
            url_contains: ["maps.google.com"],
            enabled: true,
            created_at: "2026-06-13T00:00:00Z",
            updated_at: "2026-06-13T00:00:00Z",
          },
        ],
      },
    });

    const container = renderApp("/routing");
    await waitForText(container, "Map links");

    expect(container.textContent).toContain("Routing rules");
    expect(container.textContent).toContain("maps.google.com");
    expect(container.querySelector('[role="switch"]')?.getAttribute("aria-checked")).toBe("true");
  });

  it("renders the agent chat route with stored messages", async () => {
    window.SEAGULL_CONFIG = { socialApiUrl: "https://api.example.test", auth: { mode: "local" } };
    saveLoopState({ activeUser: identity, activeProfile: profile, ownedProfiles: [profile] });
    mockApi({
      "/health": { ok: true, app: "api", storage: "memory" },
      "/profiles?owner_user_id=user_1": { items: [profile] },
      "/feed?owner_user_id=user_1&limit=50": { items: [] },
      "/profiles/%40researcher%3Aseagull.local/notifications?owner_user_id=user_1&limit=50": {
        items: [],
      },
      "/moderation?limit=50": { items: [] },
      "/agent-chats?owner_user_id=user_1": { items: [chat] },
      "/agent-chats/chat_1/messages?owner_user_id=user_1": { items: [chatMessage, chatReply] },
    });

    const container = renderApp("/chat/chat_1");
    await waitForText(container, "Can you review the landing page plan?");

    expect(container.textContent).toContain("Chat with Researcher");
    expect(container.textContent).toContain("Prompt asset_prompt");
    expect(container.textContent).toContain("Skill asset_skill");
    expect(container.textContent).toContain("Saved");
    expect(container.textContent).toContain("New chat");
    expect(container.textContent).toContain("The plan looks solid; tighten the hero copy.");
    expect(container.textContent).not.toContain("AI run airun_1 (completed)");
  });

  it("shows hub traffic in the stream and expands the delivery lifecycle", async () => {
    window.SEAGULL_CONFIG = {
      socialApiUrl: "https://api.example.test",
      messageApiUrl: "https://message.example.test",
      auth: { mode: "local" },
    };
    saveLoopState({ activeUser: identity, activeProfile: profile, ownedProfiles: [profile] });
    mockApi({
      "/health": { ok: true, app: "api", storage: "memory" },
      "/profiles?owner_user_id=user_1": { items: [profile] },
      "/feed?owner_user_id=user_1&limit=50": { items: [] },
      "/profiles/%40researcher%3Aseagull.local/notifications?owner_user_id=user_1&limit=50": {
        items: [],
      },
      "/moderation?limit=50": { items: [] },
      "/agents/%40researcher%3Aseagull.local/inbox?limit=20": inboxResponse,
    });

    const container = renderApp("/sky");
    await waitForText(container, "Prepared map question");

    expect(container.textContent).toContain("waiting on you");
    expect(container.textContent).toContain("@sender");

    await clickTestId(container, "traffic-toggle-delivery_1");
    await waitForText(container, "Original map question");

    expect(container.textContent).toContain("receive.before");
    expect(container.textContent).toContain("Apply hook");
    expect(container.textContent).toContain("Ask human");
  });

  it("routes @gull composer drafts to a direct chat with the mention prefix stripped", async () => {
    window.SEAGULL_CONFIG = { socialApiUrl: "https://api.example.test", auth: { mode: "local" } };
    saveLoopState({ activeUser: identity, activeProfile: profile, ownedProfiles: [profile] });
    mockApi({
      "/health": { ok: true, app: "api", storage: "memory" },
      "/profiles?owner_user_id=user_1": { items: [profile] },
      "/feed?owner_user_id=user_1&limit=50": { items: [] },
      "/profiles/%40researcher%3Aseagull.local/notifications?owner_user_id=user_1&limit=50": {
        items: [],
      },
      "/moderation?limit=50": { items: [] },
      "/agent-chats?owner_user_id=user_1": { items: [] },
      "/agent-chats": { created: true, chat },
      "/agent-chats/chat_1/messages": { message: chatMessage, reply: null },
    });

    const container = renderApp("/sky");
    await waitForText(container, "The stream");

    const composer = container.querySelector('textarea[aria-label="Composer"]');
    if (!(composer instanceof HTMLTextAreaElement)) {
      throw new Error("Composer textarea not found.");
    }
    await act(async () => {
      setNativeValue(composer, "@researcher:seagull.local please check");
    });
    await waitForText(container, "direct to @researcher — flies now");
    await act(async () => {
      composer.form!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    await waitForText(container, "Flew direct to @researcher");

    const fetchMock = vi.mocked(fetch);
    const chatCreate = fetchMock.mock.calls.find(
      ([input, init]) => String(input).endsWith("/agent-chats") && init?.method === "POST",
    );
    expect(String(chatCreate?.[1]?.body)).toContain('"agent_handle":"@researcher:seagull.local"');
    const messageCall = fetchMock.mock.calls.find(
      ([input, init]) => String(input).includes("/agent-chats/chat_1/messages") && init?.method === "POST",
    );
    expect(String(messageCall?.[1]?.body)).toContain('"content":"please check"');
    expect(
      fetchMock.mock.calls.some(([input, init]) => String(input).endsWith("/posts") && init?.method === "POST"),
    ).toBe(false);
  });

  it("publishes plain composer drafts as public sky posts", async () => {
    window.SEAGULL_CONFIG = { socialApiUrl: "https://api.example.test", auth: { mode: "local" } };
    saveLoopState({ activeUser: identity, activeProfile: profile, ownedProfiles: [profile] });
    mockApi({
      "/health": { ok: true, app: "api", storage: "memory" },
      "/profiles?owner_user_id=user_1": { items: [profile] },
      "/feed?owner_user_id=user_1&limit=50": { items: [] },
      "/profiles/%40researcher%3Aseagull.local/notifications?owner_user_id=user_1&limit=50": {
        items: [],
      },
      "/moderation?limit=50": { items: [] },
      "/posts": { post: { ...post, post_id: "post_2", content: "hello sky", created_at: "2026-06-13T00:01:00Z" } },
    });

    const container = renderApp("/sky");
    await waitForText(container, "The stream");

    const composer = container.querySelector('textarea[aria-label="Composer"]');
    if (!(composer instanceof HTMLTextAreaElement)) {
      throw new Error("Composer textarea not found.");
    }
    await act(async () => {
      setNativeValue(composer, "hello sky");
    });
    await act(async () => {
      composer.form!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    await waitForText(container, "hello sky");

    const fetchMock = vi.mocked(fetch);
    const postCall = fetchMock.mock.calls.find(
      ([input, init]) => String(input).endsWith("/posts") && init?.method === "POST",
    );
    expect(String(postCall?.[1]?.body)).toContain('"author_handle":"@researcher:seagull.local"');
    expect(String(postCall?.[1]?.body)).toContain('"visibility":"public"');
    expect(String(postCall?.[1]?.body)).toContain('"content":"hello sky"');
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) => String(input).endsWith("/agent-chats") && init?.method === "POST",
      ),
    ).toBe(false);
  });

  it("toggles and persists the dark theme", async () => {
    window.SEAGULL_CONFIG = { socialApiUrl: "https://api.example.test", auth: { mode: "local" } };
    saveLoopState({ activeUser: identity, activeProfile: profile, ownedProfiles: [profile] });
    mockApi({
      "/health": { ok: true, app: "api", storage: "memory" },
      "/profiles?owner_user_id=user_1": { items: [profile] },
      "/feed?owner_user_id=user_1&limit=50": { items: [] },
      "/profiles/%40researcher%3Aseagull.local/notifications?owner_user_id=user_1&limit=50": {
        items: [],
      },
      "/moderation?limit=50": { items: [] },
    });

    const container = renderApp("/sky");
    await waitForText(container, "The sky");

    const toggle = container.querySelector('[aria-label="Toggle dark mode"]');
    if (!(toggle instanceof HTMLElement)) {
      throw new Error("Theme toggle not found.");
    }
    await act(async () => {
      toggle.click();
    });
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(window.localStorage.getItem("seagulls-theme")).toBe("dark");

    await act(async () => {
      toggle.click();
    });
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(window.localStorage.getItem("seagulls-theme")).toBe("light");
  });

  it("clears user-scoped state and cached data on sign out", async () => {
    window.SEAGULL_CONFIG = {
      socialApiUrl: "https://api.example.test",
      messageApiUrl: "https://message.example.test",
      auth: { mode: "local" },
    };
    saveLoopState({ activeUser: identity, activeProfile: profile, ownedProfiles: [profile] });
    mockApi({
      "/health": { ok: true, app: "social-api", storage: "memory" },
      "/profiles?owner_user_id=user_1": { items: [profile] },
      "/feed?owner_user_id=user_1&limit=50": { items: [] },
      "/profiles/%40researcher%3Aseagull.local/notifications?owner_user_id=user_1&limit=50": {
        items: [],
      },
      "/moderation?limit=50": { items: [] },
    });

    const { container, queryClient } = renderAppWithQueryClient("/sky");
    await waitForText(container, "The sky");
    queryClient.setQueryData(["message-routing-rules", "https://message.example.test"], {
      items: [{ name: "account A private rule" }],
    });

    const signOutButton = container.querySelector<HTMLButtonElement>('button[aria-label="Sign out"]');
    if (!signOutButton) {
      throw new Error("Sign-out button not found.");
    }
    await act(async () => {
      signOutButton.click();
    });
    await waitForText(container, "Your sky is waiting");

    expect(
      queryClient.getQueryData(["message-routing-rules", "https://message.example.test"]),
    ).toBeUndefined();
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}").activeUser).toBeNull();
  });

  it("signs in through the custom Cognito email-code screen", async () => {
    window.SEAGULL_CONFIG = {
      socialApiUrl: "https://api.example.test",
      auth: {
        mode: "cognito",
        issuer: "https://cognito-idp.example.test/pool",
        hostedDomain: "seagull.auth.example.test",
        clientId: "client_1",
        redirectUri: "https://app.example.test/auth/callback",
        logoutUri: "https://app.example.test/register",
      },
    };
    const cognitoBodies: Record<string, unknown>[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const target = new Headers(init?.headers).get("x-amz-target") ?? "";
        if (target) {
          const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
          cognitoBodies.push(body);
          if (target.endsWith(".InitiateAuth")) {
            return new Response(
              JSON.stringify({ ChallengeName: "EMAIL_OTP", Session: "challenge_session_1" }),
              { status: 200 },
            );
          }
          if (target.endsWith(".RespondToAuthChallenge")) {
            return new Response(
              JSON.stringify({
                AuthenticationResult: {
                  AccessToken: "email-code-access-token",
                  IdToken: "email-code-id-token",
                  TokenType: "Bearer",
                  ExpiresIn: 3600,
                },
              }),
              { status: 200 },
            );
          }
        }

        const url = new URL(String(input));
        const key = `${url.pathname}${url.search}`;
        const responses: Record<string, unknown> = {
          "/health": { ok: true, app: "social-api", storage: "memory" },
          "/dashboard": {
            identity,
            profiles: { items: [profile] },
            feed: { items: [post] },
            notifications: { unread_count: 0, items: [] },
            moderation: { count: 0, items: [] },
            health: { ok: true, app: "social-api", storage: "memory" },
          },
          "/profiles": { items: [profile] },
          "/feed?owner_user_id=user_1&limit=50": { items: [post] },
          "/profiles/%40researcher%3Aseagull.local/notifications?limit=50": { items: [] },
          "/moderation?limit=50": { items: [] },
        };
        const responseBody = responses[key] ?? { error: "not_found", message: key };
        return new Response(JSON.stringify(responseBody), {
          status: key in responses ? 200 : 404,
          headers: { "content-type": "application/json" },
        });
      }),
    );

    const container = renderApp("/login");
    await waitForText(container, "Your sky is waiting");

    const emailInput = container.querySelector('input[aria-label="Email"]');
    if (!(emailInput instanceof HTMLInputElement)) {
      throw new Error("Email input not found.");
    }
    await act(async () => {
      setNativeValue(emailInput, "ALICE@example.com");
    });
    const requestButton = container.querySelector('button[aria-label="Send login code"]');
    if (!(requestButton instanceof HTMLButtonElement)) {
      throw new Error("Send-login-code button not found.");
    }
    await act(async () => {
      requestButton.click();
    });
    await waitForText(container, "Check your inbox");

    expect(container.textContent).toContain("We sent a code to alice@example.com.");
    const codeInput = container.querySelector('input[aria-label="Email code"]');
    if (!(codeInput instanceof HTMLInputElement)) {
      throw new Error("Email-code input not found.");
    }
    await act(async () => {
      setNativeValue(codeInput, "123456");
    });
    const verifyButton = container.querySelector('button[aria-label="Verify code"]');
    if (!(verifyButton instanceof HTMLButtonElement)) {
      throw new Error("Verify-code button not found.");
    }
    await act(async () => {
      verifyButton.click();
    });
    await waitForText(container, "The sky");

    const session = JSON.parse(window.localStorage.getItem("seagull.web.auth.session") ?? "{}");
    expect(session.accessToken).toBe("email-code-access-token");
    expect(window.sessionStorage.getItem("seagull.web.auth.session")).toBeNull();
    expect(cognitoBodies[0]).toMatchObject({
      AuthFlow: "USER_AUTH",
      AuthParameters: {
        USERNAME: "alice@example.com",
        PREFERRED_CHALLENGE: "EMAIL_OTP",
      },
    });
    expect(cognitoBodies[1]).toMatchObject({
      ChallengeName: "EMAIL_OTP",
      ChallengeResponses: { EMAIL_OTP_CODE: "123456" },
    });
    expect(JSON.stringify(cognitoBodies)).not.toContain("PASSWORD");
  });

  it("restores an expired persisted session without leaving the requested route", async () => {
    configureCognito();
    savePersistedSession({
      accessToken: "expired-access-token",
      refreshToken: "refresh-token-1",
      expiresAt: Date.now() - 1_000,
    });
    const refreshBodies: Record<string, unknown>[] = [];
    mockCognitoApi(cognitoDashboardResponses(), (body) => {
      refreshBodies.push(body);
      return jsonResponse({
        AuthenticationResult: {
          AccessToken: "restored-access-token",
          IdToken: "restored-id-token",
          RefreshToken: "refresh-token-1",
          TokenType: "Bearer",
          ExpiresIn: 3_600,
        },
      });
    });

    const container = renderApp("/flock");
    expect(container.textContent).toContain("Restoring your session");
    await waitForText(container, "Flock");

    expect(container.querySelector('button[aria-current="page"]')?.textContent).toContain("Flock");
    expect(container.querySelector('input[aria-label="Email"]')).toBeNull();
    expect(refreshBodies).toHaveLength(1);
    expect(refreshBodies[0]).toMatchObject({
      AuthFlow: "REFRESH_TOKEN_AUTH",
      AuthParameters: { REFRESH_TOKEN: "refresh-token-1" },
    });
    expect(JSON.parse(window.localStorage.getItem("seagull.web.auth.session") ?? "{}").accessToken).toBe(
      "restored-access-token",
    );
  });

  it("refreshes a persisted session before it expires", async () => {
    vi.useFakeTimers();
    configureCognito();
    savePersistedSession({
      accessToken: "active-access-token",
      refreshToken: "refresh-token-2",
      expiresAt: Date.now() + 61_000,
    });
    const refreshBodies: Record<string, unknown>[] = [];
    mockCognitoApi(cognitoDashboardResponses(), (body) => {
      refreshBodies.push(body);
      return jsonResponse({
        AuthenticationResult: {
          AccessToken: "proactively-refreshed-token",
          IdToken: "refreshed-id-token",
          RefreshToken: "refresh-token-2",
          TokenType: "Bearer",
          ExpiresIn: 3_600,
        },
      });
    });

    const container = renderApp("/sky");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    await waitForText(container, "The sky");

    expect(refreshBodies).toHaveLength(1);
    expect(JSON.parse(window.localStorage.getItem("seagull.web.auth.session") ?? "{}").accessToken).toBe(
      "proactively-refreshed-token",
    );
  });

  it("keeps a session persisted through a temporary refresh failure and retries online", async () => {
    configureCognito();
    savePersistedSession({
      accessToken: "offline-access-token",
      refreshToken: "refresh-token-3",
      expiresAt: Date.now() - 1_000,
    });
    let attempts = 0;
    mockCognitoApi(cognitoDashboardResponses(), () => {
      attempts += 1;
      if (attempts === 1) {
        return jsonResponse({ message: "temporarily unavailable" }, 503);
      }
      return jsonResponse({
        AuthenticationResult: {
          AccessToken: "reconnected-access-token",
          IdToken: "reconnected-id-token",
          RefreshToken: "refresh-token-3",
          TokenType: "Bearer",
          ExpiresIn: 3_600,
        },
      });
    });

    const container = renderApp("/sky");
    await waitForText(container, "We couldn’t reconnect");
    expect(window.localStorage.getItem("seagull.web.auth.session")).toContain("offline-access-token");

    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });
    await waitForText(container, "The sky");
    expect(attempts).toBe(2);
  });

  it("clears a revoked persisted session and returns to login", async () => {
    configureCognito();
    savePersistedSession({
      accessToken: "revoked-access-token",
      refreshToken: "revoked-refresh-token",
      expiresAt: Date.now() - 1_000,
    });
    mockCognitoApi(cognitoDashboardResponses(), () =>
      jsonResponse(
        { __type: "NotAuthorizedException", message: "Refresh Token has been revoked" },
        400,
      ),
    );

    const container = renderApp("/sky");
    await waitForText(container, "Your sky is waiting");

    expect(window.localStorage.getItem("seagull.web.auth.session")).toBeNull();
    expect(window.sessionStorage.getItem("seagull.web.auth.session")).toBeNull();
  });

  it("ignores a late refresh response after signing in with another account", async () => {
    configureCognito();
    savePersistedSession({
      accessToken: "old-access-token",
      refreshToken: "old-refresh-token",
      expiresAt: Date.now() - 1_000,
    });
    let resolveRefresh!: (response: Response) => void;
    const refreshResponse = new Promise<Response>((resolve) => {
      resolveRefresh = resolve;
    });
    mockCognitoApi(cognitoDashboardResponses(), () => refreshResponse);

    const container = renderApp("/sky");
    await waitForText(container, "Restoring your session");
    const anotherAccountButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Sign in with another account"),
    );
    if (!(anotherAccountButton instanceof HTMLButtonElement)) {
      throw new Error("Another-account button not found.");
    }
    await act(async () => {
      anotherAccountButton.click();
    });
    await waitForText(container, "Your sky is waiting");
    expect(window.localStorage.getItem("seagull.web.auth.session")).toBeNull();

    resolveRefresh(
      jsonResponse({
        AuthenticationResult: {
          AccessToken: "late-access-token",
          RefreshToken: "late-refresh-token",
          TokenType: "Bearer",
          ExpiresIn: 3_600,
        },
      }),
    );
    await act(async () => {
      await refreshResponse;
      await Promise.resolve();
    });
    expect(window.localStorage.getItem("seagull.web.auth.session")).toBeNull();
    expect(container.textContent).toContain("Your sky is waiting");
  });

  it("signs out when another tab removes the persisted session", async () => {
    configureCognito();
    savePersistedSession({
      accessToken: "cross-tab-access-token",
      refreshToken: "cross-tab-refresh-token",
      expiresAt: Date.now() + 3_600_000,
    });
    mockCognitoApi(cognitoDashboardResponses(), () => {
      throw new Error("Cross-tab logout should not refresh.");
    });

    const container = renderApp("/sky");
    await waitForText(container, "The sky");
    window.localStorage.removeItem("seagull.web.auth.session");
    const event = new StorageEvent("storage", { key: "seagull.web.auth.session", newValue: null });
    Object.defineProperty(event, "storageArea", { value: window.localStorage });
    await act(async () => {
      window.dispatchEvent(event);
    });
    await waitForText(container, "Your sky is waiting");
  });

  it("does not repeatedly renew a session that the API still rejects", async () => {
    configureCognito();
    savePersistedSession();
    let renewals = 0;
    mockCognitoApi(cognitoDashboardResponses(), () => {
      renewals += 1;
      return jsonResponse({ AuthenticationResult: { AccessToken: "still-rejected-token", ExpiresIn: 3_600 } });
    });
    const apiFetch = vi.mocked(fetch).getMockImplementation()!;
    vi.mocked(fetch).mockImplementation((input, init) => {
      if (new URL(String(input)).pathname === "/dashboard") {
        return Promise.resolve(jsonResponse({ message: "Not authorized" }, 401));
      }
      return apiFetch(input, init);
    });

    const container = renderApp("/sky");
    await waitForText(container, "Your sky is waiting");

    expect(renewals).toBe(1);
    expect(window.localStorage.getItem("seagull.web.auth.session")).toBeNull();
  });

  it.each([
    { claims: { name: "Zoë Carter", email: "zoe@example.com" }, label: "Zoë Carter" },
    { claims: { email: "alice@example.com" }, label: "alice" },
    { claims: { email: "alice@example.com" }, label: "alice", subject: "opaque-cognito-user" },
  ])("shows $label instead of the Cognito ID in the sidebar", async ({ claims, label, subject = "00000000-0000-4000-8000-000000000001" }) => {
    window.SEAGULL_CONFIG = {
      socialApiUrl: "https://api.example.test",
      auth: {
        mode: "cognito",
        issuer: "https://cognito-idp.example.test/pool",
        clientId: "client_1",
      },
    };
    const payload = btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(claims))))
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    window.sessionStorage.setItem("seagull.web.auth.session", JSON.stringify({
      accessToken: "sidebar-access-token",
      idToken: `header.${payload}.signature`,
      tokenType: "Bearer",
      expiresAt: Date.now() + 3_600_000,
    }));
    mockApi({
      "/health": { ok: true, app: "social-api", storage: "memory" },
      "/dashboard": {
        identity: { ...identity, provider: "cognito", subject, email: null, display_name: subject },
        profiles: { items: [] },
        feed: { items: [] },
        notifications: { unread_count: 0, items: [] },
        moderation: { count: 0, items: [] },
        health: { ok: true, app: "social-api", storage: "memory" },
      },
      "/profiles": { items: [] },
      "/feed?owner_user_id=user_1&limit=50": { items: [] },
      "/moderation?limit=50": { items: [] },
    });

    const container = renderApp("/sky");
    await waitForText(container, label);

    expect(window.localStorage.getItem("seagull.web.auth.session")).toContain("sidebar-access-token");
    expect(window.sessionStorage.getItem("seagull.web.auth.session")).toBeNull();
    const sidebar = container.querySelector("aside");
    expect(sidebar?.textContent).toContain(label);
    expect(sidebar?.textContent).not.toContain(subject);
  });

  it("redirects legacy Hosted UI callbacks to the email-code login", async () => {
    window.SEAGULL_CONFIG = {
      socialApiUrl: "https://api.example.test",
      auth: {
        mode: "cognito",
        issuer: "https://cognito-idp.example.test/pool",
        hostedDomain: "seagull.auth.example.test",
        clientId: "client_1",
        redirectUri: "https://app.example.test/auth/callback",
        logoutUri: "https://app.example.test/register",
      },
    };
    mockApi({
      "/health": { ok: true, app: "social-api", storage: "memory" },
    });

    const container = renderApp("/auth/callback?code=code_1&state=state_1");
    await waitForText(container, "Your sky is waiting");

    const fetchMock = vi.mocked(fetch);
    expect(
      fetchMock.mock.calls.some(([, init]) => {
        const target = new Headers(init?.headers).get("x-amz-target") ?? "";
        return target.length > 0;
      }),
    ).toBe(false);
    expect(window.sessionStorage.getItem("seagull.web.auth.session")).toBeNull();
  });

  it("renders AI provider admin config on the server screen", async () => {
    window.SEAGULL_CONFIG = {
      socialApiUrl: "https://api.example.test",
      messageApiUrl: "https://message.example.test",
      aiProviderApiUrl: "https://ai.example.test",
      auth: {
        mode: "cognito",
        issuer: "https://cognito-idp.example.test/pool",
        hostedDomain: "seagull.auth.example.test",
        clientId: "client_1",
        redirectUri: "https://app.example.test/auth/callback",
        logoutUri: "https://app.example.test/register",
      },
    };
    window.sessionStorage.setItem(
      "seagull.web.auth.session",
      JSON.stringify({
        accessToken: "admin-access-token",
        idToken: null,
        refreshToken: null,
        tokenType: "Bearer",
        expiresAt: Date.now() + 3_600_000,
      }),
    );
    saveLoopState({ activeUser: identity, activeProfile: profile, ownedProfiles: [profile] });
    mockApi({
      "/health": { ok: true, app: "api", storage: "memory" },
      "/dashboard": {
        identity,
        profiles: { items: [profile] },
        feed: { items: [] },
        notifications: { unread_count: 0, items: [] },
        moderation: { count: 0, items: [] },
        health: { ok: true, app: "api", storage: "memory" },
      },
      "/profiles": { items: [profile] },
      "/profiles?owner_user_id=user_1": { items: [profile] },
      "/feed?owner_user_id=user_1&limit=50": { items: [] },
      "/profiles/%40researcher%3Aseagull.local/notifications?owner_user_id=user_1&limit=50": {
        items: [],
      },
      "/moderation?limit=50": { items: [] },
      "/routing-rules": { items: [] },
      "https://ai.example.test/health": { ok: true, app: "ai-provider", storage: "dynamodb" },
      "https://ai.example.test/admin/ai-providers": {
        provider_configs: [
          {
            provider_config_id: "provider_config_fake",
            provider: "fake",
            enabled: true,
            allowed_models: ["fake-small"],
            secret_ref: null,
            region: null,
            created_at: "2026-06-29T00:00:00Z",
            updated_at: "2026-06-29T00:00:00Z",
          },
        ],
      },
      "https://ai.example.test/admin/ai-credits/server-balance": {
        balance: { available_credits: 12000 },
      },
      "https://ai.example.test/admin/ai-credits/server-ledger": {
        entries: [
          {
            entry_id: "server_credit_1",
            entry_type: "credit_grant",
            credit_delta: 12000,
            reason: "Initial pool",
            admin_actor_id: "server-owner",
            owner_user_id: null,
            user_credit_entry_id: null,
            created_at: "2026-06-29T00:00:00Z",
          },
        ],
      },
      "https://ai.example.test/admin/ai-audit-events": {
        events: [
          {
            audit_id: "audit_1",
            admin_actor_id: "server-owner",
            action: "ai.provider_config_update",
            target_type: "provider",
            target_id: "fake",
            reason: "Enable fake provider",
            metadata: {},
            created_at: "2026-06-29T00:00:00Z",
          },
        ],
      },
    });

    const container = renderApp("/server");
    await waitForText(container, "12,000");

    expect(container.textContent).toContain("fake");
    expect(container.textContent).toContain("fake-small");
    expect(container.textContent).toContain("ai.provider_config_update");
    expect(container.textContent).toContain("Initial pool");

    const fetchMock = vi.mocked(fetch);
    const providerCall = fetchMock.mock.calls.find(([input]) => String(input) === "https://ai.example.test/admin/ai-providers");
    const headers = new Headers(providerCall?.[1]?.headers);
    expect(headers.get("authorization")).toBe("Bearer admin-access-token");
    expect(headers.get("x-seagull-admin-secret")).toBeNull();
  });
});

function renderApp(path: string): HTMLElement {
  return renderAppWithQueryClient(path).container;
}

function renderAppWithQueryClient(path: string): {
  container: HTMLElement;
  queryClient: QueryClient;
} {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.push(root);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  act(() => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  });
  return { container, queryClient };
}

function saveLoopState(partial: Record<string, unknown>): void {
  window.localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      apiUrl: "https://api.example.test",
      activeUser: null,
      reviewUser: null,
      activeProfile: null,
      reviewProfile: null,
      ownedProfiles: [],
      room: null,
      membership: null,
      follow: null,
      posts: [],
      selectedPostId: null,
      moderation: null,
      updatedAt: null,
      ...partial,
    }),
  );
}

function mockApi(responses: Record<string, unknown>): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = new URL(String(input));
      const key = `${url.pathname}${url.search}`;
      const fullKey = `${url.origin}${url.pathname}${url.search}`;
      const body = responses[fullKey] ?? responses[key] ?? { error: "not_found", message: fullKey };
      return new Response(JSON.stringify(body), {
        status: fullKey in responses || key in responses ? 200 : 404,
        headers: { "content-type": "application/json" },
      });
    }),
  );
}

function configureCognito(): void {
  window.SEAGULL_CONFIG = {
    socialApiUrl: "https://api.example.test",
    auth: {
      mode: "cognito",
      issuer: "https://cognito-idp.example.test/pool",
      clientId: "client_1",
    },
  };
}

function savePersistedSession(overrides: Partial<{
  accessToken: string;
  idToken: string | null;
  refreshToken: string | null;
  tokenType: string;
  expiresAt: number;
}> = {}): void {
  window.localStorage.setItem(
    "seagull.web.auth.session",
    JSON.stringify({
      accessToken: "persisted-access-token",
      idToken: "persisted-id-token",
      refreshToken: "persisted-refresh-token",
      tokenType: "Bearer",
      expiresAt: Date.now() + 3_600_000,
      ...overrides,
    }),
  );
}

function cognitoDashboardResponses(): Record<string, unknown> {
  return {
    "/health": { ok: true, app: "social-api", storage: "memory" },
    "/dashboard": {
      identity: { ...identity, provider: "cognito" },
      profiles: { items: [profile] },
      feed: { items: [] },
      notifications: { unread_count: 0, items: [] },
      moderation: { count: 0, items: [] },
      health: { ok: true, app: "social-api", storage: "memory" },
    },
    "/profiles": { items: [profile] },
    "/feed?owner_user_id=user_1&limit=50": { items: [] },
    "/profiles/%40researcher%3Aseagull.local/notifications?limit=50": { items: [] },
    "/moderation?limit=50": { items: [] },
  };
}

function mockCognitoApi(
  responses: Record<string, unknown>,
  refreshHandler: (body: Record<string, unknown>) => Response | Promise<Response>,
): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const target = new Headers(init?.headers).get("x-amz-target") ?? "";
      if (target.endsWith(".InitiateAuth")) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        if (body.AuthFlow === "REFRESH_TOKEN_AUTH") {
          return refreshHandler(body);
        }
      }
      const url = new URL(String(input));
      const key = `${url.pathname}${url.search}`;
      const fullKey = `${url.origin}${url.pathname}${url.search}`;
      const body = responses[fullKey] ?? responses[key] ?? { error: "not_found", message: fullKey };
      return new Response(JSON.stringify(body), {
        status: fullKey in responses || key in responses ? 200 : 404,
        headers: { "content-type": "application/json" },
      });
    }),
  );
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function setNativeValue(element: HTMLTextAreaElement | HTMLInputElement, value: string): void {
  const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  if (!setter) {
    throw new Error("Native value setter unavailable.");
  }
  setter.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

async function clickTestId(container: HTMLElement, testId: string): Promise<void> {
  const element = container.querySelector(`[data-testid="${testId}"]`);
  if (!(element instanceof HTMLElement)) {
    throw new Error(`Expected to find element with data-testid "${testId}".`);
  }
  await act(async () => {
    element.click();
  });
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

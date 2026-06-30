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
  created_at: "2026-06-13T00:00:21Z",
  updated_at: "2026-06-13T00:00:21Z",
};

const roots: Root[] = [];

afterEach(async () => {
  for (const root of roots.splice(0)) {
    await act(async () => {
      root.unmount();
    });
  }
  document.body.innerHTML = "";
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.SEAGULL_CONFIG = undefined;
  vi.restoreAllMocks();
});

describe("App dashboard", () => {
  it("keeps unauthenticated users on a clean auth screen", async () => {
    window.SEAGULL_CONFIG = { socialApiUrl: "https://api.example.test", auth: { mode: "local" } };
    mockApi({
      "/health": { ok: true, app: "social-api", storage: "memory" },
    });

    const container = renderApp("/");
    await waitForText(container, "Login");

    expect(container.textContent).toContain("Register");
    expect(container.textContent).not.toContain("Social workspace");
    expect(container.textContent).not.toContain("Social API");
  });

  it("shows first-agent creation as the dashboard empty state", async () => {
    window.SEAGULL_CONFIG = { socialApiUrl: "https://api.example.test", auth: { mode: "local" } };
    saveLoopState({ activeUser: identity });
    mockApi({
      "/health": { ok: true, app: "social-api", storage: "memory" },
      "/profiles?owner_user_id=user_1": { items: [] },
      "/feed?owner_user_id=user_1&limit=50": { items: [] },
      "/moderation?limit=50": { items: [] },
    });

    const container = renderApp("/dashboard");
    await waitForText(container, "Create first agent");

    expect(container.textContent).toContain("Create the first social identity for your AI.");
    expect(container.textContent).toContain("0 unread mentions");
  });

  it("shows loaded agent activity and attention counts", async () => {
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

    const container = renderApp("/dashboard");
    await waitForText(container, "Recent social activity");

    expect(container.textContent).toContain("Researcher");
    expect(container.textContent).toContain("Planning the first social loop.");
    expect(container.textContent).toContain("1 unread mentions");
    expect(container.textContent).toContain("1 moderation items");
    expect(container.textContent).toContain("Profile");
    expect(container.textContent).toContain("Post");
    expect(container.textContent).toContain("Inbox");
  });

  it("renders message routing rules", async () => {
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

    expect(container.textContent).toContain("Message rules");
    expect(container.textContent).toContain("maps.google.com");
    expect(container.textContent).toContain("URL routing");
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
      "/agent-chats/chat_1/messages?owner_user_id=user_1": { items: [chatMessage] },
    });

    const container = renderApp("/chat/chat_1");
    await waitForText(container, "Can you review the landing page plan?");

    expect(container.textContent).toContain("Chat with Researcher");
    expect(container.textContent).toContain("Prompt asset_prompt");
    expect(container.textContent).toContain("Skill asset_skill");
    expect(container.textContent).toContain("stored");
    expect(container.textContent).toContain("New chat");
  });

  it("renders lifecycle inbox original and current messages", async () => {
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
      "/agents/%40researcher%3Aseagull.local/inbox?limit=20": {
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
      },
    });

    const container = renderApp("/agent-inbox");
    await waitForText(container, "Prepared map question");

    expect(container.textContent).toContain("Lifecycle deliveries");
    expect(container.textContent).toContain("Original map question");
    expect(container.textContent).toContain("receive.before");
    expect(container.textContent).toContain("Apply hook");
  });

  it("completes Cognito Hosted UI callbacks without direct password auth APIs", async () => {
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
    window.sessionStorage.setItem(
      "seagull.web.auth.pending",
      JSON.stringify({ state: "state_1", codeVerifier: "verifier_1", createdAt: 1 }),
    );
    mockApi({
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
      "/profiles/%40researcher%3Aseagull.local/notifications?owner_user_id=user_1&limit=50": {
        items: [],
      },
      "/moderation?limit=50": { items: [] },
      "https://seagull.auth.example.test/oauth2/token": {
        access_token: "access_1",
        id_token: "id_1",
        token_type: "Bearer",
        expires_in: 3600,
      },
    });

    const container = renderApp("/auth/callback?code=code_1&state=state_1");
    await waitForText(container, "Recent social activity");

    const session = JSON.parse(window.sessionStorage.getItem("seagull.web.auth.session") ?? "{}");
    expect(session.accessToken).toBe("access_1");

    const fetchMock = vi.mocked(fetch);
    const tokenCall = fetchMock.mock.calls.find(([input]) => String(input) === "https://seagull.auth.example.test/oauth2/token");
    expect(String(tokenCall?.[1]?.body)).toContain("code_verifier=verifier_1");
    expect(
      fetchMock.mock.calls.some(([, init]) => {
        const target = new Headers(init?.headers).get("x-amz-target") ?? "";
        return target.includes("SignUp") || target.includes("ConfirmSignUp") || target.includes("InitiateAuth");
      }),
    ).toBe(false);
  });

  it("renders AI provider admin config", async () => {
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

    const container = renderApp("/admin");
    await waitForText(container, "12000");

    expect(container.textContent).toContain("fake");
    expect(container.textContent).toContain("fake-small");
    expect(container.textContent).toContain("12000");
    expect(container.textContent).toContain("ai.provider_config_update");

    const fetchMock = vi.mocked(fetch);
    const providerCall = fetchMock.mock.calls.find(([input]) => String(input) === "https://ai.example.test/admin/ai-providers");
    const headers = new Headers(providerCall?.[1]?.headers);
    expect(headers.get("authorization")).toBe("Bearer admin-access-token");
    expect(headers.get("x-seagull-admin-secret")).toBeNull();
  });
});

function renderApp(path: string): HTMLElement {
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
  return container;
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

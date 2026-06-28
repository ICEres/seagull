import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type { AgentProfile, HumanIdentity, ModerationRecord, Notification, Post } from "./lib/social";

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

const roots: Root[] = [];

afterEach(async () => {
  for (const root of roots.splice(0)) {
    await act(async () => {
      root.unmount();
    });
  }
  document.body.innerHTML = "";
  window.localStorage.clear();
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
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input));
      const key = `${url.pathname}${url.search}`;
      const body = responses[key] ?? { error: "not_found", message: key };
      return new Response(JSON.stringify(body), {
        status: key in responses ? 200 : 404,
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

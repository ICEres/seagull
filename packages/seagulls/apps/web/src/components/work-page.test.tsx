import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkPage } from "./work-page";
import { MessageHubClient, type HubTask } from "../lib/message-hub";
import type { AgentProfile } from "../lib/social";

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

function task(overrides: Partial<HubTask> = {}): HubTask {
  return {
    task_id: "task_1",
    thread_id: "thread_1",
    requester_agent_id: "agent_1",
    recipient_agent_id: "agent_2",
    objective: "Summarize the release notes",
    state: "running",
    accepted_by_agent_id: null,
    result_message_id: null,
    result_ref: null,
    artifact_refs: [],
    created_at: "2026-06-13T00:00:00Z",
    updated_at: "2026-06-13T00:00:00Z",
    ...overrides,
  };
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

async function render(profiles: AgentProfile[], tasks: HubTask[]) {
  const requests: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      requests.push(String(url));
      return new Response(
        JSON.stringify({ agent_handle: profiles[0]?.handle ?? "", role: "all", tasks }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }),
  );

  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  await act(async () => {
    root?.render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <WorkPage
            messageApi={new MessageHubClient("https://message.example.test")}
            profiles={profiles}
            onNotice={() => {}}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  });
  // react-query resolves over several microtask/timer turns; poll until the
  // loading state clears rather than guessing a single flush.
  const text = () => container?.textContent ?? "";
  for (let attempt = 0; attempt < 25 && text().includes("Loading requests"); attempt += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 5));
    });
  }

  return { requests, text };
}

describe("WorkPage", () => {
  it("lists an agent's requests", async () => {
    const { text } = await render([agent()], [task()]);

    expect(text()).toContain("Summarize the release notes");
    // State is humanized, not raw snake_case.
    expect(text()).toContain("running");
  });

  it("separates open requests from finished ones", async () => {
    const { text } = await render(
      [agent()],
      [
        task({ task_id: "task_open", objective: "Still going", state: "running" }),
        task({ task_id: "task_done", objective: "All wrapped up", state: "completed" }),
      ],
    );

    expect(text()).toContain("Open (1)");
    expect(text()).toContain("Finished (1)");
  });

  it("queries the first owned agent by default", async () => {
    const { requests } = await render([agent()], []);

    expect(requests[0]).toContain("/agents/%40researcher%3Aseagull.local/tasks");
    expect(requests[0]).toContain("role=all");
  });

  it("explains itself when the human owns no agents", async () => {
    const { text, requests } = await render([], []);

    expect(text()).toContain("Create an agent in Flock first");
    // Nothing to ask about, so nothing is requested.
    expect(requests).toHaveLength(0);
  });

  it("reports an empty queue rather than looking broken", async () => {
    const { text } = await render([agent()], []);

    expect(text()).toContain("No requests yet");
  });
});

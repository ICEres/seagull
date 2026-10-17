import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FlockPage } from "./flock-page";
import { SocialApiClient } from "../lib/api";
import { emptyLoopState } from "../lib/state";
import type { AgentProfile, LoopState, PersonalAgentAsset } from "../lib/social";

function agent(overrides: Partial<AgentProfile> = {}): AgentProfile {
  return {
    agent_id: "agent_1",
    owner_user_id: "user_1",
    handle: "@researcher:seagull.local",
    display_name: "Researcher",
    bio: "Research agent",
    capabilities: ["research"],
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
  };
}

function prompt(instructions: string, overrides: Partial<PersonalAgentAsset> = {}): PersonalAgentAsset {
  return {
    asset_id: "prompt_1",
    owner_user_id: "user_1",
    asset_type: "prompt",
    name: "Reply prompt",
    instructions,
    description: null,
    style: null,
    tags: [],
    max_output_chars: null,
    status: "active",
    created_at: "2026-06-13T00:00:00Z",
    updated_at: "2026-06-13T00:00:00Z",
    ...overrides,
  };
}

function loopState(userId = "user_1"): LoopState {
  return {
    ...emptyLoopState(),
    apiUrl: "https://social.example.test",
    activeUser: {
      user_id: userId,
      provider: "local",
      subject: userId,
      email: `${userId}@example.com`,
      display_name: userId,
      created_at: "2026-06-13T00:00:00Z",
      updated_at: "2026-06-13T00:00:00Z",
    },
  };
}

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function setNativeValue(element: HTMLTextAreaElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
  if (!setter) {
    throw new Error("Native value setter unavailable.");
  }
  setter.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

async function flush(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function waitForText(text: string): Promise<void> {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (container?.textContent?.includes(text)) {
      return;
    }
    await flush();
  }
  throw new Error(`Expected to find "${text}" in: ${container?.textContent ?? ""}`);
}

function button(text: string, scope: ParentNode = container!): HTMLButtonElement {
  const found = Array.from(scope.querySelectorAll("button")).find((candidate) => candidate.textContent?.trim() === text);
  if (!(found instanceof HTMLButtonElement)) {
    throw new Error(`Button "${text}" not found.`);
  }
  return found;
}

function articleFor(handle: string): HTMLElement {
  const article = Array.from(container!.querySelectorAll("article")).find((candidate) =>
    candidate.textContent?.includes(handle),
  );
  if (!(article instanceof HTMLElement)) {
    throw new Error(`Article for ${handle} not found.`);
  }
  return article;
}

function promptTextarea(): HTMLTextAreaElement {
  const textarea = container?.querySelector('section[aria-label^="Reply prompt"] textarea');
  if (!(textarea instanceof HTMLTextAreaElement)) {
    throw new Error("Reply instructions textarea not found.");
  }
  return textarea;
}

async function waitForPromptTextarea(): Promise<HTMLTextAreaElement> {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const textarea = container?.querySelector('section[aria-label^="Reply prompt"] textarea');
    if (textarea instanceof HTMLTextAreaElement) {
      return textarea;
    }
    await flush();
  }
  return promptTextarea();
}

async function renderFlock({
  fetchImpl,
  profiles = [agent()],
  userId = "user_1",
}: {
  fetchImpl: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
  profiles?: AgentProfile[];
  userId?: string;
}): Promise<void> {
  vi.stubGlobal("fetch", vi.fn(fetchImpl));
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const api = new SocialApiClient("https://social.example.test");

  await act(async () => {
    root?.render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <FlockPage
            api={api}
            state={loopState(userId)}
            setState={() => {}}
            profiles={profiles}
            onNotice={() => {}}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  });
}

let root: Root | null = null;
let container: HTMLDivElement | null = null;

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  vi.unstubAllGlobals();
});

describe("FlockPage per-gull prompts", () => {
  it("loads a prompt only after opening that gull's editor and saves it to that gull", async () => {
    const first = agent();
    const second = agent({
      agent_id: "agent_2",
      handle: "@writer:seagull.local",
      display_name: "Writer",
    });
    const requests: Array<{ method: string; url: string; body?: string }> = [];

    await renderFlock({
      profiles: [first, second],
      fetchImpl: async (input, init) => {
        const url = String(input);
        requests.push({ method: init?.method ?? "GET", url, body: init?.body as string | undefined });
        if (init?.method === "PUT") {
          return response({ prompt: prompt("Answer in a concise, practical style.") });
        }
        return response({ prompt: prompt("Start with the conclusion.") });
      },
    });

    expect(requests).toHaveLength(0);
    await act(async () => {
      button("Prompt", articleFor("Researcher")).click();
    });
    await waitForText("Reply prompt");
    expect(requests).toHaveLength(1);
    expect(requests[0].url).toContain("/profiles/%40researcher%3Aseagull.local/prompt");
    expect(requests[0].url).toContain("owner_user_id=user_1");

    const textarea = await waitForPromptTextarea();
    setNativeValue(textarea, "Answer in a concise, practical style.");
    await act(async () => {
      button("Save prompt", articleFor("Researcher")).click();
    });
    await flush();

    expect(requests).toHaveLength(2);
    expect(requests[1].method).toBe("PUT");
    expect(requests[1].url).toContain("/profiles/%40researcher%3Aseagull.local/prompt");
    expect(JSON.parse(requests[1].body ?? "{}")).toEqual({
      owner_user_id: "user_1",
      instructions: "Answer in a concise, practical style.",
    });
    expect(container?.textContent).not.toContain("Reply prompt");
  });

  it("keeps gull editors isolated and cancel never writes", async () => {
    const first = agent();
    const second = agent({
      agent_id: "agent_2",
      handle: "@writer:seagull.local",
      display_name: "Writer",
    });
    const requests: string[] = [];

    await renderFlock({
      profiles: [first, second],
      fetchImpl: async (input) => {
        requests.push(String(input));
        return response({ prompt: prompt("Only Researcher should see this.") });
      },
    });

    await act(async () => {
      button("Prompt", articleFor("Researcher")).click();
    });
    await waitForText("Only Researcher should see this.");
    expect(requests).toHaveLength(1);
    expect(requests[0]).toContain("researcher");
    expect(requests[0]).not.toContain("writer");

    const textarea = await waitForPromptTextarea();
    setNativeValue(textarea, "Unsaved change.");
    await act(async () => {
      button("Cancel", articleFor("Researcher")).click();
    });
    await flush();
    expect(requests).toHaveLength(1);
    expect(container?.textContent).not.toContain("Unsaved change.");
    expect(container?.textContent).toContain("Writer");
  });

  it("reset clears the draft but does not persist until Save prompt is clicked", async () => {
    const requests: Array<{ method: string; body?: string }> = [];
    await renderFlock({
      fetchImpl: async (input, init) => {
        requests.push({ method: init?.method ?? "GET", body: init?.body as string | undefined });
        if (init?.method === "PUT") {
          return response({ prompt: null });
        }
        return response({ prompt: prompt("A saved instruction.") });
      },
    });

    await act(async () => {
      button("Prompt", articleFor("Researcher")).click();
    });
    await waitForText("A saved instruction.");
    await act(async () => {
      button("Reset to default", articleFor("Researcher")).click();
    });
    expect(promptTextarea().value).toBe("");
    expect(requests).toHaveLength(1);
    await act(async () => {
      button("Save prompt", articleFor("Researcher")).click();
    });
    await flush();
    expect(requests).toHaveLength(2);
    expect(JSON.parse(requests[1].body ?? "{}")).toEqual({ owner_user_id: "user_1", instructions: "" });
  });

  it("retains the draft and shows an inline error when saving fails", async () => {
    let saveAttempted = false;
    await renderFlock({
      fetchImpl: async (_input, init) => {
        if (init?.method === "PUT") {
          saveAttempted = true;
          return response({ error: "save failed" }, 500);
        }
        return response({ prompt: null });
      },
    });

    await act(async () => {
      button("Prompt", articleFor("Researcher")).click();
    });
    await waitForText("Reply prompt");
    const textarea = await waitForPromptTextarea();
    setNativeValue(textarea, "Keep the answer short.");
    await act(async () => {
      button("Save prompt", articleFor("Researcher")).click();
    });
    await waitForText("Could not save the prompt.");
    expect(saveAttempted).toBe(true);
    expect(textarea.value).toBe("Keep the answer short.");
    expect(container?.textContent).toContain("Reply prompt");
  });

  it("blocks editing after a load failure and retries the same gull without leaking data", async () => {
    let loads = 0;
    await renderFlock({
      fetchImpl: async (input) => {
        const url = String(input);
        if (url.includes("researcher")) {
          loads += 1;
          if (loads === 1) {
            return response({ error: "load failed" }, 503);
          }
          return response({ prompt: prompt("Retry succeeded.") });
        }
        return response({ prompt: prompt("Writer secret.", { owner_user_id: "user_2" }) });
      },
      profiles: [agent(), agent({ agent_id: "agent_2", handle: "@writer:seagull.local", display_name: "Writer" })],
    });

    await act(async () => {
      button("Prompt", articleFor("Researcher")).click();
    });
    await waitForText("Could not load the prompt.");
    expect(container?.querySelector('section[aria-label^="Reply prompt"] textarea')).toBeNull();
    await act(async () => {
      button("Try again", articleFor("Researcher")).click();
    });
    await waitForText("Retry succeeded.");
    expect(loads).toBe(2);
    expect(container?.textContent).not.toContain("Writer secret.");
  });

  it("includes the active owner in prompt requests", async () => {
    const urls: string[] = [];
    await renderFlock({
      userId: "user_2",
      profiles: [agent({ owner_user_id: "user_2" })],
      fetchImpl: async (input) => {
        urls.push(String(input));
        return response({ prompt: null });
      },
    });

    await act(async () => {
      button("Prompt", articleFor("Researcher")).click();
    });
    await waitForText("Reply prompt");
    expect(urls[0]).toContain("owner_user_id=user_2");
  });
});

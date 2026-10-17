import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AiUsagePage } from "./ai-usage-page";
import { SocialApiClient } from "../lib/api";
import { emptyLoopState } from "../lib/state";
import type { AgentProfile, LoopState } from "../lib/social";

type UsageRecord = {
  usage_id: string;
  run_id: string;
  provider: string;
  model: string;
  owner_user_id: string;
  agent_id: string;
  input_tokens: number;
  output_tokens: number;
  cached_tokens: number;
  estimated_cost_units: number;
  created_at: string;
};

type UsageResponse = {
  owner_user_id: string;
  balance: { owner_user_id: string; available_credits: number };
  usage: UsageRecord[];
  entries: Array<{
    entry_id: string;
    owner_user_id: string;
    entry_type: string;
    credit_delta: number;
    reason: string;
    run_id: string | null;
    usage_id: string | null;
    created_at: string;
  }>;
};

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

function usage(overrides: Partial<UsageRecord> = {}): UsageRecord {
  return {
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
    ...overrides,
  };
}

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
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

async function waitForNoText(text: string): Promise<void> {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (!container?.textContent?.includes(text)) {
      return;
    }
    await flush();
  }
  throw new Error(`Expected not to find "${text}" in: ${container?.textContent ?? ""}`);
}

function renderHarness({
  fetchImpl,
  userId = "user_1",
  profiles = [agent()],
}: {
  fetchImpl: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
  userId?: string;
  profiles?: AgentProfile[];
}) {
  vi.stubGlobal("fetch", vi.fn(fetchImpl));
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const api = new SocialApiClient("https://social.example.test");

  function render(nextUserId: string) {
    root?.render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <AiUsagePage api={api} state={loopState(nextUserId)} profiles={profiles} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  act(() => render(userId));
  return { queryClient, rerender: (nextUserId: string) => act(() => render(nextUserId)) };
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

describe("AiUsagePage", () => {
  it("shows balance, aggregate token usage, reply count, gull totals, activity, and allowance history", async () => {
    const data: UsageResponse = {
      owner_user_id: "user_1",
      balance: { owner_user_id: "user_1", available_credits: 9800 },
      usage: [
        usage(),
        usage({
          usage_id: "usage_2",
          run_id: "run_2",
          agent_id: "agent_2",
          input_tokens: 60,
          output_tokens: 20,
          cached_tokens: 0,
          estimated_cost_units: 80,
          created_at: "2026-10-17T10:00:00Z",
        }),
      ],
      entries: [
        {
          entry_id: "entry_1",
          owner_user_id: "user_1",
          entry_type: "credit_grant",
          credit_delta: 10000,
          reason: "Monthly allowance",
          run_id: null,
          usage_id: null,
          created_at: "2026-10-17T08:00:00Z",
        },
        {
          entry_id: "entry_2",
          owner_user_id: "user_1",
          entry_type: "ai_run_charge",
          credit_delta: -200,
          reason: "AI reply",
          run_id: "run_2",
          usage_id: "usage_2",
          created_at: "2026-10-17T10:00:00Z",
        },
      ],
    };
    renderHarness({
      profiles: [agent(), agent({ agent_id: "agent_2", display_name: "Writer" })],
      fetchImpl: async () => response(data),
    });

    await waitForText("AI Usage");
    await waitForText("9,800");
    expect(container?.textContent).toContain("Available tokens");
    expect(container?.textContent).toContain("Tokens used");
    expect(container?.textContent).toContain("220");
    expect(container?.textContent).toContain("AI requests");
    expect(container?.textContent).toContain("2");
    expect(container?.textContent).toContain("Researcher");
    expect(container?.textContent).toContain("Writer");
    expect(container?.textContent).toContain("Monthly allowance");
    expect(container?.textContent).toContain("AI usage");
    expect(container?.textContent).toMatch(/input\s*100/i);
    expect(container?.textContent).toMatch(/output\s*40/i);
  });

  it("requests the active owner's private usage and never shows another owner's data after a switch", async () => {
    const requests: string[] = [];
    const deferred: { resolve?: (result: Response) => void } = {};
    const firstResponse = new Promise<Response>((resolve) => {
      deferred.resolve = resolve;
    });
    const secondData: UsageResponse = {
      owner_user_id: "user_2",
      balance: { owner_user_id: "user_2", available_credits: 55 },
      usage: [],
      entries: [],
    };
    const harness = renderHarness({
      userId: "user_1",
      fetchImpl: async (input) => {
        const url = String(input);
        requests.push(url);
        return url.includes("user_1") ? firstResponse : response(secondData);
      },
    });
    expect(container?.textContent).toContain("Loading your AI usage");
    await flush();
    harness.rerender("user_2");
    await waitForText("55");
    expect(requests.some((url) => url.includes("owner_user_id=user_1"))).toBe(true);
    expect(requests.some((url) => url.includes("owner_user_id=user_2"))).toBe(true);
    expect(container?.textContent).not.toContain("user_1");
    deferred.resolve?.(
      response({
        owner_user_id: "user_1",
        balance: { owner_user_id: "user_1", available_credits: 99999 },
        usage: [usage({ owner_user_id: "user_1" })],
        entries: [],
      }),
    );
    await flush();
    expect(container?.textContent).not.toContain("99,999");
    expect(container?.textContent).toContain("55");
  });

  it("shows an explicit empty state without inventing zero usage", async () => {
    renderHarness({
      fetchImpl: async () =>
        response({
          owner_user_id: "user_1",
          balance: { owner_user_id: "user_1", available_credits: 0 },
          usage: [],
          entries: [],
        } satisfies UsageResponse),
    });
    await waitForText("AI Usage");
    await waitForText("No AI activity yet");
    expect(container?.textContent).toContain("No AI allowance yet");
    expect(container?.textContent).toContain("Available tokens");
  });

  it("shows loading and server errors, then retries successfully", async () => {
    let attempts = 0;
    renderHarness({
      fetchImpl: async () => {
        attempts += 1;
        if (attempts === 1) {
          return response({ error: "usage unavailable" }, 503);
        }
        return response({
          owner_user_id: "user_1",
          balance: { owner_user_id: "user_1", available_credits: 12 },
          usage: [],
          entries: [],
        } satisfies UsageResponse);
      },
    });
    await waitForText("Could not load AI usage.");
    const retry = Array.from(container!.querySelectorAll("button")).find((item) => item.textContent?.trim() === "Try again");
    expect(retry).toBeInstanceOf(HTMLButtonElement);
    await act(async () => {
      (retry as HTMLButtonElement).click();
    });
    await waitForText("12");
    expect(attempts).toBe(2);
  });

  it("handles forbidden usage access without exposing misleading account data", async () => {
    renderHarness({ fetchImpl: async () => response({ error: "forbidden" }, 403) });
    await waitForText("Could not load AI usage.");
    expect(container?.textContent).toMatch(/permission|access|forbidden/i);
    await waitForNoText("Available tokens0");
    expect(container?.textContent).not.toContain("No AI activity yet");
  });

  it("refreshes the owner-scoped usage snapshot", async () => {
    let calls = 0;
    renderHarness({
      fetchImpl: async () => {
        calls += 1;
        return response({
          owner_user_id: "user_1",
          balance: { owner_user_id: "user_1", available_credits: calls === 1 ? 12 : 24 },
          usage: [],
          entries: [],
        } satisfies UsageResponse);
      },
    });
    await waitForText("12");
    const refresh = Array.from(container!.querySelectorAll("button")).find(
      (item) => item.textContent?.trim() === "Refresh",
    );
    expect(refresh).toBeInstanceOf(HTMLButtonElement);
    await act(async () => {
      (refresh as HTMLButtonElement).click();
    });
    await waitForText("24");
    expect(calls).toBe(2);
  });
});

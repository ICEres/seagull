// Tests for the Agent Request client.
// Run: node --test test/  (Node 22+, native type stripping)

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  AgentRequestClient,
  AgentRequestError,
  TASK_INACTIVE_STATES,
  isTaskActive,
  nextTaskStates,
  taskLifecycleAllows,
  type TaskState,
} from "../src/agent-request.ts";

interface CapturedCall {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

/** Mock transport capturing each call and replaying queued responses. */
function mockFetch(responses: Array<() => Response>) {
  const calls: CapturedCall[] = [];
  let index = 0;

  const fetchImpl = (async (url: string | URL | Request, init?: RequestInit) => {
    const headers: Record<string, string> = {};
    new Headers(init?.headers).forEach((value, key) => {
      headers[key] = value;
    });
    calls.push({
      url: String(url),
      method: init?.method ?? "GET",
      headers,
      body: init?.body === undefined ? undefined : JSON.parse(String(init.body)),
    });
    const factory = responses[Math.min(index, responses.length - 1)];
    index += 1;
    return factory();
  }) as typeof globalThis.fetch;

  return { fetchImpl, calls };
}

function jsonResponse(body: unknown, status = 200): () => Response {
  return () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
}

const TASK = {
  task_id: "task_1",
  thread_id: "thread_1",
  state: "requested" as TaskState,
  objective: "Summarize the release notes",
};

describe("task lifecycle", () => {
  it("mirrors the protocol transition table", () => {
    assert.equal(taskLifecycleAllows("requested", "quoted"), true);
    assert.equal(taskLifecycleAllows("requested", "released"), false);
    assert.equal(taskLifecycleAllows("running", "failed"), true);
    // A finished request is terminal.
    assert.deepEqual(nextTaskStates("completed"), []);
    // ...except a failure, which can still be disputed.
    assert.deepEqual(nextTaskStates("failed"), ["disputed"]);
  });

  it("classifies active and inactive states", () => {
    assert.equal(isTaskActive("running"), true);
    assert.equal(isTaskActive("completed"), false);
    assert.equal(TASK_INACTIVE_STATES.has("canceled"), true);
    assert.equal(TASK_INACTIVE_STATES.has("accepted"), false);
  });
});

describe("AgentRequestClient", () => {
  it("opens a request against the hub's /tasks route", async () => {
    const { fetchImpl, calls } = mockFetch([
      jsonResponse({ created: true, task: TASK, task_id: "task_1", thread_id: "thread_1" }, 201),
    ]);
    const client = new AgentRequestClient({ baseUrl: "https://hub.example/", fetchImpl });

    const result = await client.createTask({
      requester_handle: "@alice:gulls.ai",
      recipient_handle: "@worker:gulls.ai",
      objective: "Summarize the release notes",
    });

    assert.equal(result.task_id, "task_1");
    assert.equal(calls[0].method, "POST");
    // Trailing slash on the base URL must not double up.
    assert.equal(calls[0].url, "https://hub.example/tasks");
    assert.deepEqual(calls[0].body, {
      requester_handle: "@alice:gulls.ai",
      recipient_handle: "@worker:gulls.ai",
      objective: "Summarize the release notes",
    });
  });

  it("sends the bearer token when one is available", async () => {
    const { fetchImpl, calls } = mockFetch([jsonResponse({ task: TASK })]);
    const client = new AgentRequestClient({
      baseUrl: "https://hub.example",
      getAuthToken: () => "token-abc",
      fetchImpl,
    });

    await client.readTask("task_1");

    assert.equal(calls[0].headers.authorization, "Bearer token-abc");
  });

  it("percent-encodes task ids in the path", async () => {
    const { fetchImpl, calls } = mockFetch([jsonResponse({ task: TASK })]);
    const client = new AgentRequestClient({ baseUrl: "https://hub.example", fetchImpl });

    await client.acceptTask("task/../admin", "@worker:gulls.ai");

    assert.equal(calls[0].url, "https://hub.example/tasks/task%2F..%2Fadmin/accept");
  });

  it("refuses an impossible transition without calling the hub", async () => {
    const { fetchImpl, calls } = mockFetch([jsonResponse({ task: TASK })]);
    const client = new AgentRequestClient({ baseUrl: "https://hub.example", fetchImpl });

    await assert.rejects(
      () => client.updateTaskState("task_1", "released", { from: "requested" }),
      (error: unknown) => {
        assert.ok(error instanceof AgentRequestError);
        assert.equal(error.code, "invalid_transition");
        return true;
      },
    );
    // gulls is still the authority, but there is no point asking.
    assert.equal(calls.length, 0);
  });

  it("allows a legal transition through to the hub", async () => {
    const { fetchImpl, calls } = mockFetch([
      jsonResponse({ task: { ...TASK, state: "quoted" } }),
    ]);
    const client = new AgentRequestClient({ baseUrl: "https://hub.example", fetchImpl });

    const result = await client.updateTaskState("task_1", "quoted", { from: "requested" });

    assert.equal(result.task.state, "quoted");
    assert.equal(calls[0].url, "https://hub.example/tasks/task_1/status");
    assert.deepEqual(calls[0].body, { state: "quoted" });
  });

  it("surfaces hub errors as AgentRequestError", async () => {
    const { fetchImpl } = mockFetch([
      jsonResponse({ error: "forbidden", message: "relationship policy blocked" }, 403),
    ]);
    const client = new AgentRequestClient({ baseUrl: "https://hub.example", fetchImpl });

    await assert.rejects(
      () => client.readTask("task_1"),
      (error: unknown) => {
        assert.ok(error instanceof AgentRequestError);
        assert.equal(error.status, 403);
        assert.equal(error.code, "forbidden");
        assert.equal(error.message, "relationship policy blocked");
        return true;
      },
    );
  });

  it("reports a network failure rather than throwing raw", async () => {
    const fetchImpl = (async () => {
      throw new Error("connection reset");
    }) as typeof globalThis.fetch;
    const client = new AgentRequestClient({ baseUrl: "https://hub.example", fetchImpl });

    await assert.rejects(
      () => client.readTask("task_1"),
      (error: unknown) => {
        assert.ok(error instanceof AgentRequestError);
        assert.equal(error.code, "network_error");
        return true;
      },
    );
  });

  it("lists the requests carried on a thread", async () => {
    const { fetchImpl, calls } = mockFetch([
      jsonResponse({ thread_id: "thread_1", tasks: [TASK] }),
    ]);
    const client = new AgentRequestClient({ baseUrl: "https://hub.example", fetchImpl });

    const result = await client.listThreadTasks("thread_1", { limit: 10 });

    assert.equal(result.tasks.length, 1);
    assert.equal(calls[0].url, "https://hub.example/threads/thread_1/tasks?limit=10");
  });
});

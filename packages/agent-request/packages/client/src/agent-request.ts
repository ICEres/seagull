// Agent Request: the Request/Tasking product interface.
//
// Agent Request is a sibling product layer over gulls, not a second message
// transport. Every call here goes to the shared message hub over its existing
// /tasks routes; the durable task record, its lifecycle, escrow, and audit
// stay in gulls. This package owns only the product-facing shape of the
// interaction: what a request looks like to a human or agent surface, and
// which actions are available next.
//
// Spec: packages/agent-request/docs/spec.md

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

/** Mirrors seagull_protocol.work.TaskState. */
export type TaskState =
  | "requested"
  | "quoted"
  | "needs_approval"
  | "approved"
  | "escrowed"
  | "accepted"
  | "running"
  | "result_ready"
  | "result_accepted"
  | "released"
  | "completed"
  | "canceled"
  | "disputed"
  | "refused"
  | "failed";

/**
 * Mirrors TASK_LIFECYCLE_TRANSITIONS in
 * packages/gulls/packages/protocol/src/seagull_protocol/work.py.
 *
 * gulls remains the authority: the hub re-checks every transition. This copy
 * exists so a product surface can grey out an impossible action instead of
 * round-tripping to be told no.
 */
export const TASK_LIFECYCLE_TRANSITIONS: Readonly<Record<TaskState, readonly TaskState[]>> =
  Object.freeze({
    requested: ["quoted", "needs_approval", "accepted", "canceled", "refused"],
    quoted: ["needs_approval", "approved", "canceled", "refused"],
    needs_approval: ["approved", "canceled", "refused"],
    approved: ["escrowed", "accepted", "canceled"],
    escrowed: ["accepted", "running", "canceled", "disputed"],
    accepted: ["running", "result_ready", "completed", "canceled", "refused"],
    running: ["result_ready", "completed", "failed", "disputed"],
    result_ready: ["result_accepted", "completed", "disputed"],
    result_accepted: ["released", "completed", "disputed"],
    released: ["completed"],
    disputed: ["result_accepted", "released", "completed", "canceled"],
    completed: [],
    canceled: [],
    refused: [],
    failed: ["disputed"],
  });

/** States in which a request is finished and needs no further action. */
export const TASK_INACTIVE_STATES: ReadonlySet<TaskState> = new Set<TaskState>([
  "released",
  "completed",
  "canceled",
  "refused",
  "failed",
]);

export function isTaskActive(state: TaskState): boolean {
  return !TASK_INACTIVE_STATES.has(state);
}

export function taskLifecycleAllows(current: TaskState, next: TaskState): boolean {
  return (TASK_LIFECYCLE_TRANSITIONS[current] ?? []).includes(next);
}

export function nextTaskStates(current: TaskState): readonly TaskState[] {
  return TASK_LIFECYCLE_TRANSITIONS[current] ?? [];
}

// ---------------------------------------------------------------------------
// Records
// ---------------------------------------------------------------------------

/** Shape returned by the hub's task_to_dict. */
export interface AgentTask {
  task_id: string;
  thread_id: string;
  requester_agent_id: string;
  recipient_agent_id: string;
  objective: string;
  request_message_id: string;
  context_refs: string[];
  context_pack_id: string | null;
  context_pack_ref: string | null;
  input_ref: string | null;
  stream_id: string | null;
  allowed_tool_names: string[];
  allowed_use_terms: string[];
  tool_grant_ids: string[];
  quote_ids: string[];
  escrow_ids: string[];
  capacity_policy_ids: string[];
  state: TaskState;
  policy_decision_id: string | null;
  accepted_by_agent_id: string | null;
  result_message_id: string | null;
  result_ref: string | null;
  artifact_refs: string[];
  tool_request_ids: string[];
  created_at: string | null;
  updated_at: string | null;
}

export interface CreateTaskRequest {
  requester_handle: string;
  recipient_handle: string;
  objective: string;
  thread_id?: string;
  context_refs?: string[];
  context_pack_id?: string;
  context_pack_ref?: string;
  input_ref?: string;
  stream_id?: string;
  allowed_tool_names?: string[];
  allowed_use_terms?: string[];
  idempotency_key?: string;
}

export interface CreateTaskResult {
  created: boolean;
  task: AgentTask;
  task_id: string;
  thread_id: string;
}

export interface ReturnResultRequest {
  responder_handle: string;
  state: TaskState;
  content?: string;
  content_ref?: string;
  artifact_refs?: string[];
  tool_use_summary_refs?: string[];
  error?: string;
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

export class AgentRequestError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "AgentRequestError";
    this.status = status;
    this.code = code;
  }
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

type FetchLike = typeof globalThis.fetch;

export interface AgentRequestClientOptions {
  /** Base URL of the gulls message hub. */
  baseUrl: string;
  /** Bearer token; called per request so a refreshed token is picked up. */
  getAuthToken?: () => string | null;
  /** Injectable for tests. */
  fetchImpl?: FetchLike;
}

/**
 * Thin product-layer client over the hub's task routes.
 *
 * Route paths are unchanged from the hub's existing surface -- terminology.md
 * defers API renames to a separate migration.
 */
export class AgentRequestClient {
  private readonly baseUrl: string;
  private readonly getAuthToken?: () => string | null;
  private readonly fetchImpl: FetchLike;

  constructor(options: AgentRequestClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.getAuthToken = options.getAuthToken;
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch;
  }

  /** Open a request. The hub creates the durable task and its Inbox message. */
  async createTask(request: CreateTaskRequest): Promise<CreateTaskResult> {
    return this.request<CreateTaskResult>("POST", "/tasks", request);
  }

  async readTask(taskId: string): Promise<{ task: AgentTask }> {
    return this.request<{ task: AgentTask }>("GET", `/tasks/${encodeURIComponent(taskId)}`);
  }

  async acceptTask(taskId: string, workerHandle: string): Promise<{ task: AgentTask }> {
    return this.request<{ task: AgentTask }>(
      "POST",
      `/tasks/${encodeURIComponent(taskId)}/accept`,
      { worker_handle: workerHandle },
    );
  }

  /**
   * Advance a request's state. Rejects locally when the lifecycle forbids the
   * move, so an impossible action never reaches the hub.
   */
  async updateTaskState(
    taskId: string,
    next: TaskState,
    options: { from?: TaskState } = {},
  ): Promise<{ task: AgentTask }> {
    if (options.from !== undefined && !taskLifecycleAllows(options.from, next)) {
      throw new AgentRequestError(
        400,
        "invalid_transition",
        `task cannot move from ${options.from} to ${next}`,
      );
    }
    return this.request<{ task: AgentTask }>(
      "POST",
      `/tasks/${encodeURIComponent(taskId)}/status`,
      { state: next },
    );
  }

  async returnResult(taskId: string, result: ReturnResultRequest): Promise<{ task: AgentTask }> {
    return this.request<{ task: AgentTask }>(
      "POST",
      `/tasks/${encodeURIComponent(taskId)}/results`,
      result,
    );
  }

  /** Requests carried on one thread -- the hub's thread-scoped listing. */
  async listThreadTasks(
    threadId: string,
    options: { limit?: number } = {},
  ): Promise<{ thread_id: string; tasks: AgentTask[] }> {
    const query = options.limit === undefined ? "" : `?limit=${options.limit}`;
    return this.request<{ thread_id: string; tasks: AgentTask[] }>(
      "GET",
      `/threads/${encodeURIComponent(threadId)}/tasks${query}`,
    );
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers = new Headers();
    const init: RequestInit = { method, headers };

    if (body !== undefined) {
      headers.set("content-type", "application/json");
      init.body = JSON.stringify(body);
    }
    const token = this.getAuthToken?.();
    if (token) {
      headers.set("authorization", `Bearer ${token}`);
    }

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, init);
    } catch (cause) {
      throw new AgentRequestError(0, "network_error", `agent request failed: ${String(cause)}`);
    }

    const text = await response.text();
    let payload: unknown = {};
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        throw new AgentRequestError(
          response.status,
          "invalid_response",
          "agent request returned a non-JSON response",
        );
      }
    }

    if (!response.ok) {
      const error = payload as { error?: string; message?: string };
      throw new AgentRequestError(
        response.status,
        error.error ?? "request_failed",
        error.message ?? `agent request failed with status ${response.status}`,
      );
    }

    return payload as T;
  }
}

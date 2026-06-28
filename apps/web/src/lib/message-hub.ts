import { trimBaseUrl } from "./api";

export const DEFAULT_MESSAGE_API_URL = "http://localhost:8200";

type RequestInitJson = Omit<RequestInit, "body"> & {
  body?: unknown;
};

type ErrorPayload = {
  error?: string;
  message?: string;
};

export type MessageHubHealth = {
  ok: boolean;
  app: string;
  storage: string;
};

export type MessageHubAgent = {
  agent_id: string;
  handle: string;
  display_name: string | null;
  capabilities: string[];
  status: string;
  trigger_mode: string;
  webhook_enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type MessageRef = {
  type: string;
  url?: string;
  find?: string;
  remember_as?: string;
};

export type PayloadRecord = {
  content_ref: string;
  media_type: string;
  byte_length: number;
  hash: string;
  compression: string;
  compressed_byte_length: number;
  compressed_hash?: string | null;
  ttl_expires_at?: string | null;
  retention_state: string;
  access_scope: string;
  fetch_policy_ref?: string | null;
  chunk_manifest_ref?: string | null;
  storage_provider: string;
  storage_ref?: string | null;
  created_at: string;
};

export type CreatePayloadResult = {
  content_ref: string;
  payload: PayloadRecord;
};

export type ReadPayloadResult = {
  content_ref: string;
  payload: PayloadRecord;
  content?: string;
  content_bytes?: unknown;
};

export type WorkflowTraceEntry = {
  hook: string;
  runtime: string;
  action: string;
  actor?: string;
  changed?: string[];
  note?: string;
  created_at: string;
};

export type ActionRequest = {
  action_request_id: string;
  type: string;
  target?: string;
  runtime: string;
  requires_approval: boolean;
  status: string;
  created_at: string;
};

export type HubMessage = {
  message_id: string;
  thread_id: string;
  sender_agent_id: string;
  sender_handle?: string;
  recipient_agent_ids?: string[];
  recipient_handles?: string[];
  intent: string;
  visibility: string;
  content_inline?: string;
  content_ref?: string;
  refs?: MessageRef[];
  schema_version: string;
  safety_status: string;
  created_at: string;
};

export type HubDelivery = {
  delivery_id: string;
  message_id: string;
  thread_id: string;
  sender_agent_id: string;
  sender_handle?: string;
  recipient_agent_id: string;
  recipient_handle?: string;
  status: string;
  retry_count: number;
  last_error?: string;
  current_content_inline?: string;
  current_content_ref?: string;
  refs?: MessageRef[];
  workflow_trace?: WorkflowTraceEntry[];
  current_stage?: string;
  action_request?: ActionRequest;
  created_at: string;
  updated_at: string;
  acked_at?: string;
};

export type InboxItem = {
  delivery: HubDelivery;
  message: HubMessage;
  current_message?: {
    content_inline?: string;
    content_ref?: string;
    refs?: MessageRef[];
  };
};

export type RoutingRule = {
  rule_id: string;
  name: string;
  mode: string;
  route_to_handles: string[];
  url_contains: string[];
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type SendMessageResult = {
  message: HubMessage;
  thread_id: string;
  deliveries: HubDelivery[];
};

export type DecisionResult = {
  delivery: HubDelivery;
  reply: SendMessageResult | null;
  action_request: ActionRequest | null;
};

export class MessageHubError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "MessageHubError";
    this.status = status;
    this.code = code;
  }
}

export class MessageHubClient {
  readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = trimBaseUrl(baseUrl);
  }

  health(): Promise<MessageHubHealth> {
    return this.request("/health");
  }

  registerAgent(body: {
    handle: string;
    display_name?: string;
    capabilities?: string[];
  }): Promise<{ created: boolean; agent: MessageHubAgent }> {
    return this.request("/agents", { method: "POST", body });
  }

  getInbox(handle: string, limit = 20): Promise<{ agent: MessageHubAgent; items: InboxItem[] }> {
    const query = new URLSearchParams({ limit: String(limit) });
    return this.request(`/agents/${encodeURIComponent(handle)}/inbox?${query.toString()}`);
  }

  createPayload(body: {
    content: string;
    media_type?: string;
    access_scope?: string;
    ttl_expires_at?: string;
  }): Promise<CreatePayloadResult> {
    return this.request("/payloads", { method: "POST", body });
  }

  readPayload(contentRef: string): Promise<ReadPayloadResult> {
    const query = new URLSearchParams({ content_ref: contentRef });
    return this.request(`/payloads?${query.toString()}`);
  }

  createMessage(body: {
    sender_handle: string;
    recipient_handles: string[];
    content?: string;
    content_ref?: string;
    refs?: MessageRef[];
    intent?: string;
    visibility?: string;
    thread_id?: string;
    idempotency_key?: string;
  }): Promise<SendMessageResult> {
    return this.request("/messages", { method: "POST", body });
  }

  listRoutingRules(): Promise<{ items: RoutingRule[] }> {
    return this.request("/routing-rules");
  }

  createRoutingRule(body: {
    name: string;
    mode: string;
    route_to_handles: string[];
    url_contains: string[];
    enabled?: boolean;
  }): Promise<{ created: boolean; routing_rule: RoutingRule }> {
    return this.request("/routing-rules", { method: "POST", body });
  }

  submitHookResult(
    deliveryId: string,
    body: {
      hook: string;
      runtime: string;
      actor?: string;
      content?: string;
      content_ref?: string;
      current_content_ref?: string;
      refs?: MessageRef[];
      action?: string;
      note?: string;
    },
  ): Promise<{ delivery: HubDelivery }> {
    return this.request(`/deliveries/${encodeURIComponent(deliveryId)}/hook-results`, {
      method: "POST",
      body,
    });
  }

  submitDecision(
    deliveryId: string,
    body: {
      agent_handle: string;
      decision: string;
      content?: string;
      content_ref?: string;
      refs?: MessageRef[];
      action_type?: string;
      action_target?: string;
      action_runtime?: string;
      requires_approval?: boolean;
      note?: string;
    },
  ): Promise<DecisionResult> {
    return this.request(`/deliveries/${encodeURIComponent(deliveryId)}/decision`, {
      method: "POST",
      body,
    });
  }

  private async request<T>(path: string, init: RequestInitJson = {}): Promise<T> {
    const { body, ...fetchInit } = init;
    const headers = new Headers(init.headers);
    const requestInit: RequestInit = {
      ...fetchInit,
      headers,
    };

    if (body !== undefined) {
      headers.set("content-type", "application/json");
      requestInit.body = JSON.stringify(body);
    }

    const response = await fetch(`${this.baseUrl}${path}`, requestInit);
    const text = await response.text();
    const payload = text ? safeJson(text) : {};

    if (!response.ok) {
      const errorPayload = payload as ErrorPayload;
      throw new MessageHubError(
        response.status,
        errorPayload.error ?? "request_failed",
        errorPayload.message ?? `Message API request failed with ${response.status}`,
      );
    }

    return payload as T;
  }
}

export function configuredMessageApiUrl(): string {
  const envUrl = import.meta.env.VITE_MESSAGE_API_URL;
  const runtimeUrl = window.SEAGULL_CONFIG?.messageApiUrl;
  return trimBaseUrl(envUrl || runtimeUrl || DEFAULT_MESSAGE_API_URL);
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return {};
  }
}

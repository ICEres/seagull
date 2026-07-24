import { ApiError, JsonApiClient, trimBaseUrl } from "./http";

export const DEFAULT_MESSAGE_API_URL = "http://localhost:8200";

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

export type ContactExplanation = {
  explanation_id: string;
  delivery_id: string;
  message_id: string;
  thread_id: string;
  requester_agent_id: string;
  requester_handle: string;
  recipient_agent_id: string;
  recipient_handle: string;
  answering_asset_handle: string;
  relationship: string;
  reason: string;
  allowed_reason: string;
  shared_context_summary: string;
  shared_context_refs: string[];
  pending_action: string | null;
  current_stage: string;
  policy_refs: string[];
  audit_event_refs: string[];
  created_at: string;
};

export class MessageHubError extends ApiError {
  constructor(status: number, code: string, message: string) {
    super(status, code, message, "message-hub");
    this.name = "MessageHubError";
  }
}

export class MessageHubClient extends JsonApiClient {
  readonly authToken: string | null;

  constructor(baseUrl: string, authToken: string | null = null) {
    const normalizedToken = authToken?.trim() || null;
    super(baseUrl, () => normalizedToken);
    this.authToken = normalizedToken;
  }

  protected override get serviceLabel(): string {
    return "Message API";
  }

  protected override createError(status: number, code: string, message: string): ApiError {
    return new MessageHubError(status, code, message);
  }

  health(): Promise<MessageHubHealth> {
    return this.request("GET", "/health");
  }

  registerAgent(body: {
    handle: string;
    display_name?: string;
    capabilities?: string[];
  }): Promise<{ created: boolean; agent: MessageHubAgent }> {
    return this.request("POST", "/agents", body);
  }

  getInbox(handle: string, limit = 20): Promise<{ agent: MessageHubAgent; items: InboxItem[] }> {
    const query = new URLSearchParams({ limit: String(limit) });
    return this.request("GET", `/agents/${encodeURIComponent(handle)}/inbox?${query.toString()}`);
  }

  createPayload(body: {
    content: string;
    media_type?: string;
    access_scope?: string;
    ttl_expires_at?: string;
  }): Promise<CreatePayloadResult> {
    return this.request("POST", "/payloads", body);
  }

  readPayload(contentRef: string): Promise<ReadPayloadResult> {
    const query = new URLSearchParams({ content_ref: contentRef });
    return this.request("GET", `/payloads?${query.toString()}`);
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
    return this.request("POST", "/messages", body);
  }

  listRoutingRules(): Promise<{ items: RoutingRule[] }> {
    return this.request("GET", "/routing-rules");
  }

  createRoutingRule(body: {
    name: string;
    mode: string;
    route_to_handles: string[];
    url_contains: string[];
    enabled?: boolean;
  }): Promise<{ created: boolean; routing_rule: RoutingRule }> {
    return this.request("POST", "/routing-rules", body);
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
    return this.request("POST", `/deliveries/${encodeURIComponent(deliveryId)}/hook-results`, body);
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
    return this.request("POST", `/deliveries/${encodeURIComponent(deliveryId)}/decision`, body);
  }

  explainContact(deliveryId: string): Promise<{ explanation: ContactExplanation }> {
    return this.request("GET", `/deliveries/${encodeURIComponent(deliveryId)}/contact-explanation`);
  }
}

export function configuredMessageApiUrl(): string {
  const envUrl = import.meta.env.VITE_MESSAGE_API_URL;
  const runtimeUrl = window.SEAGULL_CONFIG?.messageApiUrl;
  return trimBaseUrl(envUrl || runtimeUrl || DEFAULT_MESSAGE_API_URL);
}

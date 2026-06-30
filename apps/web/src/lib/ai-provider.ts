export const DEFAULT_AI_PROVIDER_API_URL = "http://localhost:8400";

type RequestInitJson = Omit<RequestInit, "body"> & {
  body?: unknown;
};

type ErrorPayload = {
  error?: string;
  message?: string;
};

export type AiProviderHealth = {
  ok: boolean;
  app: string;
  storage: string;
};

export type ProviderConfig = {
  provider_config_id: string;
  provider: string;
  enabled: boolean;
  allowed_models: string[];
  secret_ref: string | null;
  region: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type ServerCreditBalance = {
  available_credits: number;
};

export type ServerCreditLedgerEntry = {
  entry_id: string;
  entry_type: string;
  credit_delta: number;
  reason: string;
  admin_actor_id: string;
  owner_user_id: string | null;
  user_credit_entry_id: string | null;
  created_at: string | null;
};

export type AdminAuditEvent = {
  audit_id: string;
  admin_actor_id: string;
  action: string;
  target_type: string;
  target_id: string;
  reason: string;
  metadata: Record<string, string>;
  created_at: string | null;
};

export class AiProviderApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "AiProviderApiError";
    this.status = status;
    this.code = code;
  }
}

export class AiProviderClient {
  readonly baseUrl: string;
  readonly authToken: string;

  constructor(baseUrl: string, authToken = "") {
    this.baseUrl = trimBaseUrl(baseUrl);
    this.authToken = authToken.trim();
  }

  health(): Promise<AiProviderHealth> {
    return this.request<AiProviderHealth>("/health");
  }

  listProviderConfigs(): Promise<{ provider_configs: ProviderConfig[] }> {
    return this.request("/admin/ai-providers");
  }

  saveProviderConfig(
    provider: string,
    body: {
      admin_actor_id: string;
      enabled: boolean;
      allowed_models: string[];
      secret_ref?: string | null;
      region?: string | null;
      reason?: string;
    },
  ): Promise<{ provider_config: ProviderConfig }> {
    return this.request(`/admin/ai-providers/${encodeURIComponent(provider)}`, {
      method: "POST",
      body,
    });
  }

  getServerCreditBalance(): Promise<{ balance: ServerCreditBalance }> {
    return this.request("/admin/ai-credits/server-balance");
  }

  listServerCreditLedger(): Promise<{ entries: ServerCreditLedgerEntry[] }> {
    return this.request("/admin/ai-credits/server-ledger");
  }

  grantServerCredits(body: {
    admin_actor_id: string;
    credit_amount: number;
    reason: string;
  }): Promise<{ entry: ServerCreditLedgerEntry }> {
    return this.request("/admin/ai-credits/server-grants", {
      method: "POST",
      body,
    });
  }

  listAdminAuditEvents(): Promise<{ events: AdminAuditEvent[] }> {
    return this.request("/admin/ai-audit-events");
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
    if (this.authToken) {
      headers.set("authorization", `Bearer ${this.authToken}`);
    }

    const response = await fetch(`${this.baseUrl}${path}`, requestInit);
    const text = await response.text();
    const payload = text ? parseJson(text, response.status) : {};

    if (!response.ok) {
      const errorPayload = payload as ErrorPayload;
      throw new AiProviderApiError(
        response.status,
        errorPayload.error ?? "request_failed",
        errorPayload.message ?? `AI provider request failed with ${response.status}`,
      );
    }

    return payload as T;
  }
}

export function configuredAiProviderApiUrl(): string {
  const envUrl = import.meta.env.VITE_AI_PROVIDER_API_URL;
  const runtimeUrl = window.SEAGULL_CONFIG?.aiProviderApiUrl;
  return trimBaseUrl(envUrl || runtimeUrl || DEFAULT_AI_PROVIDER_API_URL);
}

export function trimBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

function parseJson(text: string, status: number): unknown {
  try {
    return JSON.parse(text);
  } catch {
    throw new AiProviderApiError(status, "invalid_json", "AI provider returned invalid JSON.");
  }
}

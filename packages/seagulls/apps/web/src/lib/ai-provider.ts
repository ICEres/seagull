import { ApiError, JsonApiClient, trimBaseUrl } from "./http";

export const DEFAULT_AI_PROVIDER_API_URL = "http://localhost:8400";

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

export type AiUsageRecord = {
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
  created_at: string | null;
};

export type UserCreditLedgerEntry = {
  entry_id: string;
  owner_user_id: string;
  entry_type: "credit_grant" | "ai_run_charge";
  credit_delta: number;
  reason: string;
  run_id: string | null;
  usage_id: string | null;
  created_at: string | null;
};

export type MyAiUsage = {
  owner_user_id: string;
  balance: { owner_user_id: string; available_credits: number };
  usage: AiUsageRecord[];
  entries: UserCreditLedgerEntry[];
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

export class AiProviderApiError extends ApiError {
  constructor(status: number, code: string, message: string) {
    super(status, code, message, "ai-provider");
    this.name = "AiProviderApiError";
  }
}

export class AiProviderClient extends JsonApiClient {
  readonly authToken: string;

  constructor(baseUrl: string, authToken = "") {
    const normalizedToken = authToken.trim();
    super(baseUrl, () => normalizedToken);
    this.authToken = normalizedToken;
  }

  protected override get serviceLabel(): string {
    return "AI provider";
  }

  protected override createError(status: number, code: string, message: string): ApiError {
    return new AiProviderApiError(status, code, message);
  }

  health(): Promise<AiProviderHealth> {
    return this.request<AiProviderHealth>("GET", "/health");
  }

  listProviderConfigs(): Promise<{ provider_configs: ProviderConfig[] }> {
    return this.request("GET", "/admin/ai-providers");
  }

  saveProviderConfig(
    provider: string,
    body: {
      admin_actor_id: string;
      enabled: boolean;
      allowed_models: string[];
      secret_ref?: string | null;
      api_key?: string;
      region?: string | null;
      reason?: string;
    },
  ): Promise<{ provider_config: ProviderConfig }> {
    return this.request("POST", `/admin/ai-providers/${encodeURIComponent(provider)}`, body);
  }

  getServerCreditBalance(): Promise<{ balance: ServerCreditBalance }> {
    return this.request("GET", "/admin/ai-credits/server-balance");
  }

  listServerCreditLedger(): Promise<{ entries: ServerCreditLedgerEntry[] }> {
    return this.request("GET", "/admin/ai-credits/server-ledger");
  }

  grantServerCredits(body: {
    admin_actor_id: string;
    credit_amount: number;
    reason: string;
  }): Promise<{ entry: ServerCreditLedgerEntry }> {
    return this.request("POST", "/admin/ai-credits/server-grants", body);
  }

  listAdminAuditEvents(): Promise<{ events: AdminAuditEvent[] }> {
    return this.request("GET", "/admin/ai-audit-events");
  }
}

export function configuredAiProviderApiUrl(): string {
  const envUrl = import.meta.env.VITE_AI_PROVIDER_API_URL;
  const runtimeUrl = window.SEAGULL_CONFIG?.aiProviderApiUrl;
  return trimBaseUrl(envUrl || runtimeUrl || DEFAULT_AI_PROVIDER_API_URL);
}

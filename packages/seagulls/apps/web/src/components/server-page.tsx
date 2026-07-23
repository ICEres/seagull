import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  AiProviderApiError,
  AiProviderClient,
  type ProviderConfig,
} from "../lib/ai-provider";
import {
  MessageHubClient,
  MessageHubError,
  type MessageHubHealth,
  type RoutingRule,
} from "../lib/message-hub";
import { trimBaseUrl } from "../lib/api";
import type { AgentProfile, Health, ModerationRecord } from "../lib/social";
import { formatRelativeTime, parseCommaList } from "../lib/state";
import { Chip, EmptyState, SectionCard, type Notice } from "./shared";

const ADMIN_ACTOR_STORAGE_KEY = "seagull.web.ai_provider.admin_actor";

const PROVIDER_PRESETS = [
  {
    provider: "openai",
    label: "OpenAI",
    defaultModels: ["gpt-5.5", "gpt-5.4-mini"],
    reason: "enable openai",
  },
  {
    provider: "fake",
    label: "Fake",
    defaultModels: ["fake-small"],
    reason: "provider config update",
  },
] as const;

type AdminError = Error | AiProviderApiError | MessageHubError;

export function ServerPage({
  aiProviderApiUrl,
  authToken,
  messageApi,
  profiles,
  moderationRecords,
  socialHealth,
  messageHealth,
  apiUrl,
  onApplyApiUrl,
  onNotice,
}: {
  aiProviderApiUrl: string;
  authToken: string | null;
  messageApi: MessageHubClient;
  profiles: AgentProfile[];
  moderationRecords: ModerationRecord[];
  socialHealth: Health | undefined;
  messageHealth: MessageHubHealth | undefined;
  apiUrl: string;
  onApplyApiUrl: (nextUrl: string) => void;
  onNotice: (notice: Notice) => void;
}) {
  const adminReady = Boolean(authToken?.trim());
  const aiProvider = useMemo(
    () => new AiProviderClient(aiProviderApiUrl, authToken ?? ""),
    [aiProviderApiUrl, authToken],
  );

  const aiHealthQuery = useQuery({
    queryKey: ["ai-provider-health", aiProviderApiUrl],
    queryFn: () => aiProvider.health(),
  });

  return (
    <div className="mx-auto max-w-[940px]">
      <header className="mb-[18px] flex flex-wrap items-baseline gap-3">
        <h1 className="m-0 text-[1.4rem] font-extrabold tracking-[-0.02em]">
          Server<span className="text-accent">.</span>
        </h1>
        <span className="text-[0.84rem] font-bold text-faint">
          provider, credits, rules — the harbor your flock flies from
        </span>
      </header>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(300px,1fr))] items-start gap-3">
        <ProviderCard aiProvider={aiProvider} adminReady={adminReady} onNotice={onNotice} />
        <CreditsCard aiProvider={aiProvider} adminReady={adminReady} onNotice={onNotice} />
        <RoutingCard messageApi={messageApi} profiles={profiles} onNotice={onNotice} />
        <ModerationCard records={moderationRecords} />
        <AuditCard aiProvider={aiProvider} adminReady={adminReady} />
        <ConnectionCard
          apiUrl={apiUrl}
          onApplyApiUrl={onApplyApiUrl}
          socialHealth={socialHealth}
          messageHealth={messageHealth}
          aiHealthy={aiHealthQuery.data?.ok}
          aiChecking={aiHealthQuery.isLoading}
        />
      </div>
    </div>
  );
}

function AdminLocked() {
  return (
    <EmptyState
      title="Admin locked"
      detail="Sign in with a Cognito admin session to manage this harbor."
    />
  );
}

function ProviderCard({
  aiProvider,
  adminReady,
  onNotice,
}: {
  aiProvider: AiProviderClient;
  adminReady: boolean;
  onNotice: (notice: Notice) => void;
}) {
  const queryClient = useQueryClient();
  const [adminActorId, setAdminActorId] = useState(
    () => window.localStorage.getItem(ADMIN_ACTOR_STORAGE_KEY) ?? "server-owner",
  );
  const [provider, setProvider] = useState("fake");
  const [enabled, setEnabled] = useState(true);
  const [allowedModels, setAllowedModels] = useState("fake-small");
  const [apiKey, setApiKey] = useState("");
  // Carried through on save so editing a config never wipes its stored
  // secret reference or region.
  const [secretRef, setSecretRef] = useState("");
  const [region, setRegion] = useState("");
  const [saved, setSaved] = useState(false);

  const configsQuery = useQuery({
    queryKey: ["ai-provider-configs", aiProvider.baseUrl, aiProvider.authToken],
    queryFn: () => aiProvider.listProviderConfigs(),
    enabled: adminReady,
    retry: false,
  });
  const configs = configsQuery.data?.provider_configs ?? [];

  const saveMutation = useMutation({
    mutationFn: () => {
      const providerName = provider.trim().toLowerCase();
      window.localStorage.setItem(ADMIN_ACTOR_STORAGE_KEY, adminActorId.trim() || "server-owner");
      return aiProvider.saveProviderConfig(providerName, {
        admin_actor_id: adminActorId.trim() || "server-owner",
        enabled,
        allowed_models: parseCommaList(allowedModels),
        api_key: apiKey.trim() || undefined,
        secret_ref: secretRef.trim() || null,
        region: region.trim() || null,
        reason: "provider config update",
      });
    },
    onSuccess: (result) => {
      setApiKey("");
      setSecretRef(result.provider_config.secret_ref ?? "");
      setRegion(result.provider_config.region ?? "");
      setSaved(true);
      window.setTimeout(() => setSaved(false), 1800);
      onNotice({ tone: "ok", message: `${result.provider_config.provider} saved.` });
      void queryClient.invalidateQueries({ queryKey: ["ai-provider-configs"] });
      void queryClient.invalidateQueries({ queryKey: ["ai-provider-audit"] });
    },
    onError: (error: AdminError) => onNotice({ tone: "error", message: error.message }),
  });

  function editConfig(config: ProviderConfig) {
    setProvider(config.provider);
    setEnabled(config.enabled);
    setAllowedModels(config.allowed_models.join(", "));
    setApiKey("");
    setSecretRef(config.secret_ref ?? "");
    setRegion(config.region ?? "");
  }

  return (
    <SectionCard title="AI provider">
      {!adminReady ? (
        <AdminLocked />
      ) : (
        <>
          {configs.length > 0 ? (
            <div className="grid gap-1.5">
              {configs.map((config) => (
                <div key={config.provider_config_id} className="flex items-center gap-2 text-[0.82rem]">
                  <strong>{config.provider}</strong>
                  <Chip tone={config.enabled ? "accent" : "faint"}>{config.enabled ? "enabled" : "disabled"}</Chip>
                  <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-[0.74rem] text-faint">
                    {config.allowed_models.join(", ") || "all models"}
                  </span>
                  <button
                    type="button"
                    onClick={() => editConfig(config)}
                    className="border-0 bg-transparent p-0 text-[0.74rem] font-extrabold text-accent-strong hover:text-accent"
                  >
                    Edit
                  </button>
                </div>
              ))}
            </div>
          ) : null}
          <form
            className="grid w-full gap-2.5"
            onSubmit={(event: FormEvent<HTMLFormElement>) => {
              event.preventDefault();
              if (provider.trim()) {
                saveMutation.mutate();
              }
            }}
          >
            <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
              Provider
              <select
                value={PROVIDER_PRESETS.some((preset) => preset.provider === provider) ? provider : "custom"}
                onChange={(event) => {
                  const preset = PROVIDER_PRESETS.find((entry) => entry.provider === event.target.value);
                  if (preset) {
                    setProvider(preset.provider);
                    setAllowedModels(preset.defaultModels.join(", "));
                    setEnabled(true);
                    setSecretRef("");
                    setRegion("");
                  }
                }}
                className="bg-bg text-[0.88rem]"
              >
                {PROVIDER_PRESETS.map((preset) => (
                  <option key={preset.provider} value={preset.provider}>
                    {preset.label}
                  </option>
                ))}
                <option value="custom">Custom…</option>
              </select>
            </label>
            <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
              Provider id
              <input
                value={provider}
                onChange={(event) => setProvider(event.target.value)}
                spellCheck={false}
                className="bg-bg text-[0.88rem]"
              />
            </label>
            <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
              Models · comma separated
              <input
                value={allowedModels}
                onChange={(event) => setAllowedModels(event.target.value)}
                spellCheck={false}
                className="bg-bg text-[0.88rem]"
              />
            </label>
            <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
              API key
              <input
                type="password"
                autoComplete="new-password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder="sk-…"
                spellCheck={false}
                className="bg-bg text-[0.88rem]"
              />
            </label>
            <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
              Admin actor
              <input
                value={adminActorId}
                onChange={(event) => {
                  setAdminActorId(event.target.value);
                  // Persist immediately so credit grants pick up the actor
                  // without requiring a provider save first.
                  window.localStorage.setItem(
                    ADMIN_ACTOR_STORAGE_KEY,
                    event.target.value.trim() || "server-owner",
                  );
                }}
                spellCheck={false}
                className="bg-bg text-[0.88rem]"
              />
            </label>
            <label className="flex items-center gap-2 text-[0.78rem] font-extrabold text-muted">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
                className="h-4 w-4 min-h-4"
              />
              Enabled
            </label>
            <div className="flex items-center gap-2.5">
              <button
                type="submit"
                disabled={!provider.trim() || saveMutation.isPending}
                className="min-h-9 rounded-lg border-0 bg-accent px-4 text-[0.82rem] font-extrabold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
              >
                Save
              </button>
              {saved ? <span className="text-[0.78rem] font-extrabold text-ok">Saved ✓</span> : null}
            </div>
          </form>
        </>
      )}
    </SectionCard>
  );
}

function CreditsCard({
  aiProvider,
  adminReady,
  onNotice,
}: {
  aiProvider: AiProviderClient;
  adminReady: boolean;
  onNotice: (notice: Notice) => void;
}) {
  const queryClient = useQueryClient();
  const [amount, setAmount] = useState("10000");
  const [reason, setReason] = useState("Monthly top-up");

  const balanceQuery = useQuery({
    queryKey: ["ai-provider-server-balance", aiProvider.baseUrl, aiProvider.authToken],
    queryFn: () => aiProvider.getServerCreditBalance(),
    enabled: adminReady,
    retry: false,
  });
  const ledgerQuery = useQuery({
    queryKey: ["ai-provider-server-ledger", aiProvider.baseUrl, aiProvider.authToken],
    queryFn: () => aiProvider.listServerCreditLedger(),
    enabled: adminReady,
    retry: false,
  });
  const entries = ledgerQuery.data?.entries ?? [];

  const grantMutation = useMutation({
    mutationFn: () =>
      aiProvider.grantServerCredits({
        admin_actor_id: window.localStorage.getItem(ADMIN_ACTOR_STORAGE_KEY) ?? "server-owner",
        credit_amount: Number.parseInt(amount, 10),
        reason: reason.trim() || "server credit grant",
      }),
    onSuccess: (result) => {
      onNotice({ tone: "ok", message: `${result.entry.credit_delta} credits granted.` });
      void queryClient.invalidateQueries({ queryKey: ["ai-provider-server-balance"] });
      void queryClient.invalidateQueries({ queryKey: ["ai-provider-server-ledger"] });
      void queryClient.invalidateQueries({ queryKey: ["ai-provider-audit"] });
    },
    onError: (error: AdminError) => onNotice({ tone: "error", message: error.message }),
  });

  return (
    <SectionCard title="Credits">
      {!adminReady ? (
        <AdminLocked />
      ) : (
        <>
          <p className="m-0 text-[1.6rem] font-extrabold tracking-[-0.02em]">
            {balanceQuery.data ? balanceQuery.data.balance.available_credits.toLocaleString("en-US") : "…"}
            <span className="text-[0.8rem] font-extrabold text-faint"> credits</span>
          </p>
          <div className="grid gap-2">
            {entries
              .slice(-5)
              .reverse()
              .map((entry) => (
                <div key={entry.entry_id} className="flex items-baseline gap-2.5 text-[0.82rem]">
                  <strong
                    className="flex-none tabular-nums"
                    style={{ color: entry.credit_delta >= 0 ? "var(--ok)" : "var(--ink)" }}
                  >
                    {entry.credit_delta >= 0 ? `+${entry.credit_delta.toLocaleString("en-US")}` : entry.credit_delta.toLocaleString("en-US")}
                  </strong>
                  <span className="min-w-0 flex-1 text-body">{entry.reason}</span>
                  <span className="flex-none text-[0.72rem] font-extrabold text-faint">
                    {formatRelativeTime(entry.created_at)}
                  </span>
                </div>
              ))}
            {entries.length === 0 ? (
              <span className="text-[0.82rem] text-faint">No ledger entries yet.</span>
            ) : null}
          </div>
          <form
            className="grid grid-cols-[110px_minmax(0,1fr)_auto] items-end gap-2 max-[620px]:grid-cols-1"
            onSubmit={(event) => {
              event.preventDefault();
              if (Number.parseInt(amount, 10) > 0) {
                grantMutation.mutate();
              }
            }}
          >
            <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
              Amount
              <input
                type="number"
                min="1"
                step="1"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                className="bg-bg text-[0.88rem]"
              />
            </label>
            <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
              Reason
              <input
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                className="bg-bg text-[0.88rem]"
              />
            </label>
            <button
              type="submit"
              disabled={!(Number.parseInt(amount, 10) > 0) || grantMutation.isPending}
              className="min-h-[42px] rounded-lg border-0 bg-accent px-3.5 text-[0.82rem] font-extrabold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
            >
              Grant
            </button>
          </form>
        </>
      )}
    </SectionCard>
  );
}

function RoutingCard({
  messageApi,
  profiles,
  onNotice,
}: {
  messageApi: MessageHubClient;
  profiles: AgentProfile[];
  onNotice: (notice: Notice) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("Map links");
  const [mode, setMode] = useState("copy");
  const [routeToHandle, setRouteToHandle] = useState(profiles[0]?.handle ?? "");
  const [urlContains, setUrlContains] = useState("maps.google.com");

  const rulesQuery = useQuery({
    queryKey: ["message-routing-rules", messageApi.baseUrl],
    queryFn: () => messageApi.listRoutingRules(),
    retry: false,
  });
  const rules = rulesQuery.data?.items ?? [];

  const createMutation = useMutation({
    mutationFn: async () => {
      const handles = mode === "block" ? [] : [routeToHandle.trim()].filter(Boolean);
      for (const handle of handles) {
        const profile = profiles.find((item) => item.handle === handle);
        await messageApi.registerAgent({
          handle,
          display_name: profile?.display_name ?? undefined,
          capabilities: profile?.capabilities ?? [],
        });
      }
      return messageApi.createRoutingRule({
        name: name.trim(),
        mode,
        route_to_handles: handles,
        url_contains: parseCommaList(urlContains.toLowerCase()),
      });
    },
    onSuccess: () => {
      onNotice({ tone: "ok", message: "Routing rule created." });
      void queryClient.invalidateQueries({ queryKey: ["message-routing-rules"] });
    },
    onError: (error: AdminError) => onNotice({ tone: "error", message: error.message }),
  });

  return (
    <SectionCard title="Routing rules">
      <div className="grid gap-2.5">
        {rules.map((rule) => (
          <RoutingRuleRow key={rule.rule_id} rule={rule} />
        ))}
        {rules.length === 0 ? (
          <span className="text-[0.82rem] text-faint">
            {rulesQuery.isFetching ? "Checking the hub…" : "No routing rules yet."}
          </span>
        ) : null}
      </div>
      <form
        className="grid gap-2.5 border-t border-line pt-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim() && urlContains.trim() && (mode === "block" || routeToHandle.trim())) {
            createMutation.mutate();
          }
        }}
      >
        <div className="grid grid-cols-2 gap-2">
          <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
            Name
            <input value={name} onChange={(event) => setName(event.target.value)} className="bg-bg text-[0.88rem]" />
          </label>
          <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
            Mode
            <select value={mode} onChange={(event) => setMode(event.target.value)} className="bg-bg text-[0.88rem]">
              <option value="copy">copy</option>
              <option value="handoff">handoff</option>
              <option value="review">review</option>
              <option value="direct">direct</option>
              <option value="block">block</option>
            </select>
          </label>
        </div>
        <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
          Route to
          <input
            value={routeToHandle}
            onChange={(event) => setRouteToHandle(event.target.value)}
            list="routing-agent-handles"
            disabled={mode === "block"}
            spellCheck={false}
            className="bg-bg text-[0.88rem]"
          />
        </label>
        <datalist id="routing-agent-handles">
          {profiles.map((profile) => (
            <option value={profile.handle} key={profile.agent_id} />
          ))}
        </datalist>
        <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
          URL contains
          <input
            value={urlContains}
            onChange={(event) => setUrlContains(event.target.value)}
            spellCheck={false}
            className="bg-bg text-[0.88rem]"
          />
        </label>
        <button
          type="submit"
          disabled={
            !name.trim() || !urlContains.trim() || (mode !== "block" && !routeToHandle.trim()) || createMutation.isPending
          }
          className="min-h-9 w-fit rounded-lg border-0 bg-accent px-4 text-[0.82rem] font-extrabold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
        >
          Create rule
        </button>
      </form>
    </SectionCard>
  );
}

function RoutingRuleRow({ rule }: { rule: RoutingRule }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="min-w-0 flex-1 text-[0.82rem] leading-[1.4] text-body">
        <strong>{rule.name}</strong>
        <span className="text-faint"> · {rule.url_contains.join(", ")} → </span>
        {rule.mode === "block" ? "block" : rule.route_to_handles.join(", ") || "none"}
        <span className="text-faint"> ({rule.mode})</span>
      </span>
      <span
        role="switch"
        aria-checked={rule.enabled}
        aria-disabled="true"
        aria-label={`Rule ${rule.name} ${rule.enabled ? "enabled" : "disabled"}`}
        title="Rules are managed at creation time"
        className="relative h-5 w-9 flex-none cursor-default rounded-full transition-colors"
        style={{ background: rule.enabled ? "var(--accent)" : "var(--line)" }}
      >
        <span
          className="absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,0.25)] transition-all"
          style={{ left: rule.enabled ? 18 : 2 }}
        />
      </span>
    </div>
  );
}

function ModerationCard({ records }: { records: ModerationRecord[] }) {
  return (
    <SectionCard title="Moderation">
      <div className="grid gap-2.5">
        {records.slice(0, 6).map((record) => (
          <div key={record.moderation_id} className="flex flex-wrap items-center gap-2.5">
            <span className="min-w-0 flex-1 text-[0.82rem] leading-[1.4] text-body">
              <strong>{record.action}</strong> {record.target_type} · {record.target_id}
              <span className="block text-[0.74rem] text-faint">{record.reason}</span>
            </span>
            <Chip tone={record.status === "open" ? "amber" : "faint"}>{record.status}</Chip>
          </div>
        ))}
        {records.length === 0 ? <span className="text-[0.82rem] text-faint">A calm harbor — nothing flagged.</span> : null}
      </div>
    </SectionCard>
  );
}

function AuditCard({
  aiProvider,
  adminReady,
}: {
  aiProvider: AiProviderClient;
  adminReady: boolean;
}) {
  const auditQuery = useQuery({
    queryKey: ["ai-provider-audit", aiProvider.baseUrl, aiProvider.authToken],
    queryFn: () => aiProvider.listAdminAuditEvents(),
    enabled: adminReady,
    retry: false,
  });
  const events = auditQuery.data?.events ?? [];

  return (
    <SectionCard title="Audit">
      {!adminReady ? (
        <AdminLocked />
      ) : (
        <div className="grid gap-2.5">
          {events
            .slice(-6)
            .reverse()
            .map((event) => (
              <div key={event.audit_id} className="flex items-baseline gap-2.5 text-[0.82rem]">
                <span className="min-w-0 flex-1 text-body">
                  <strong>{event.action}</strong>
                  <span className="text-faint"> · {event.target_type}/{event.target_id}</span>
                  <span className="block text-[0.74rem] text-faint">{event.reason}</span>
                </span>
                <span className="flex-none text-[0.72rem] font-extrabold text-faint">
                  {formatRelativeTime(event.created_at)}
                </span>
              </div>
            ))}
          {events.length === 0 ? <span className="text-[0.82rem] text-faint">No admin writes yet.</span> : null}
        </div>
      )}
    </SectionCard>
  );
}

function ConnectionCard({
  apiUrl,
  onApplyApiUrl,
  socialHealth,
  messageHealth,
  aiHealthy,
  aiChecking,
}: {
  apiUrl: string;
  onApplyApiUrl: (nextUrl: string) => void;
  socialHealth: Health | undefined;
  messageHealth: MessageHubHealth | undefined;
  aiHealthy: boolean | undefined;
  aiChecking: boolean;
}) {
  const [draft, setDraft] = useState(apiUrl);

  const rows: Array<{ label: string; ok: boolean | undefined; detail: string }> = [
    { label: "Social API", ok: socialHealth?.ok, detail: socialHealth?.storage ?? "offline" },
    { label: "Message hub", ok: messageHealth?.ok, detail: messageHealth?.storage ?? "offline" },
    { label: "AI provider", ok: aiHealthy, detail: aiChecking ? "checking" : aiHealthy ? "ok" : "offline" },
  ];

  return (
    <SectionCard title="Connection">
      <div className="grid gap-2">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center gap-2 text-[0.82rem]">
            <span
              className="h-[7px] w-[7px] flex-none rounded-full"
              style={{ background: row.ok ? "var(--ok)" : "var(--faint)" }}
            />
            <strong className="flex-none">{row.label}</strong>
            <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-right text-faint">
              {row.detail}
            </span>
          </div>
        ))}
      </div>
      <form
        className="grid gap-2 border-t border-line pt-3"
        onSubmit={(event) => {
          event.preventDefault();
          onApplyApiUrl(trimBaseUrl(draft));
        }}
      >
        <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
          Social API endpoint
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            spellCheck={false}
            className="bg-bg text-[0.88rem]"
          />
        </label>
        <button
          type="submit"
          className="min-h-9 w-fit rounded-lg border-[1.5px] border-line bg-transparent px-3.5 text-[0.82rem] font-extrabold text-muted hover:border-accent hover:text-accent-strong"
        >
          Apply
        </button>
      </form>
    </SectionCard>
  );
}

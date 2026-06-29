import { Database, KeyRound, Save, ServerCog, ShieldCheck, Wallet } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  AiProviderApiError,
  AiProviderClient,
  type AdminAuditEvent,
  type ProviderConfig,
  type ServerCreditLedgerEntry,
} from "../lib/ai-provider";
import { formatTimestamp, parseCommaList } from "../lib/state";
import { EmptyState, StatusPill, type Notice } from "./shared";

const ADMIN_SECRET_STORAGE_KEY = "seagull.web.ai_provider.admin_secret";
const ADMIN_ACTOR_STORAGE_KEY = "seagull.web.ai_provider.admin_actor";

type AdminError = Error | AiProviderApiError;

export function AdminPage({
  aiProviderApiUrl,
  onNotice,
}: {
  aiProviderApiUrl: string;
  onNotice: (notice: Notice) => void;
}) {
  const queryClient = useQueryClient();
  const [adminSecret, setAdminSecret] = useState(() => window.localStorage.getItem(ADMIN_SECRET_STORAGE_KEY) ?? "");
  const [adminActorId, setAdminActorId] = useState(() => window.localStorage.getItem(ADMIN_ACTOR_STORAGE_KEY) ?? "server-owner");
  const [provider, setProvider] = useState("fake");
  const [enabled, setEnabled] = useState(true);
  const [allowedModels, setAllowedModels] = useState("fake-small");
  const [secretRef, setSecretRef] = useState("");
  const [region, setRegion] = useState("");
  const [reason, setReason] = useState("provider config update");
  const [serverCreditAmount, setServerCreditAmount] = useState("10000");
  const [serverCreditReason, setServerCreditReason] = useState("server credit grant");

  const adminReady = Boolean(adminSecret.trim());
  const aiProvider = useMemo(
    () => new AiProviderClient(aiProviderApiUrl, adminSecret),
    [aiProviderApiUrl, adminSecret],
  );

  const healthQuery = useQuery({
    queryKey: ["ai-provider-health", aiProviderApiUrl],
    queryFn: () => aiProvider.health(),
  });

  const providerConfigsQuery = useQuery({
    queryKey: ["ai-provider-configs", aiProviderApiUrl, adminSecret],
    queryFn: () => aiProvider.listProviderConfigs(),
    enabled: adminReady,
    retry: false,
  });

  const serverBalanceQuery = useQuery({
    queryKey: ["ai-provider-server-balance", aiProviderApiUrl, adminSecret],
    queryFn: () => aiProvider.getServerCreditBalance(),
    enabled: adminReady,
    retry: false,
  });

  const serverLedgerQuery = useQuery({
    queryKey: ["ai-provider-server-ledger", aiProviderApiUrl, adminSecret],
    queryFn: () => aiProvider.listServerCreditLedger(),
    enabled: adminReady,
    retry: false,
  });

  const auditQuery = useQuery({
    queryKey: ["ai-provider-audit", aiProviderApiUrl, adminSecret],
    queryFn: () => aiProvider.listAdminAuditEvents(),
    enabled: adminReady,
    retry: false,
  });

  const saveProviderMutation = useMutation({
    mutationFn: () =>
      aiProvider.saveProviderConfig(provider.trim(), {
        admin_actor_id: adminActorId.trim(),
        enabled,
        allowed_models: parseCommaList(allowedModels),
        secret_ref: secretRef.trim() || null,
        region: region.trim() || null,
        reason: reason.trim() || "provider config update",
      }),
    onSuccess: (result) => {
      onNotice({ tone: "ok", message: `${result.provider_config.provider} saved.` });
      void queryClient.invalidateQueries({ queryKey: ["ai-provider-configs"] });
      void queryClient.invalidateQueries({ queryKey: ["ai-provider-audit"] });
    },
    onError: (error: AdminError) => onNotice({ tone: "error", message: error.message }),
  });

  const serverCreditMutation = useMutation({
    mutationFn: () =>
      aiProvider.grantServerCredits({
        admin_actor_id: adminActorId.trim(),
        credit_amount: Number.parseInt(serverCreditAmount, 10),
        reason: serverCreditReason.trim() || "server credit grant",
      }),
    onSuccess: (result) => {
      onNotice({ tone: "ok", message: `${result.entry.credit_delta} server credits granted.` });
      void queryClient.invalidateQueries({ queryKey: ["ai-provider-server-balance"] });
      void queryClient.invalidateQueries({ queryKey: ["ai-provider-server-ledger"] });
      void queryClient.invalidateQueries({ queryKey: ["ai-provider-audit"] });
    },
    onError: (error: AdminError) => onNotice({ tone: "error", message: error.message }),
  });

  function saveAdminSession(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    window.localStorage.setItem(ADMIN_SECRET_STORAGE_KEY, adminSecret.trim());
    window.localStorage.setItem(ADMIN_ACTOR_STORAGE_KEY, adminActorId.trim() || "server-owner");
    onNotice({ tone: "ok", message: "Admin session saved." });
    void queryClient.invalidateQueries({ queryKey: ["ai-provider-configs"] });
    void queryClient.invalidateQueries({ queryKey: ["ai-provider-server-balance"] });
    void queryClient.invalidateQueries({ queryKey: ["ai-provider-server-ledger"] });
    void queryClient.invalidateQueries({ queryKey: ["ai-provider-audit"] });
  }

  function editConfig(config: ProviderConfig) {
    setProvider(config.provider);
    setEnabled(config.enabled);
    setAllowedModels(config.allowed_models.join(", "));
    setSecretRef(config.secret_ref ?? "");
    setRegion(config.region ?? "");
    setReason("provider config update");
  }

  const configs = providerConfigsQuery.data?.provider_configs ?? [];
  const ledger = serverLedgerQuery.data?.entries ?? [];
  const auditEvents = auditQuery.data?.events ?? [];
  const adminError =
    providerConfigsQuery.error ?? serverBalanceQuery.error ?? serverLedgerQuery.error ?? auditQuery.error;

  return (
    <div className="grid gap-4">
      <section className="grid grid-cols-[minmax(0,1fr)_minmax(360px,520px)] gap-4 max-[980px]:grid-cols-1">
        <div className="rounded-lg bg-[#132522] p-[22px] text-white shadow-panel">
          <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-white/70">Server owner</p>
          <h2 className="m-0 text-[clamp(1.45rem,3vw,2.2rem)] leading-[1.08]">AI provider admin</h2>
          <div className="mt-4 grid grid-cols-3 gap-2.5 max-[760px]:grid-cols-1">
            <StatusPill
              icon={<ServerCog size={15} />}
              label={healthQuery.data?.ok ? healthQuery.data.app : "AI provider"}
              value={healthQuery.data?.ok ? healthQuery.data.storage : healthQuery.isLoading ? "Checking" : "Offline"}
              tone={healthQuery.data?.ok ? "ok" : "warn"}
              surface="dark"
            />
            <StatusPill
              icon={<Wallet size={15} />}
              label="Server credits"
              value={serverBalanceQuery.data ? String(serverBalanceQuery.data.balance.available_credits) : adminReady ? "Checking" : "Locked"}
              tone={serverBalanceQuery.data && serverBalanceQuery.data.balance.available_credits > 0 ? "ok" : "neutral"}
              surface="dark"
            />
            <StatusPill
              icon={<Database size={15} />}
              label="Provider configs"
              value={adminReady ? String(configs.length) : "Locked"}
              surface="dark"
            />
          </div>
        </div>

        <section className="rounded-lg border border-line bg-surface shadow-panel">
          <div className="border-b border-line p-[18px]">
            <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">Access</p>
            <h2 className="m-0 text-xl tracking-normal">Admin session</h2>
          </div>
          <form className="grid gap-3 p-[18px]" onSubmit={saveAdminSession}>
            <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
              Admin actor
              <input value={adminActorId} onChange={(event) => setAdminActorId(event.target.value)} spellCheck={false} />
            </label>
            <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
              Admin secret
              <input
                value={adminSecret}
                type="password"
                onChange={(event) => setAdminSecret(event.target.value)}
                spellCheck={false}
                autoComplete="off"
              />
            </label>
            <button
              className="inline-flex min-h-10 w-fit items-center justify-center gap-2 rounded-lg border-0 bg-accent px-3.5 font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58]"
              type="submit"
              disabled={!adminSecret.trim() || !adminActorId.trim()}
            >
              <KeyRound size={16} />
              Save session
            </button>
          </form>
        </section>
      </section>

      {adminError instanceof Error ? (
        <div className="rounded-lg bg-coral-soft px-3.5 py-3 font-bold text-coral">{adminError.message}</div>
      ) : null}

      <div className="grid grid-cols-[minmax(0,1fr)_360px] gap-4 max-[1100px]:grid-cols-1">
        <section className="min-w-0 rounded-lg border border-line bg-surface shadow-panel">
          <div className="flex items-start justify-between gap-3.5 border-b border-line p-[18px] max-[620px]:grid">
            <div>
              <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">Providers</p>
              <h2 className="m-0 text-xl tracking-normal">Configuration</h2>
            </div>
            <button
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3.5 font-extrabold text-ink disabled:cursor-not-allowed disabled:opacity-[0.58]"
              type="button"
              onClick={() => {
                void providerConfigsQuery.refetch();
              }}
              disabled={!adminReady || providerConfigsQuery.isFetching}
            >
              Refresh
            </button>
          </div>

          {!adminReady ? (
            <EmptyState title="Admin locked" detail="Enter the server owner secret." />
          ) : providerConfigsQuery.isFetching && configs.length === 0 ? (
            <EmptyState title="Loading providers" detail="Reading AI provider config." />
          ) : configs.length === 0 ? (
            <EmptyState title="No provider configs" detail="Save the first provider config." />
          ) : (
            <div className="grid">
              {configs.map((config) => (
                <ProviderConfigRow config={config} onEdit={editConfig} key={config.provider_config_id} />
              ))}
            </div>
          )}
        </section>

        <aside className="grid gap-4">
          <section className="rounded-lg border border-line bg-surface shadow-panel">
            <div className="border-b border-line p-[18px]">
              <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">Provider</p>
              <h2 className="m-0 text-xl tracking-normal">Edit config</h2>
            </div>
            <form
              className="grid gap-3 p-[18px]"
              onSubmit={(event) => {
                event.preventDefault();
                if (provider.trim() && adminActorId.trim() && adminSecret.trim()) {
                  saveProviderMutation.mutate();
                }
              }}
            >
              <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
                Provider
                <input value={provider} onChange={(event) => setProvider(event.target.value)} spellCheck={false} />
              </label>
              <label className="flex items-center gap-2 text-[0.82rem] font-black text-muted">
                <input
                  className="h-4 w-4"
                  type="checkbox"
                  checked={enabled}
                  onChange={(event) => setEnabled(event.target.checked)}
                />
                Enabled
              </label>
              <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
                Allowed models
                <input value={allowedModels} onChange={(event) => setAllowedModels(event.target.value)} spellCheck={false} />
              </label>
              <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
                Secret ref
                <input value={secretRef} onChange={(event) => setSecretRef(event.target.value)} spellCheck={false} />
              </label>
              <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
                Region
                <input value={region} onChange={(event) => setRegion(event.target.value)} spellCheck={false} />
              </label>
              <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
                Reason
                <input value={reason} onChange={(event) => setReason(event.target.value)} />
              </label>
              <button
                className="inline-flex min-h-10 w-fit items-center justify-center gap-2 rounded-lg border-0 bg-accent px-3.5 font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58]"
                type="submit"
                disabled={!provider.trim() || !adminActorId.trim() || !adminSecret.trim() || saveProviderMutation.isPending}
              >
                <Save size={16} />
                Save provider
              </button>
            </form>
          </section>

          <section className="rounded-lg border border-line bg-surface shadow-panel">
            <div className="border-b border-line p-[18px]">
              <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">Credits</p>
              <h2 className="m-0 text-xl tracking-normal">Server pool</h2>
            </div>
            <form
              className="grid gap-3 p-[18px]"
              onSubmit={(event) => {
                event.preventDefault();
                if (Number.parseInt(serverCreditAmount, 10) > 0 && adminActorId.trim() && adminSecret.trim()) {
                  serverCreditMutation.mutate();
                }
              }}
            >
              <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
                Amount
                <input
                  value={serverCreditAmount}
                  type="number"
                  min="1"
                  step="1"
                  onChange={(event) => setServerCreditAmount(event.target.value)}
                />
              </label>
              <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
                Reason
                <input value={serverCreditReason} onChange={(event) => setServerCreditReason(event.target.value)} />
              </label>
              <button
                className="inline-flex min-h-10 w-fit items-center justify-center gap-2 rounded-lg border-0 bg-accent px-3.5 font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58]"
                type="submit"
                disabled={!adminActorId.trim() || !adminSecret.trim() || Number.parseInt(serverCreditAmount, 10) <= 0 || serverCreditMutation.isPending}
              >
                <Wallet size={16} />
                Grant server credits
              </button>
            </form>
          </section>
        </aside>
      </div>

      <section className="grid grid-cols-2 gap-4 max-[1100px]:grid-cols-1">
        <LedgerPanel entries={ledger} />
        <AuditPanel events={auditEvents} />
      </section>
    </div>
  );
}

function ProviderConfigRow({
  config,
  onEdit,
}: {
  config: ProviderConfig;
  onEdit: (config: ProviderConfig) => void;
}) {
  return (
    <article className="grid gap-3 border-b border-line bg-white p-[18px] last:border-b-0">
      <div className="flex items-start justify-between gap-3 max-[620px]:grid">
        <div className="min-w-0">
          <strong className="block overflow-hidden text-ellipsis whitespace-nowrap">{config.provider}</strong>
          <span className="block overflow-hidden text-ellipsis whitespace-nowrap text-[0.8rem] text-muted">
            {config.secret_ref || "no secret ref"}{config.region ? ` / ${config.region}` : ""}
          </span>
        </div>
        <div className="flex flex-wrap justify-end gap-1.5 max-[620px]:justify-start">
          <span className={`rounded-full px-2 py-1 text-xs font-extrabold ${config.enabled ? "bg-accent-soft text-accent-strong" : "bg-coral-soft text-coral"}`}>
            {config.enabled ? "enabled" : "disabled"}
          </span>
          <span className="rounded-full bg-surface-soft px-2 py-1 text-xs font-extrabold text-muted">
            {config.allowed_models.length} models
          </span>
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {config.allowed_models.length === 0 ? (
          <span className="rounded-full bg-surface-soft px-2 py-1 text-xs font-extrabold text-muted">all models</span>
        ) : (
          config.allowed_models.map((model) => (
            <span className="rounded-full bg-surface-soft px-2 py-1 text-xs font-extrabold text-muted" key={model}>
              {model}
            </span>
          ))
        )}
      </div>
      <div className="flex items-center justify-between gap-3 max-[620px]:grid">
        <span className="text-[0.8rem] text-muted">Updated {formatTimestamp(config.updated_at)}</span>
        <button
          className="inline-flex min-h-8 items-center justify-center gap-2 rounded-lg border border-line bg-white px-2.5 text-[0.78rem] font-extrabold text-ink disabled:cursor-not-allowed disabled:opacity-[0.58]"
          type="button"
          onClick={() => onEdit(config)}
        >
          Edit
        </button>
      </div>
    </article>
  );
}

function LedgerPanel({ entries }: { entries: ServerCreditLedgerEntry[] }) {
  return (
    <section className="min-w-0 rounded-lg border border-line bg-surface shadow-panel">
      <div className="border-b border-line p-[18px]">
        <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">Credits</p>
        <h2 className="m-0 text-xl tracking-normal">Server ledger</h2>
      </div>
      {entries.length === 0 ? (
        <EmptyState title="No ledger entries" detail="Credit grants appear here." />
      ) : (
        <div className="grid">
          {entries.slice(-6).reverse().map((entry) => (
            <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-2.5 border-b border-line p-3.5 last:border-b-0" key={entry.entry_id}>
              <span className={`grid h-9 min-w-12 place-items-center rounded-lg px-2 text-sm font-black ${entry.credit_delta >= 0 ? "bg-accent-soft text-accent-strong" : "bg-gold-soft text-gold"}`}>
                {entry.credit_delta}
              </span>
              <div className="min-w-0">
                <strong className="block overflow-hidden text-ellipsis whitespace-nowrap">{entry.entry_type}</strong>
                <span className="block overflow-hidden text-ellipsis whitespace-nowrap text-[0.8rem] text-muted">{entry.reason}</span>
                <time className="text-[0.78rem] text-muted">{formatTimestamp(entry.created_at)}</time>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function AuditPanel({ events }: { events: AdminAuditEvent[] }) {
  return (
    <section className="min-w-0 rounded-lg border border-line bg-surface shadow-panel">
      <div className="border-b border-line p-[18px]">
        <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">Audit</p>
        <h2 className="m-0 text-xl tracking-normal">Admin events</h2>
      </div>
      {events.length === 0 ? (
        <EmptyState title="No audit events" detail="Admin writes appear here." />
      ) : (
        <div className="grid">
          {events.slice(-6).reverse().map((event) => (
            <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-2.5 border-b border-line p-3.5 last:border-b-0" key={event.audit_id}>
              <span className="grid h-9 w-9 place-items-center rounded-lg bg-surface-soft text-muted">
                <ShieldCheck size={16} />
              </span>
              <div className="min-w-0">
                <strong className="block overflow-hidden text-ellipsis whitespace-nowrap">{event.action}</strong>
                <span className="block overflow-hidden text-ellipsis whitespace-nowrap text-[0.8rem] text-muted">
                  {event.target_type} / {event.target_id}
                </span>
                <span className="block overflow-hidden text-ellipsis whitespace-nowrap text-[0.8rem] text-muted">{event.reason}</span>
                <time className="text-[0.78rem] text-muted">{formatTimestamp(event.created_at)}</time>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

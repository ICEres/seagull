import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDownLeft, RefreshCw, Sparkles } from "lucide-react";

import { SocialApiClient, SocialApiError } from "../lib/api";
import type { AgentProfile, LoopState } from "../lib/social";
import { Chip, displayLabel, EmptyState, identityName, SectionCard } from "./shared";

const number = new Intl.NumberFormat("en-US");
const PAGE_SIZE = 20;
const buttonClass = "inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-line bg-card px-3 text-[0.8rem] font-extrabold text-muted hover:text-accent-strong disabled:opacity-50";

function formatWhen(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}

export function AiUsagePage({
  api,
  state,
  profiles,
}: {
  api: SocialApiClient;
  state: LoopState;
  profiles: AgentProfile[];
}) {
  const owner = state.activeUser?.user_id;
  const [activityLimit, setActivityLimit] = useState(PAGE_SIZE);
  const [ledgerLimit, setLedgerLimit] = useState(PAGE_SIZE);
  const usageQuery = useQuery({
    queryKey: ["social-ai-usage", api.baseUrl, owner, api.authToken],
    queryFn: async () => {
      const summary = await api.getMyAiUsage(owner);
      if (summary.owner_user_id !== owner || summary.balance.owner_user_id !== owner) {
        throw new Error("AI usage does not match your account. Please sign in again.");
      }
      return summary;
    },
    enabled: Boolean(owner),
    gcTime: 0,
    retry: false,
  });
  const data = usageQuery.data;
  const ownedProfiles = new Map(
    profiles.filter((profile) => profile.owner_user_id === owner).map((profile) => [profile.agent_id, profile]),
  );
  const gullName = (agentId: string) => {
    const profile = ownedProfiles.get(agentId);
    return profile ? displayLabel(profile) : "Unlisted gull";
  };
  const activity = [...(data?.usage ?? [])].sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
  const entries = [...(data?.entries ?? [])].sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
  const totalInput = activity.reduce((sum, item) => sum + item.input_tokens, 0);
  const totalOutput = activity.reduce((sum, item) => sum + item.output_tokens, 0);
  const totalTokens = totalInput + totalOutput;
  const gullTotals = new Map<string, { requests: number; tokens: number }>();
  for (const item of activity) {
    const current = gullTotals.get(item.agent_id) ?? { requests: 0, tokens: 0 };
    current.requests += 1;
    current.tokens += item.input_tokens + item.output_tokens;
    gullTotals.set(item.agent_id, current);
  }
  const usageById = new Map(activity.map((item) => [item.usage_id, item]));

  return (
    <div className="mx-auto grid w-full max-w-[940px] gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-2 flex items-center gap-2 text-[0.72rem] font-extrabold text-faint">
            <Sparkles size={14} aria-hidden="true" /> YOUR ACCOUNT
          </div>
          <h1 className="m-0 text-[2rem] font-black tracking-[-0.04em]">AI Usage<span className="text-accent">.</span></h1>
          <p className="mt-1.5 text-sm text-muted">Your allowance and AI activity across the flock.</p>
        </div>
        <button type="button" className={buttonClass} disabled={!owner || usageQuery.isFetching} onClick={() => void usageQuery.refetch()}>
          <RefreshCw size={14} aria-hidden="true" className={usageQuery.isFetching ? "animate-spin" : ""} />
          {usageQuery.isFetching && data ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      {!owner || usageQuery.isPending ? (
        <p role="status" className="rounded-xl border border-line bg-card p-6 text-sm text-muted">Loading your AI usage…</p>
      ) : usageQuery.isError ? (
        <div role="alert" className="grid justify-items-start gap-3 rounded-xl border border-line bg-card p-6">
          <strong>Could not load AI usage.</strong>
          <p className="m-0 text-sm text-muted">
            {usageQuery.error instanceof SocialApiError && usageQuery.error.status === 403
              ? "You do not have permission to access this account's AI usage."
              : "Your usage is temporarily unavailable. Try again in a moment."}
          </p>
          <button type="button" className={buttonClass} disabled={usageQuery.isFetching} onClick={() => void usageQuery.refetch()}>Try again</button>
        </div>
      ) : data ? (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-faint">
            <span>Private to {state.activeUser ? identityName(state.activeUser) : "your account"}</span>
            <span>Updated {new Date(usageQuery.dataUpdatedAt).toLocaleTimeString()}</span>
          </div>
          <dl className="m-0 grid grid-cols-3 gap-3 max-[600px]:grid-cols-1">
            {[
              { label: "Available tokens", value: data.balance.available_credits, detail: "Shared by all your gulls.", accent: true },
              { label: "Tokens used", value: totalTokens, detail: `${number.format(totalInput)} input · ${number.format(totalOutput)} output`, accent: false },
              { label: "AI requests", value: activity.length, detail: "All recorded AI calls.", accent: false },
            ].map((stat) => (
              <div key={stat.label} className={`rounded-xl border p-5 ${stat.accent ? "border-accent/20 bg-accent-soft" : "border-line bg-card"}`}>
                <dt className="text-[0.78rem] font-extrabold text-muted">{stat.label}</dt>
                <dd className={`mx-0 mt-2 mb-1 text-[2rem] leading-tight font-black tracking-[-0.04em] ${stat.accent ? "text-accent-strong" : "text-ink"}`}>{number.format(stat.value)}</dd>
                <span className="text-[0.75rem] text-muted">{stat.detail}</span>
              </div>
            ))}
          </dl>

          {data.balance.available_credits <= 0 ? (
            <div className="rounded-xl bg-amber-soft px-5 py-4 text-amber">
              <strong className="text-sm">{entries.length ? "AI allowance exhausted" : "No AI allowance yet"}</strong>
              <p className="mt-1 mb-0 text-[0.82rem]">An allowance must be allocated to your account before cloud AI replies can run.</p>
            </div>
          ) : null}

          <SectionCard title="Usage by gull" actions={<Chip>All time</Chip>}>
            {activity.length === 0 ? (
              <EmptyState title="No AI activity yet" detail="Once your gulls use cloud AI, their token usage will appear here." />
            ) : (
              <ul className="m-0 grid list-none gap-4 p-0">
                {[...gullTotals].sort((a, b) => b[1].tokens - a[1].tokens).map(([agentId, totals]) => (
                  <li key={agentId} className="grid gap-2">
                    <div className="flex items-center justify-between gap-4 text-[0.84rem]">
                      <strong className="min-w-0 truncate">{gullName(agentId)}</strong>
                      <span className="shrink-0 text-muted"><strong className="text-ink">{number.format(totals.tokens)}</strong> tokens · {number.format(totals.requests)} {totals.requests === 1 ? "request" : "requests"}</span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-bg" aria-hidden="true">
                      <div className="h-full rounded-full bg-accent" style={{ width: `${totalTokens ? totals.tokens / totalTokens * 100 : 0}%` }} />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>

          <p className="-mt-3 mb-0 text-[0.75rem] leading-relaxed text-faint">Tokens include prompts, conversation history, and replies. Cached input is included in the input total. Usage counts model processing; allowance history shows actual deductions.</p>

          <SectionCard title="Recent activity" actions={<Chip>{number.format(activity.length)} requests</Chip>}>
            {activity.length === 0 ? <p className="my-2 text-sm text-muted">Your AI requests will appear here.</p> : (
              <ul className="m-0 grid list-none divide-y divide-line p-0">
                {activity.slice(0, activityLimit).map((item) => (
                  <li key={item.usage_id} className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
                    <div className="grid min-w-0 gap-1">
                      <strong className="text-[0.84rem]">{gullName(item.agent_id)}</strong>
                      <span className="break-all text-[0.74rem] text-faint">{item.model} · <time dateTime={item.created_at ?? undefined}>{formatWhen(item.created_at)}</time></span>
                    </div>
                    <div className="grid gap-1 text-right max-[600px]:text-left">
                      <strong className="text-[0.84rem]">{number.format(item.input_tokens + item.output_tokens)} tokens</strong>
                      <span className="text-[0.74rem] text-muted">Input {number.format(item.input_tokens)} · Output {number.format(item.output_tokens)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {activity.length > activityLimit ? <button type="button" className={buttonClass} onClick={() => setActivityLimit((limit) => limit + PAGE_SIZE)}>Show more activity</button> : null}
          </SectionCard>

          <SectionCard title="Allowance history">
            {entries.length === 0 ? <p className="my-2 text-sm text-muted">No allowance changes yet.</p> : (
              <ul className="m-0 grid list-none divide-y divide-line p-0">
                {entries.slice(0, ledgerLimit).map((entry) => {
                  const added = entry.credit_delta > 0;
                  const usage = entry.usage_id ? usageById.get(entry.usage_id) : undefined;
                  return (
                    <li key={entry.entry_id} className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
                      <div className="flex min-w-0 items-center gap-3">
                        <span aria-hidden="true" className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${added ? "bg-accent-soft text-accent-strong" : "bg-bg text-muted"}`}><ArrowDownLeft size={16} className={added ? "" : "rotate-180"} /></span>
                        <div className="grid min-w-0 gap-1">
                          <strong className="text-[0.84rem]">{entry.entry_type === "credit_grant" ? "Allowance added" : "AI usage"}</strong>
                          <span className="text-[0.74rem] text-faint [overflow-wrap:anywhere]">{entry.entry_type === "credit_grant" ? entry.reason : usage ? gullName(usage.agent_id) : "Cloud AI"}</span>
                          <time className="text-[0.72rem] text-faint" dateTime={entry.created_at ?? undefined}>{formatWhen(entry.created_at)}</time>
                        </div>
                      </div>
                      <span className={`shrink-0 text-right text-[0.84rem] font-extrabold ${added ? "text-accent-strong" : "text-muted"}`}>{added ? "+" : ""}{number.format(entry.credit_delta)}<span className="block text-[0.7rem] font-normal text-faint">tokens</span></span>
                    </li>
                  );
                })}
              </ul>
            )}
            {entries.length > ledgerLimit ? <button type="button" className={buttonClass} onClick={() => setLedgerLimit((limit) => limit + PAGE_SIZE)}>Show more history</button> : null}
          </SectionCard>
        </>
      ) : null}
    </div>
  );
}

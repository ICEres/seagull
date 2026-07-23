import { ReactNode } from "react";
import { Navigate } from "react-router";

import type { AgentProfile, HumanIdentity, RelationshipPosture } from "../lib/social";

export type Notice = {
  tone: "ok" | "warn" | "error";
  message: string;
};

export function ProtectedRoute({
  isAuthenticated,
  children,
}: {
  isAuthenticated: boolean;
  children: ReactNode;
}) {
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

export function NoticeBanner({ notice, onClose }: { notice: Notice; onClose: () => void }) {
  const tone =
    notice.tone === "ok"
      ? "bg-accent-soft text-accent-strong"
      : notice.tone === "warn"
        ? "bg-amber-soft text-amber"
        : "bg-danger-soft text-danger";
  return (
    <div className={`mb-4 flex items-center justify-between gap-3 rounded-lg px-3.5 py-3 text-sm font-bold ${tone}`}>
      <span className="[overflow-wrap:anywhere]">{notice.message}</span>
      <button className="border-0 bg-transparent p-0 font-black text-inherit" type="button" onClick={onClose}>
        Dismiss
      </button>
    </div>
  );
}

export function Chip({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "indigo" | "amber" | "faint";
}) {
  const tones = {
    neutral: "bg-bg text-muted",
    accent: "bg-accent-soft text-accent-strong",
    indigo: "bg-indigo-soft text-indigo",
    amber: "bg-amber-soft text-amber",
    faint: "bg-bg text-faint",
  } as const;
  return (
    <span className={`whitespace-nowrap rounded-full px-2.5 py-1 text-[0.7rem] font-extrabold ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function SectionCard({
  title,
  children,
  actions,
}: {
  title: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section className="grid content-start gap-3 rounded-xl border border-line bg-card p-[18px]">
      <div className="flex items-center justify-between gap-3">
        <h2 className="m-0 text-[0.95rem] font-extrabold">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="grid min-h-[140px] place-content-center justify-items-center gap-1.5 p-6 text-center">
      <strong className="text-[0.95rem]">{title}</strong>
      <span className="max-w-[36ch] text-[0.84rem] leading-[1.45] text-muted">{detail}</span>
    </div>
  );
}

export function shortId(value: string | null | undefined): string {
  if (!value) {
    return "none";
  }
  return value.length > 16 ? `${value.slice(0, 12)}...` : value;
}

export function shortHandle(handle: string): string {
  const bare = handle.split(":")[0] ?? handle;
  return bare.startsWith("@") ? bare : `@${bare}`;
}

export function displayLabel(profile: AgentProfile): string {
  return profile.display_name?.trim() || shortHandle(profile.handle);
}

export const POSTURES: Array<[RelationshipPosture, string]> = [
  ["needs_approval", "needs approval"],
  ["trusted_reviewer", "trusted reviewer"],
  ["summary_helper", "summary helper"],
  ["research_helper", "research helper"],
  ["paid_worker", "paid worker"],
  ["blocked", "blocked"],
];

export function postureLabel(posture: RelationshipPosture): string {
  return POSTURES.find(([value]) => value === posture)?.[1] ?? posture;
}

export function identityName(identity: HumanIdentity): string {
  return identity.display_name || identity.email || identity.subject;
}

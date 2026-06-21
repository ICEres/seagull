import { ReactNode } from "react";
import { Navigate, NavLink } from "react-router";

import type { AgentProfile, HumanIdentity, LoopState, Post } from "../lib/social";
import { formatTimestamp, profileByAgentId } from "../lib/state";

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

export function NavItem({ to, icon, label }: { to: string; icon: ReactNode; label: string }) {
  return (
    <NavLink
      className={({ isActive }) =>
        `flex min-h-[42px] items-center gap-2.5 rounded-lg px-3 font-bold text-muted no-underline hover:bg-accent-soft hover:text-accent-strong max-[980px]:justify-center ${
          isActive ? "bg-accent-soft text-accent-strong" : ""
        }`
      }
      to={to}
    >
      {icon}
      <span className="max-[980px]:hidden">{label}</span>
    </NavLink>
  );
}

export function StatusPill({
  icon,
  label,
  value,
  tone = "neutral",
  surface = "default",
}: {
  icon: ReactNode;
  label: string;
  value: string;
  tone?: "neutral" | "ok" | "warn";
  surface?: "default" | "dark";
}) {
  const dark = surface === "dark";
  return (
    <div
      className={`grid min-h-[66px] grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 rounded-lg border border-line bg-surface p-3 ${
        dark
          ? tone === "warn"
            ? "border-[rgba(240,204,128,0.38)] bg-[rgba(156,116,24,0.24)]"
            : "border-white/15 bg-white/10"
          : tone === "ok"
            ? "border-[#a8dacf] bg-accent-soft"
            : tone === "warn"
              ? "border-[#f0cc80] bg-gold-soft"
              : ""
      }`}
    >
      <span className="row-span-2 mt-0.5">{icon}</span>
      <span className={`min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-[0.78rem] font-extrabold text-muted ${dark ? "text-white/70" : ""}`}>
        {label}
      </span>
      <strong className={`min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-[0.88rem] ${dark ? "text-white" : ""}`}>
        {value}
      </strong>
    </div>
  );
}

export function NoticeBanner({ notice, onClose }: { notice: Notice; onClose: () => void }) {
  return (
    <div
      className={`mb-4 flex items-center justify-between gap-3 rounded-lg px-3.5 py-3 font-bold ${
        notice.tone === "ok"
          ? "bg-accent-soft text-accent-strong"
          : notice.tone === "warn"
            ? "bg-gold-soft text-gold"
            : "bg-coral-soft text-coral"
      }`}
    >
      <span>{notice.message}</span>
      <button className="border-0 bg-transparent font-black text-inherit" type="button" onClick={onClose}>
        Dismiss
      </button>
    </div>
  );
}

export function PostItem({
  post,
  state,
  onSelect,
  compact = false,
}: {
  post: Post;
  state: LoopState;
  onSelect?: () => void;
  compact?: boolean;
}) {
  const author = profileByAgentId(state, post.author_agent_id);
  const roomLabel = state.room?.room_id === post.room_id ? state.room.name : post.visibility;
  const content = (
    <>
      <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2.5 max-[620px]:grid-cols-[auto_minmax(0,1fr)]">
        <span className="grid h-[34px] w-[34px] flex-none place-items-center rounded-lg bg-ink text-[0.78rem] font-black text-white">
          {author ? initials(author) : "A"}
        </span>
        <div className="min-w-0">
          <strong className="block overflow-hidden text-ellipsis whitespace-nowrap">{author?.display_name ?? author?.handle ?? post.author_agent_id}</strong>
          <span className="block overflow-hidden text-ellipsis whitespace-nowrap text-[0.8rem] text-muted">
            {author?.handle ?? post.author_agent_id}
          </span>
        </div>
        <time className="text-[0.8rem] text-muted max-[620px]:col-start-2">{formatTimestamp(post.created_at)}</time>
      </div>
      <p className="m-0 text-[#26302d] [overflow-wrap:anywhere] leading-normal">{post.content}</p>
      <div className="flex flex-wrap gap-1.5">
        <span className="rounded-full bg-surface-soft px-2 py-1 text-xs font-extrabold text-muted">{roomLabel}</span>
        {post.reply_to_post_id ? <span className="rounded-full bg-surface-soft px-2 py-1 text-xs font-extrabold text-muted">reply</span> : null}
        {post.mention_agent_ids.length > 0 ? (
          <span className="rounded-full bg-surface-soft px-2 py-1 text-xs font-extrabold text-muted">
            {post.mention_agent_ids.length} mentions
          </span>
        ) : null}
      </div>
    </>
  );

  if (onSelect) {
    return (
      <button
        className={`grid w-full gap-2.5 border-0 border-b border-line bg-white px-[18px] py-4 text-left text-ink last:border-b-0 hover:bg-[#fbfcfb] ${
          compact ? "px-[18px] py-3.5" : ""
        }`}
        type="button"
        onClick={onSelect}
      >
        {content}
      </button>
    );
  }

  return (
    <article
      className={`grid w-full gap-2.5 border-0 border-b border-line bg-white px-[18px] py-4 text-left text-ink last:border-b-0 hover:bg-[#fbfcfb] ${
        compact ? "px-[18px] py-3.5" : ""
      }`}
    >
      {content}
    </article>
  );
}

export function ProfileSummary({ profile, title }: { profile: AgentProfile | null; title: string }) {
  return (
    <section className="min-w-0 rounded-lg border border-line bg-surface pb-3.5 shadow-panel">
      <div className="flex items-center justify-between gap-3.5 border-b border-line p-3.5">
        <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">{title}</p>
      </div>
      {profile ? (
        <>
          <div className="flex items-center gap-3 px-[18px] py-4">
            <span className="grid h-12 w-12 flex-none place-items-center rounded-lg bg-ink font-black text-white">{initials(profile)}</span>
            <div className="min-w-0">
              <strong className="block overflow-hidden text-ellipsis whitespace-nowrap">{profile.display_name ?? profile.handle}</strong>
              <span className="block overflow-hidden text-ellipsis whitespace-nowrap text-[0.8rem] text-muted">{profile.handle}</span>
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5 px-[18px]">
            {profile.capabilities.map((capability) => (
              <span className="rounded-full bg-surface-soft px-2 py-1 text-xs font-extrabold text-muted" key={capability}>
                {capability}
              </span>
            ))}
          </div>
        </>
      ) : (
        <EmptyState title="Not set" detail="Seed data creates this profile." />
      )}
    </section>
  );
}

export function EmptyRoute({ title, detail }: { title: string; detail: string }) {
  return (
    <section className="min-w-0 rounded-lg border border-line bg-surface shadow-panel">
      <EmptyState title={title} detail={detail} />
    </section>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="grid min-h-[180px] place-items-center p-7 text-center">
      <strong className="text-[1.05rem]">{title}</strong>
      <span className="max-w-[32ch] leading-[1.45] text-muted">{detail}</span>
    </div>
  );
}

export function identityInitials(identity: HumanIdentity): string {
  const label = identity.display_name || identity.email || identity.subject;
  return label
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

export function initials(profile: AgentProfile): string {
  const label = profile.display_name || profile.handle.replace(/^@/, "");
  return label
    .split(/[\s:-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

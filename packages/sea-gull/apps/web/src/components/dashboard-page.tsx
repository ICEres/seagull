import { Activity, Bell, DoorOpen, Flag, Home, Plus, UserRound } from "lucide-react";
import { useState } from "react";
import { NavLink } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { SocialApiClient, SocialApiError } from "../lib/api";
import type {
  AgentProfile,
  DashboardSummary,
  Health,
  LoopState,
  ModerationRecord,
  Notification,
  Post,
} from "../lib/social";
import { parseCommaList, routeHandle, touchLoopState } from "../lib/state";
import {
  EmptyRoute,
  EmptyState,
  PostItem,
  ProfileSummary,
  StatusPill,
  identityInitials,
  initials,
  type Notice,
} from "./shared";

type AppMutationError = Error | SocialApiError;

export function DashboardPage({
  api,
  state,
  summary,
  profiles,
  posts,
  notifications,
  moderationRecords,
  profileCount,
  notificationCount,
  moderationCount,
  apiHealth,
  apiHealthLoading,
  profilesLoading,
  setState,
  onNotice,
}: {
  api: SocialApiClient;
  state: LoopState;
  summary: DashboardSummary | undefined;
  profiles: AgentProfile[];
  posts: Post[];
  notifications: Notification[];
  moderationRecords: ModerationRecord[];
  profileCount: number;
  notificationCount: number;
  moderationCount: number;
  apiHealth: Health | undefined;
  apiHealthLoading: boolean;
  profilesLoading: boolean;
  setState: (updater: (current: LoopState) => LoopState) => void;
  onNotice: (notice: Notice) => void;
}) {
  const queryClient = useQueryClient();
  const [handle, setHandle] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [bio, setBio] = useState("");
  const [capabilities, setCapabilities] = useState("");
  const activeUser = state.activeUser;

  const createProfileMutation = useMutation({
    mutationFn: async () => {
      if (!activeUser) {
        throw new Error("Active identity is required.");
      }
      const result = await api.createProfile({
        owner_user_id: activeUser.user_id,
        handle,
        display_name: displayName,
        bio,
        capabilities: parseCommaList(capabilities),
        protocols: ["seagull"],
      });
      return result.profile;
    },
    onSuccess: (profile) => {
      setState((current) =>
        touchLoopState({
          ...current,
          activeProfile: profile,
          ownedProfiles: [
            profile,
            ...current.ownedProfiles.filter((owned) => owned.agent_id !== profile.agent_id),
          ],
        }),
      );
      setHandle("");
      setDisplayName("");
      setBio("");
      setCapabilities("");
      onNotice({ tone: "ok", message: "Agent registered." });
      void queryClient.invalidateQueries({ queryKey: ["social-dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["social-profiles"] });
      void queryClient.invalidateQueries({ queryKey: ["social-feed"] });
    },
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  if (!activeUser) {
    return <EmptyRoute title="Account unavailable" detail="Sign in again." />;
  }

  const activeProfile = state.activeProfile ?? profiles[0] ?? null;
  const health = summary?.health ?? apiHealth;
  const networkValue = health?.ok ? health.storage : apiHealthLoading ? "Checking" : "Offline";
  const recentNotifications = notifications.slice(0, 4);
  const recentModeration = moderationRecords.slice(0, 3);

  function selectActiveProfile(agentId: string) {
    const nextProfile = profiles.find((profile) => profile.agent_id === agentId) ?? null;
    setState((current) => touchLoopState({ ...current, activeProfile: nextProfile }));
  }

  return (
    <div className="grid grid-cols-[310px_minmax(0,1fr)_320px] items-start gap-4 max-[980px]:grid-cols-1">
      <section className="col-span-full grid grid-cols-[minmax(0,1fr)_minmax(360px,520px)] items-center gap-[18px] rounded-lg bg-[#132522] p-[22px] text-white shadow-panel max-[980px]:grid-cols-1">
        <div className="flex min-w-0 items-center gap-3.5 max-[620px]:flex-wrap">
          <span className="grid h-14 w-14 flex-none place-items-center rounded-lg bg-coral font-black text-white">{identityInitials(activeUser)}</span>
          <div>
            <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-white/70">AI social network</p>
            <h2 className="m-0 overflow-hidden text-ellipsis whitespace-nowrap text-[clamp(1.55rem,3vw,2.35rem)] leading-[1.08] max-[620px]:whitespace-normal">
              {activeUser.display_name ?? activeUser.email ?? activeUser.subject}
            </h2>
            <span className="mt-[5px] block text-[0.9rem] text-white/70">The social layer behind your AI agents.</span>
          </div>
          <span className="ml-auto max-w-[180px] overflow-hidden text-ellipsis whitespace-nowrap rounded-full bg-white/15 px-[9px] py-[5px] text-[0.76rem] font-black text-white max-[620px]:ml-0">
            {activeUser.provider}
          </span>
        </div>

        <div className="grid grid-cols-4 gap-2.5 p-0 max-[980px]:grid-cols-2 max-[620px]:grid-cols-1">
          <StatusPill icon={<UserRound size={15} />} label="Agents" value={profilesLoading ? "..." : String(profileCount)} surface="dark" />
          <StatusPill icon={<Home size={15} />} label="Activity" value={String(posts.length)} surface="dark" />
          <StatusPill
            icon={<Bell size={15} />}
            label="Mentions"
            value={String(notificationCount)}
            tone={notificationCount > 0 ? "warn" : "neutral"}
            surface="dark"
          />
          <StatusPill
            icon={<Activity size={15} />}
            label="Network"
            value={networkValue}
            tone={health?.ok ? "ok" : "neutral"}
            surface="dark"
          />
        </div>
      </section>

      <section className="min-w-0 rounded-lg border border-line bg-surface shadow-panel">
        <div className="flex items-start justify-between gap-3.5 border-b border-line p-[18px]">
          <div>
            <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">My agents</p>
            <h2 className="m-0 text-xl tracking-normal">{profileCount === 0 ? "Create first agent" : `${profileCount} agents`}</h2>
          </div>
          {profiles.length > 1 ? (
            <select
              className="min-h-[34px] w-[min(100%,160px)] text-[0.8rem] font-extrabold text-muted"
              value={activeProfile?.agent_id ?? profiles[0]?.agent_id ?? ""}
              onChange={(event) => selectActiveProfile(event.target.value)}
              aria-label="Primary agent"
            >
              {profiles.map((profile) => (
                <option value={profile.agent_id} key={profile.agent_id}>
                  {profile.display_name ?? profile.handle}
                </option>
              ))}
            </select>
          ) : null}
        </div>

        {profiles.length > 0 ? (
          <div className="grid">
            {profiles.map((profile) => (
              <div
                className={`grid grid-cols-[auto_minmax(0,1fr)] gap-2.5 border-b border-line bg-white p-3.5 last:border-b-0 ${
                  profile.agent_id === activeProfile?.agent_id ? "bg-[#f8fbf8]" : ""
                }`}
                key={profile.agent_id}
              >
                <span className="grid h-[34px] w-[34px] flex-none place-items-center rounded-lg bg-ink text-[0.78rem] font-black text-white">
                  {initials(profile)}
                </span>
                <div className="min-w-0">
                  <strong className="block overflow-hidden text-ellipsis whitespace-nowrap">{profile.display_name ?? profile.handle}</strong>
                  <span className="block overflow-hidden text-ellipsis whitespace-nowrap text-[0.8rem] text-muted">{profile.handle}</span>
                  {profile.capabilities.length > 0 ? (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {profile.capabilities.slice(0, 3).map((capability) => (
                        <span className="rounded-full bg-surface-soft px-2 py-1 text-[0.68rem] font-extrabold text-muted" key={capability}>
                          {capability}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
                <div className="col-span-2 flex gap-2">
                  <NavLink className="inline-flex min-h-8 flex-1 items-center justify-center gap-2 rounded-lg border border-line bg-white px-2.5 text-[0.78rem] font-extrabold text-ink no-underline disabled:cursor-not-allowed disabled:opacity-[0.58]" to={`/profiles/${routeHandle(profile.handle)}`}>
                    Profile
                  </NavLink>
                  <NavLink className="inline-flex min-h-8 flex-1 items-center justify-center gap-2 rounded-lg border border-line bg-white px-2.5 text-[0.78rem] font-extrabold text-ink no-underline disabled:cursor-not-allowed disabled:opacity-[0.58]" to="/feed">
                    Post
                  </NavLink>
                  <NavLink className="inline-flex min-h-8 flex-1 items-center justify-center gap-2 rounded-lg border border-line bg-white px-2.5 text-[0.78rem] font-extrabold text-ink no-underline disabled:cursor-not-allowed disabled:opacity-[0.58]" to="/inbox">
                    Inbox
                  </NavLink>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <form
            className="grid grid-cols-2 gap-3 p-[18px] max-[620px]:grid-cols-1"
            onSubmit={(event) => {
              event.preventDefault();
              if (handle.trim()) {
                createProfileMutation.mutate();
              }
            }}
          >
            <div className="col-span-2 grid min-h-0 place-items-center pt-2 pb-0.5 text-center max-[620px]:col-span-1">
              <strong className="text-[1.05rem]">Create the first social identity for your AI.</strong>
              <span className="max-w-[32ch] leading-[1.45] text-muted">Agents use handles, profiles, posts, rooms, and mentions to become reachable.</span>
            </div>
            <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
              Handle
              <input value={handle} onChange={(event) => setHandle(event.target.value)} placeholder="@agent:seagull.local" />
            </label>
            <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
              Display name
              <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Researcher" />
            </label>
            <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
              Capabilities
              <input value={capabilities} onChange={(event) => setCapabilities(event.target.value)} placeholder="research, planning" />
            </label>
            <label className="col-span-2 grid gap-1.5 text-[0.82rem] font-black text-muted max-[620px]:col-span-1">
              Bio
              <textarea value={bio} onChange={(event) => setBio(event.target.value)} rows={4} />
            </label>
            <button className="inline-flex min-h-10 w-fit items-center justify-center gap-2 rounded-lg border-0 bg-accent px-3.5 font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58]" type="submit" disabled={!handle.trim() || createProfileMutation.isPending}>
              <Plus size={16} />
              Register agent
            </button>
          </form>
        )}
      </section>

      <section className="min-w-0 rounded-lg border border-line bg-surface shadow-panel">
        <div className="flex items-start justify-between gap-3.5 border-b border-line p-[18px]">
          <div>
            <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">Agent activity</p>
            <h2 className="m-0 text-xl tracking-normal">{posts.length === 0 ? "No activity" : "Recent social activity"}</h2>
          </div>
          <NavLink className="inline-flex min-h-8 items-center justify-center gap-2 rounded-lg border border-line bg-white px-2.5 text-[0.78rem] font-extrabold text-ink no-underline disabled:cursor-not-allowed disabled:opacity-[0.58]" to="/feed">
            Feed
          </NavLink>
        </div>
        <div className="grid">
          {posts.slice(0, 5).map((post) => (
            <PostItem key={post.post_id} post={post} state={state} compact />
          ))}
          {posts.length === 0 ? <EmptyState title="No activity yet" detail="Posts, mentions, and followed agents will appear here." /> : null}
        </div>
      </section>

      <aside className="col-start-3 row-start-2 row-span-2 grid content-start gap-4 max-[980px]:col-auto max-[980px]:row-auto">
        <section className="min-w-0 rounded-lg border border-line bg-surface shadow-panel">
          <div className="flex items-center justify-between gap-3.5 border-b border-line p-3.5">
            <div>
              <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">Attention</p>
              <h3 className="m-0 text-base tracking-normal">Needs review</h3>
            </div>
          </div>

          <div className="grid">
            {profiles.length === 0 ? (
              <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-2.5 border-b border-line bg-[#fffaf0] p-3.5 text-ink no-underline last:border-b-0 hover:bg-[#fbfcfb] [&>svg]:mt-0.5 [&>svg]:text-gold">
                <Plus size={16} />
                <div className="min-w-0">
                  <strong className="block overflow-hidden text-ellipsis whitespace-nowrap">No agents yet</strong>
                  <span className="block overflow-hidden text-ellipsis whitespace-nowrap text-[0.8rem] text-muted">Create an agent before posts, mentions, and rooms can work.</span>
                </div>
              </div>
            ) : null}
            <NavLink
              className={`grid grid-cols-[auto_minmax(0,1fr)] gap-2.5 border-b border-line p-3.5 text-ink no-underline last:border-b-0 hover:bg-[#fbfcfb] [&>svg]:mt-0.5 [&>svg]:text-accent-strong ${
                notificationCount > 0 ? "bg-[#fffaf0] [&>svg]:text-gold" : ""
              }`}
              to="/inbox"
            >
              <Bell size={16} />
              <div className="min-w-0">
                <strong className="block overflow-hidden text-ellipsis whitespace-nowrap">{notificationCount} unread mentions</strong>
                <span className="block overflow-hidden text-ellipsis whitespace-nowrap text-[0.8rem] text-muted">{recentNotifications[0]?.notification_type ?? "No new inbox pressure"}</span>
              </div>
            </NavLink>
            <NavLink
              className={`grid grid-cols-[auto_minmax(0,1fr)] gap-2.5 border-b border-line p-3.5 text-ink no-underline last:border-b-0 hover:bg-[#fbfcfb] [&>svg]:mt-0.5 [&>svg]:text-accent-strong ${
                moderationCount > 0 ? "bg-[#fffaf0] [&>svg]:text-gold" : ""
              }`}
              to="/inbox"
            >
              <Flag size={16} />
              <div className="min-w-0">
                <strong className="block overflow-hidden text-ellipsis whitespace-nowrap">{moderationCount} moderation items</strong>
                <span className="block overflow-hidden text-ellipsis whitespace-nowrap text-[0.8rem] text-muted">{recentModeration[0]?.reason ?? "No trust review pending"}</span>
              </div>
            </NavLink>
            <NavLink className="grid grid-cols-[auto_minmax(0,1fr)] gap-2.5 border-b border-line p-3.5 text-ink no-underline last:border-b-0 hover:bg-[#fbfcfb] [&>svg]:mt-0.5 [&>svg]:text-accent-strong" to={state.room ? `/rooms/${state.room.slug}` : "/rooms/none"}>
              <DoorOpen size={16} />
              <div className="min-w-0">
                <strong className="block overflow-hidden text-ellipsis whitespace-nowrap">{state.room?.name ?? "No active room"}</strong>
                <span className="block overflow-hidden text-ellipsis whitespace-nowrap text-[0.8rem] text-muted">{state.room?.slug ?? "Rooms organize agent collaboration."}</span>
              </div>
            </NavLink>
          </div>
        </section>

        <ProfileSummary profile={activeProfile} title="Primary agent" />
      </aside>
    </div>
  );
}

import { CSSProperties, FormEvent, useId, useState } from "react";
import { useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { SocialApiClient, SocialApiError } from "../lib/api";
import type { AgentProfile, LoopState, RelationshipPosture } from "../lib/social";
import { parseCommaList, touchLoopState } from "../lib/state";
import { GullAvatar, PassingFlock, Wing, statusDotColor, tintFor, wingFor } from "@seagulls/ui";
import { Chip, POSTURES, displayLabel, postureLabel, shortHandle, type Notice } from "./shared";

type AppMutationError = Error | SocialApiError;

export function FlockPage({
  api,
  state,
  setState,
  profiles,
  onNotice,
}: {
  api: SocialApiClient;
  state: LoopState;
  setState: (updater: (current: LoopState) => LoopState) => void;
  profiles: AgentProfile[];
  onNotice: (notice: Notice) => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [promptId, setPromptId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const openChatMutation = useMutation({
    mutationFn: async (handle: string) => {
      if (!state.activeUser) {
        throw new Error("Sign in before opening chat.");
      }
      const owner = state.activeUser.user_id;
      const existing = await queryClient.fetchQuery({
        queryKey: ["social-agent-chats", api.baseUrl, owner],
        queryFn: () => api.getAgentChats(owner),
        staleTime: 10_000,
      });
      const match = existing.items.find((chat) => chat.agent_handle === handle);
      if (match) {
        return match;
      }
      const result = await api.createAgentChat({
        owner_user_id: owner,
        agent_handle: handle,
      });
      return result.chat;
    },
    onSuccess: (chat) => {
      void queryClient.invalidateQueries({ queryKey: ["social-agent-chats"] });
      navigate(`/chat/${chat.chat_id}`);
    },
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  function rememberUpdatedProfile(updated: AgentProfile) {
    setState((current) =>
      touchLoopState({
        ...current,
        activeProfile:
          current.activeProfile?.agent_id === updated.agent_id ? updated : current.activeProfile,
        reviewProfile:
          current.reviewProfile?.agent_id === updated.agent_id ? updated : current.reviewProfile,
        ownedProfiles: current.ownedProfiles.map((profile) =>
          profile.agent_id === updated.agent_id ? updated : profile,
        ),
      }),
    );
    void queryClient.invalidateQueries({ queryKey: ["social-profiles"] });
    void queryClient.invalidateQueries({ queryKey: ["social-dashboard"] });
  }

  function rememberCreatedProfile(profile: AgentProfile) {
    setState((current) =>
      touchLoopState({
        ...current,
        activeProfile: current.activeProfile ?? profile,
        ownedProfiles: [
          profile,
          ...current.ownedProfiles.filter((owned) => owned.agent_id !== profile.agent_id),
        ],
      }),
    );
    void queryClient.invalidateQueries({ queryKey: ["social-profiles"] });
    void queryClient.invalidateQueries({ queryKey: ["social-dashboard"] });
    void queryClient.invalidateQueries({ queryKey: ["social-feed"] });
  }

  return (
    <div className="mx-auto max-w-[940px]">
      <header className="mb-[18px] flex flex-wrap items-baseline gap-3">
        <h1 className="m-0 text-[1.4rem] font-extrabold tracking-[-0.02em]">
          Flock<span className="text-accent">.</span>
        </h1>
        <span className="text-[0.84rem] font-bold text-faint">your gulls and the harbor they fly from</span>
      </header>

      <FlockSky
        profiles={profiles}
        onOpenChat={(handle) => openChatMutation.mutate(handle)}
      />

      <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-3">
        {profiles.map((profile) => (
          <GullCard
            key={profile.agent_id}
            api={api}
            state={state}
            profile={profile}
            editing={editingId === profile.agent_id}
            editingPrompt={promptId === profile.agent_id}
            isPrimary={state.activeProfile?.agent_id === profile.agent_id}
            onMakePrimary={() => {
              setState((current) => touchLoopState({ ...current, activeProfile: profile }));
              onNotice({ tone: "ok", message: `${shortHandle(profile.handle)} is now your primary gull.` });
            }}
            onEdit={() => {
              setPromptId(null);
              setEditingId(profile.agent_id);
            }}
            onPrompt={() => {
              setEditingId(null);
              setPromptId(profile.agent_id);
            }}
            onCancel={() => {
              setEditingId(null);
              setPromptId(null);
            }}
            onSaved={(updated) => {
              setEditingId(null);
              rememberUpdatedProfile(updated);
              onNotice({ tone: "ok", message: `${shortHandle(updated.handle)} saved.` });
            }}
            onChat={() => openChatMutation.mutate(profile.handle)}
            onNotice={onNotice}
          />
        ))}
        {creating ? (
          <NewGullCard
            api={api}
            state={state}
            onCancel={() => setCreating(false)}
            onCreated={(profile) => {
              setCreating(false);
              rememberCreatedProfile(profile);
              onNotice({ tone: "ok", message: `${shortHandle(profile.handle)} joined your flock.` });
            }}
            onNotice={onNotice}
          />
        ) : (
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="grid min-h-[170px] place-content-center justify-items-center gap-2.5 rounded-xl border-[1.5px] border-dashed border-line bg-transparent p-[18px] text-muted hover:border-accent hover:text-accent-strong"
          >
            <span aria-hidden="true" className="text-2xl font-extrabold">
              +
            </span>
            <strong className="text-[0.88rem] font-extrabold">Register a new gull</strong>
            <span className="text-[0.74rem] font-bold text-faint">handle, bio, posture — ready in a minute</span>
          </button>
        )}
      </div>
    </div>
  );
}

function FlockSky({
  profiles,
  onOpenChat,
}: {
  profiles: AgentProfile[];
  onOpenChat: (handle: string) => void;
}) {
  const shared = (a: AgentProfile, b: AgentProfile) =>
    a.capabilities.filter((capability) => b.capabilities.includes(capability)).length;

  const pool = [...profiles];
  const ordered: AgentProfile[] = pool.length ? [pool.shift()!] : [];
  while (pool.length) {
    const last = ordered[ordered.length - 1];
    pool.sort((x, y) => shared(last, y) - shared(last, x));
    ordered.push(pool.shift()!);
  }

  let distance = 0;
  const units = ordered.map((profile, index) => {
    if (index > 0) {
      const previous = ordered[index - 1];
      distance += previous.capabilities.some((capability) => profile.capabilities.includes(capability))
        ? 0.8
        : 1.8;
    }
    return distance;
  });
  const spread = Math.max(Math.min(76, distance * 24), ordered.length > 1 ? 24 : 0);

  return (
    <div
      role="group"
      aria-label="The sky over your harbor — your flock on the wire, other harbors' gulls passing overhead"
      className="relative mb-3.5 h-[200px] overflow-hidden rounded-xl border border-line bg-card"
    >
      <PassingFlock />
      <span aria-hidden="true" className="absolute top-[70%] right-0 left-0 border-t-[1.5px] border-line" />
      {ordered.map((profile, index) => {
        const x =
          ordered.length === 1
            ? "50%"
            : `${(50 - spread / 2 + (units[index] / distance) * spread).toFixed(1)}%`;
        const away = profile.status !== "active";
        return (
          <button
            key={profile.agent_id}
            type="button"
            onClick={() => onOpenChat(profile.handle)}
            title={`${shortHandle(profile.handle)}${away ? " is away" : " is home"} · knows ${
              profile.capabilities.join(", ") || "nothing yet"
            } — click to chat`}
            className="absolute top-[70%] grid -translate-x-1/2 -translate-y-[15px] cursor-pointer justify-items-center gap-1.5 border-0 bg-transparent px-2 text-(--tint) hover:text-accent-strong"
            style={{ left: x, opacity: away ? 0.42 : 1, "--tint": tintFor(profile.handle) } as CSSProperties}
          >
            <span aria-hidden="true" className="block origin-bottom scale-y-[0.68]">
              <Wing path={wingFor(profile.handle)} size={30} strokeWidth={2.6} />
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-[5px] w-[5px] rounded-full" style={{ background: statusDotColor(profile.status) }} />
              <span className="text-[0.72rem] font-extrabold whitespace-nowrap text-muted">
                {shortHandle(profile.handle)}
              </span>
            </span>
          </button>
        );
      })}
      {profiles.length === 0 ? (
        <div className="absolute inset-0 grid place-items-center">
          <span className="text-[0.84rem] font-bold text-faint">an empty wire — register your first gull below</span>
        </div>
      ) : null}
      <span className="absolute right-3 bottom-2 text-[0.68rem] font-bold text-faint">
        birds of a feather perch close · dim = away
      </span>
    </div>
  );
}

function GullCard({
  api,
  state,
  profile,
  editing,
  editingPrompt,
  isPrimary,
  onMakePrimary,
  onEdit,
  onPrompt,
  onCancel,
  onSaved,
  onChat,
  onNotice,
}: {
  api: SocialApiClient;
  state: LoopState;
  profile: AgentProfile;
  editing: boolean;
  editingPrompt: boolean;
  isPrimary: boolean;
  onMakePrimary: () => void;
  onEdit: () => void;
  onPrompt: () => void;
  onCancel: () => void;
  onSaved: (profile: AgentProfile) => void;
  onChat: () => void;
  onNotice: (notice: Notice) => void;
}) {
  const [name, setName] = useState(profile.display_name ?? "");
  const [bio, setBio] = useState(profile.bio ?? "");
  const [capabilities, setCapabilities] = useState(profile.capabilities.join(", "));
  const [posture, setPosture] = useState<RelationshipPosture>(profile.relationship_posture);
  const ownerUserId = state.activeUser?.user_id;
  const showPrompt = editingPrompt && ownerUserId === profile.owner_user_id;

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!state.activeUser) {
        throw new Error("Sign in before editing a gull.");
      }
      const result = await api.updateProfile(profile.handle, {
        owner_user_id: state.activeUser.user_id,
        display_name: name,
        bio,
        capabilities: parseCommaList(capabilities),
        // Only send the posture when it changed: a posture write may reset
        // server-derived approval settings for the profile.
        ...(posture !== profile.relationship_posture ? { relationship_posture: posture } : {}),
      });
      return result.profile;
    },
    onSuccess: onSaved,
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  function startEdit() {
    setName(profile.display_name ?? "");
    setBio(profile.bio ?? "");
    setCapabilities(profile.capabilities.join(", "));
    setPosture(profile.relationship_posture);
    onEdit();
  }

  return (
    <article
      className="grid min-w-0 content-start gap-3 rounded-xl border bg-card p-[18px]"
      style={{
        borderColor: editing || showPrompt ? "var(--accent)" : "var(--line)",
        gridColumn: editing || showPrompt ? "1 / -1" : "auto",
      }}
    >
      <div className="flex items-center gap-3">
        <GullAvatar handle={profile.handle} size={38} background={tintFor(profile.handle)} />
        <span className="min-w-0 flex-1">
          <strong className="block text-[0.95rem]">{displayLabel(profile)}</strong>
          <span className="flex items-center gap-1.5 text-[0.72rem] font-extrabold text-faint">
            <span className="h-[5px] w-[5px] rounded-full" style={{ background: statusDotColor(profile.status) }} />
            {profile.status} · {profile.node_id ?? "no node"}
          </span>
        </span>
        <button
          type="button"
          onClick={onChat}
          title={`Chat with ${shortHandle(profile.handle)}`}
          className="min-h-[30px] flex-none rounded-[7px] border-[1.5px] border-line bg-transparent px-2.5 text-[0.74rem] font-extrabold text-ink hover:border-accent hover:text-accent-strong"
        >
          Chat
        </button>
      </div>

      {showPrompt && ownerUserId ? (
        <GullPromptEditor
          key={`${api.baseUrl}:${ownerUserId}:${profile.agent_id}`}
          api={api}
          ownerUserId={ownerUserId}
          profile={profile}
          onClose={onCancel}
          onNotice={onNotice}
        />
      ) : !editing ? (
        <>
          <p className="m-0 text-[0.86rem] leading-normal text-body">
            {profile.bio?.trim() || "No bio yet — this gull is still finding its voice."}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {profile.capabilities.map((capability) => (
              <Chip key={capability}>{capability}</Chip>
            ))}
            <Chip tone={profile.relationship_posture === "needs_approval" ? "amber" : "accent"}>
              {postureLabel(profile.relationship_posture)}
            </Chip>
          </div>
          <div className="flex min-w-0 items-center gap-2.5">
            <button
              type="button"
              onClick={startEdit}
              className="border-0 bg-transparent p-0 text-[0.78rem] font-extrabold text-accent-strong hover:text-accent"
            >
              Edit
            </button>
            {ownerUserId === profile.owner_user_id ? (
              <button
                type="button"
                onClick={onPrompt}
                className="border-0 bg-transparent p-0 text-[0.78rem] font-extrabold text-accent-strong hover:text-accent"
              >
                Prompt
              </button>
            ) : null}
            {isPrimary ? (
              <Chip tone="accent">primary</Chip>
            ) : (
              <button
                type="button"
                onClick={onMakePrimary}
                title="Post and receive traffic as this gull"
                className="border-0 bg-transparent p-0 text-[0.78rem] font-extrabold whitespace-nowrap text-muted hover:text-accent-strong"
              >
                Make primary
              </button>
            )}
            <span className="ml-auto min-w-0 truncate text-[0.7rem] font-bold text-faint" title={profile.agent_id}>
              {profile.agent_id}
            </span>
          </div>
        </>
      ) : (
        <form
          className="grid w-full gap-2.5"
          onSubmit={(event: FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            saveMutation.mutate();
          }}
        >
          <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
            Display name
            <input value={name} onChange={(event) => setName(event.target.value)} className="bg-bg text-[0.88rem]" />
          </label>
          <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
            Bio
            <textarea
              rows={2}
              value={bio}
              onChange={(event) => setBio(event.target.value)}
              className="bg-bg text-[0.88rem]"
            />
          </label>
          <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
            Capabilities · comma separated
            <input
              value={capabilities}
              onChange={(event) => setCapabilities(event.target.value)}
              className="bg-bg text-[0.88rem]"
            />
          </label>
          <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
            Relationship posture
            <select
              value={posture}
              onChange={(event) => setPosture(event.target.value as RelationshipPosture)}
              className="bg-bg text-[0.88rem]"
            >
              {POSTURES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="submit"
              disabled={saveMutation.isPending}
              className="min-h-9 rounded-lg border-0 bg-accent px-4 text-[0.82rem] font-extrabold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
            >
              Save
            </button>
            <button
              type="button"
              onClick={onCancel}
              className="min-h-9 rounded-lg border-[1.5px] border-line bg-transparent px-3.5 text-[0.82rem] font-extrabold text-muted hover:border-accent"
            >
              Cancel
            </button>
            <span className="ml-auto text-[0.7rem] font-bold text-faint">{profile.handle}</span>
          </div>
        </form>
      )}
    </article>
  );
}

function GullPromptEditor({
  api,
  ownerUserId,
  profile,
  onClose,
  onNotice,
}: {
  api: SocialApiClient;
  ownerUserId: string;
  profile: AgentProfile;
  onClose: () => void;
  onNotice: (notice: Notice) => void;
}) {
  const queryClient = useQueryClient();
  const helpId = useId();
  const [draft, setDraft] = useState<string | null>(null);
  const queryKey = ["social-agent-prompt", api.baseUrl, ownerUserId, profile.agent_id];
  const promptQuery = useQuery({
    queryKey,
    queryFn: () => api.getAgentPrompt(profile.handle, ownerUserId),
    retry: false,
    refetchOnWindowFocus: false,
    gcTime: 0,
  });
  const savedInstructions = promptQuery.data?.prompt?.instructions ?? "";
  const instructions = draft ?? savedInstructions;
  const dirty = instructions.trim() !== savedInstructions;
  const saveMutation = useMutation({
    mutationFn: (content: string) => api.setAgentPrompt(profile.handle, {
      owner_user_id: ownerUserId,
      instructions: content,
    }),
    onSuccess: (result) => {
      queryClient.setQueryData(queryKey, result);
      void queryClient.invalidateQueries({ queryKey: ["social-agent-chats", api.baseUrl, ownerUserId] });
      onNotice({
        tone: "ok",
        message: result.prompt
          ? `${shortHandle(profile.handle)} will use this prompt from the next reply.`
          : `${shortHandle(profile.handle)} will use default replies from the next message.`,
      });
      onClose();
    },
  });

  return (
    <section aria-label={`Reply prompt for ${displayLabel(profile)}`} className="grid gap-3 border-t border-line pt-3">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="m-0 text-[1rem] font-extrabold">Reply prompt</h2>
          <Chip tone="accent">Private</Chip>
          <span className="ml-auto break-all text-[0.72rem] font-bold text-faint">{profile.handle}</span>
        </div>
        <p className="mt-1 mb-0 text-[0.8rem] leading-relaxed text-muted">
          Give {displayLabel(profile)} a role, a voice, and rules to follow.
        </p>
      </div>

      {promptQuery.isPending ? (
        <p role="status" className="m-0 py-6 text-[0.84rem] text-muted">Loading this gull's prompt…</p>
      ) : promptQuery.isError ? (
        <div role="alert" className="grid justify-items-start gap-2 rounded-lg bg-danger-soft p-3 text-[0.82rem] text-danger">
          <span>Could not load the prompt. {promptQuery.error.message}</span>
          <button type="button" onClick={() => void promptQuery.refetch()} className="font-extrabold underline">
            Try again
          </button>
        </div>
      ) : (
        <form
          className="grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (dirty && !saveMutation.isPending) {
              saveMutation.mutate(instructions.trim());
            }
          }}
        >
          <label className="grid gap-1.5 text-[0.74rem] font-extrabold text-muted">
            Reply instructions
            <textarea
              rows={9}
              value={instructions}
              maxLength={12000}
              disabled={saveMutation.isPending}
              aria-describedby={helpId}
              onChange={(event) => {
                setDraft(event.target.value);
                saveMutation.reset();
              }}
              placeholder={"You are my research assistant.\nKeep replies concise and practical.\nAsk when details are missing, and say when you are unsure."}
              className="bg-bg text-[0.88rem] font-normal leading-relaxed disabled:opacity-60"
            />
          </label>
          <div className="flex flex-wrap items-start justify-between gap-2 text-[0.72rem] text-faint">
            <span id={helpId} className="max-w-[580px] leading-relaxed">
              Only you can see this prompt. It applies to this gull's next reply in new and existing chats.
              Leave it blank to use default replies.
            </span>
            <span className="tabular-nums">{instructions.length.toLocaleString()} / 12,000</span>
          </div>
          {saveMutation.isError ? (
            <p role="alert" className="m-0 rounded-lg bg-danger-soft p-3 text-[0.82rem] text-danger">
              Could not save the prompt. Your changes are still here. {saveMutation.error.message}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="submit"
              disabled={!dirty || saveMutation.isPending}
              className="min-h-9 rounded-lg border-0 bg-accent px-4 text-[0.82rem] font-extrabold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
            >
              {saveMutation.isPending ? "Saving…" : "Save prompt"}
            </button>
            <button
              type="button"
              disabled={saveMutation.isPending}
              onClick={onClose}
              className="min-h-9 rounded-lg border-[1.5px] border-line bg-transparent px-3.5 text-[0.82rem] font-extrabold text-muted hover:border-accent disabled:opacity-60"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={!instructions || saveMutation.isPending}
              onClick={() => {
                setDraft("");
                saveMutation.reset();
              }}
              className="ml-auto min-h-9 border-0 bg-transparent px-1 text-[0.76rem] font-extrabold text-muted hover:text-accent-strong disabled:cursor-not-allowed disabled:opacity-50"
            >
              Reset to default
            </button>
          </div>
        </form>
      )}
      {(promptQuery.isPending || promptQuery.isError) ? (
        <button type="button" onClick={onClose} className="min-h-9 justify-self-start text-[0.82rem] font-extrabold text-muted">
          Cancel
        </button>
      ) : null}
    </section>
  );
}

function NewGullCard({
  api,
  state,
  onCancel,
  onCreated,
  onNotice,
}: {
  api: SocialApiClient;
  state: LoopState;
  onCancel: () => void;
  onCreated: (profile: AgentProfile) => void;
  onNotice: (notice: Notice) => void;
}) {
  const [handle, setHandle] = useState("");
  const [name, setName] = useState("");
  const [bio, setBio] = useState("");
  const [capabilities, setCapabilities] = useState("");
  const [posture, setPosture] = useState<RelationshipPosture>("needs_approval");

  const createMutation = useMutation({
    mutationFn: async () => {
      if (!state.activeUser) {
        throw new Error("Sign in before registering a gull.");
      }
      const result = await api.createProfile({
        owner_user_id: state.activeUser.user_id,
        handle: handle.trim(),
        display_name: name.trim() || undefined,
        bio: bio.trim() || undefined,
        capabilities: parseCommaList(capabilities),
        relationship_posture: posture,
        protocols: ["seagull"],
      });
      return result.profile;
    },
    onSuccess: onCreated,
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  return (
    <article className="col-span-full grid content-start gap-3 rounded-xl border border-accent bg-card p-[18px]">
      <div className="flex items-center gap-3">
        <span className="grid h-[38px] w-[38px] flex-none place-items-center rounded-full border border-dashed border-faint text-muted">
          <Wing path={wingFor(handle || "@new")} size={19} strokeWidth={3.2} />
        </span>
        <strong className="text-[0.95rem]">Register a new gull</strong>
      </div>
      <form
        className="grid grid-cols-2 gap-2.5 max-[620px]:grid-cols-1"
        onSubmit={(event) => {
          event.preventDefault();
          if (handle.trim()) {
            createMutation.mutate();
          }
        }}
      >
        <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
          Handle
          <input
            value={handle}
            onChange={(event) => setHandle(event.target.value)}
            placeholder="@scout:seagull.local"
            spellCheck={false}
            className="bg-bg text-[0.88rem]"
          />
        </label>
        <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
          Display name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Scout"
            className="bg-bg text-[0.88rem]"
          />
        </label>
        <label className="col-span-full grid gap-1 text-[0.72rem] font-extrabold text-muted">
          Bio
          <textarea
            rows={2}
            value={bio}
            onChange={(event) => setBio(event.target.value)}
            className="bg-bg text-[0.88rem]"
          />
        </label>
        <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
          Capabilities · comma separated
          <input
            value={capabilities}
            onChange={(event) => setCapabilities(event.target.value)}
            placeholder="research, planning"
            className="bg-bg text-[0.88rem]"
          />
        </label>
        <label className="grid gap-1 text-[0.72rem] font-extrabold text-muted">
          Relationship posture
          <select
            value={posture}
            onChange={(event) => setPosture(event.target.value as RelationshipPosture)}
            className="bg-bg text-[0.88rem]"
          >
            {POSTURES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <div className="col-span-full flex gap-2">
          <button
            type="submit"
            disabled={!handle.trim() || createMutation.isPending}
            className="min-h-9 rounded-lg border-0 bg-accent px-4 text-[0.82rem] font-extrabold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
          >
            Register gull
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="min-h-9 rounded-lg border-[1.5px] border-line bg-transparent px-3.5 text-[0.82rem] font-extrabold text-muted hover:border-accent"
          >
            Cancel
          </button>
        </div>
      </form>
    </article>
  );
}

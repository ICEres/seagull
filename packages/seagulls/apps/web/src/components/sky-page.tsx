import { CSSProperties, FormEvent, KeyboardEvent, useState } from "react";
import { useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { recordedMatchesReview, type OpenUrlEffect } from "../lib/action-effect";
import { SocialApiClient, SocialApiError } from "../lib/api";
import {
  MessageHubClient,
  MessageHubError,
  type InboxItem,
  type MessageRef,
  type WorkflowTraceEntry,
} from "../lib/message-hub";
import type { AgentChatSession, AgentProfile, LoopState, Notification, Post } from "../lib/social";
import { formatRelativeTime, knownProfiles } from "../lib/state";
import { GullAvatar, Wing, statusDotColor, tintFor, wingFor } from "@seagulls/ui";
import { ActionReview } from "./action-review";
import { Chip, EmptyState, displayLabel, shortHandle, type Notice } from "./shared";

type AppMutationError = Error | SocialApiError | MessageHubError;

type StreamFilter = "all" | "post" | "mention" | "traffic";

type StreamItem =
  | { kind: "post"; id: string; createdAt: string; post: Post; replies: Post[] }
  | { kind: "traffic"; id: string; createdAt: string; item: InboxItem };

export function SkyPage({
  api,
  messageApi,
  state,
  posts,
  profiles,
  notifications,
  rememberPost,
  onNotice,
}: {
  api: SocialApiClient;
  messageApi: MessageHubClient;
  state: LoopState;
  posts: Post[];
  profiles: AgentProfile[];
  notifications: Notification[];
  rememberPost: (post: Post) => void;
  onNotice: (notice: Notice) => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<StreamFilter>("all");
  const [draft, setDraft] = useState("");
  const [postToRoom, setPostToRoom] = useState(false);
  const [flyingWing, setFlyingWing] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const activeProfile = state.activeProfile;
  const activeUser = state.activeUser;
  const ownedIds = new Set(profiles.map((profile) => profile.agent_id));
  const unreadMentionPostIds = new Set(
    notifications
      .filter((notification) => !notification.read_at && notification.post_id)
      .map((notification) => notification.post_id as string),
  );

  const inboxQuery = useQuery({
    queryKey: ["message-inbox", messageApi.baseUrl, activeProfile?.handle],
    queryFn: () => messageApi.getInbox(activeProfile!.handle, 20),
    enabled: Boolean(activeProfile),
    retry: false,
  });
  const trafficItems = inboxQuery.data?.items ?? [];
  const hubNotRegistered = inboxQuery.error instanceof MessageHubError && inboxQuery.error.status === 404;

  const registerHubMutation = useMutation({
    mutationFn: () =>
      messageApi.registerAgent({
        handle: activeProfile!.handle,
        display_name: activeProfile?.display_name ?? undefined,
        capabilities: activeProfile?.capabilities ?? [],
      }),
    onSuccess: () => {
      onNotice({ tone: "ok", message: "Gull registered with the message hub." });
      void inboxQuery.refetch();
    },
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  function routedProfile(value: string): AgentProfile | null {
    const match = value.trim().match(/^@([a-z0-9_.-]+)/i);
    if (!match) {
      return null;
    }
    const token = match[1].toLowerCase();
    return (
      profiles.find((profile) => {
        const bare = profile.handle.toLowerCase().replace(/^@/, "").split(":")[0];
        return bare === token || profile.handle.toLowerCase() === `@${token}`;
      }) ?? null
    );
  }
  const routed = routedProfile(draft);

  // Reuse an existing chat session with this gull when one exists so casual
  // clicks and @-sends do not pile up duplicate sessions server-side.
  async function acquireChat(handle: string): Promise<AgentChatSession> {
    if (!activeUser) {
      throw new Error("Sign in before opening chat.");
    }
    const owner = activeUser.user_id;
    const existing = await queryClient.fetchQuery({
      queryKey: ["social-agent-chats", api.baseUrl, owner],
      queryFn: () => api.getAgentChats(owner),
      staleTime: 10_000,
    });
    const match = existing.items.find((chat) => chat.agent_handle === handle);
    if (match) {
      return match;
    }
    return (await api.createAgentChat({ owner_user_id: owner, agent_handle: handle })).chat;
  }

  const openChatMutation = useMutation({
    mutationFn: (handle: string) => acquireChat(handle),
    onSuccess: (chat) => {
      void queryClient.invalidateQueries({ queryKey: ["social-agent-chats"] });
      navigate(`/chat/${chat.chat_id}`);
    },
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  const sendDirectMutation = useMutation({
    mutationFn: async ({ target, body }: { target: AgentProfile; body: string }) => {
      if (!activeUser) {
        throw new Error("Sign in before sending.");
      }
      const chat = await acquireChat(target.handle);
      const result = await api.createAgentChatMessage(chat.chat_id, {
        owner_user_id: activeUser.user_id,
        content: body,
      });
      return { chat, result };
    },
    onSuccess: ({ result }, { target }) => {
      setDraft("");
      setFlyingWing(wingFor(target.handle));
      window.setTimeout(() => setFlyingWing(null), 950);
      void queryClient.invalidateQueries({ queryKey: ["social-agent-chats"] });
      void queryClient.invalidateQueries({ queryKey: ["social-agent-chat-messages"] });
      const failed = result.message.delivery_status === "delivery_failed" || Boolean(result.message.ai_error);
      onNotice({
        tone: failed ? "warn" : "ok",
        message: failed
          ? `Message stored for ${shortHandle(target.handle)}; delivery is delayed.`
          : `Flew direct to ${shortHandle(target.handle)} — thread in Chat.`,
      });
    },
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  const sendPostMutation = useMutation({
    mutationFn: async (body: string) => {
      if (!activeUser || !activeProfile) {
        throw new Error("Register a gull before posting to the sky.");
      }
      const result = await api.createPost({
        owner_user_id: activeUser.user_id,
        author_handle: activeProfile.handle,
        content: body,
        visibility: postToRoom && state.room ? "room" : "public",
        room_slug: postToRoom && state.room ? state.room.slug : undefined,
      });
      return result.post;
    },
    onSuccess: (post) => {
      setDraft("");
      rememberPost(post);
      void queryClient.invalidateQueries({ queryKey: ["social-feed"] });
      void queryClient.invalidateQueries({ queryKey: ["social-notifications"] });
    },
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  function submitDraft(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const text = draft.trim();
    if (!text || sendDirectMutation.isPending || sendPostMutation.isPending) {
      return;
    }
    if (routed) {
      // Strip the full mention prefix, including a ":domain" handle suffix.
      const body = text.replace(/^@[a-z0-9_.:-]+,?\s*/i, "") || text;
      sendDirectMutation.mutate({ target: routed, body });
      return;
    }
    sendPostMutation.mutate(text);
  }

  function onDraftKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submitDraft();
    }
  }

  const byId = new Map(posts.map((post) => [post.post_id, post]));
  function rootOf(post: Post): Post {
    let current = post;
    const seen = new Set<string>();
    while (current.reply_to_post_id && byId.has(current.reply_to_post_id) && !seen.has(current.post_id)) {
      seen.add(current.post_id);
      current = byId.get(current.reply_to_post_id)!;
    }
    return current;
  }
  const replyGroups = new Map<string, Post[]>();
  const roots: Post[] = [];
  for (const post of posts) {
    if (post.reply_to_post_id && byId.has(post.reply_to_post_id)) {
      const root = rootOf(post);
      const group = replyGroups.get(root.post_id) ?? [];
      group.push(post);
      replyGroups.set(root.post_id, group);
    } else {
      roots.push(post);
    }
  }
  for (const group of replyGroups.values()) {
    group.sort((a, b) => a.created_at.localeCompare(b.created_at));
  }

  const streamItems: StreamItem[] = [
    ...roots.map((post) => ({
      kind: "post" as const,
      id: post.post_id,
      createdAt: post.created_at,
      post,
      replies: replyGroups.get(post.post_id) ?? [],
    })),
    ...trafficItems.map((item) => ({
      kind: "traffic" as const,
      id: item.delivery.delivery_id,
      createdAt: item.delivery.created_at,
      item,
    })),
  ].sort((a, b) => b.createdAt.localeCompare(a.createdAt));

  const mentionsPost = (post: Post) => post.mention_agent_ids.some((id) => ownedIds.has(id));
  const visibleItems = streamItems.filter((item) => {
    if (filter === "all") {
      return true;
    }
    if (filter === "post") {
      return item.kind === "post";
    }
    if (filter === "mention") {
      return item.kind === "post" && mentionsPost(item.post);
    }
    return item.kind === "traffic";
  });

  const mentionUnread = notifications.filter((notification) => !notification.read_at).length;
  const waitingTraffic = trafficItems.filter((item) => item.delivery.current_stage === "agent.wait").length;
  const waiting = mentionUnread + waitingTraffic;
  const activeCount = profiles.filter((profile) => profile.status === "active").length;
  const skySub = `${profiles.length} ${profiles.length === 1 ? "gull" : "gulls"} in your flock · ${activeCount} online · ${
    waiting > 0 ? `${waiting} waiting on you` : "all clear"
  }`;

  const filters: Array<{ key: StreamFilter; label: string; count?: number }> = [
    { key: "all", label: "All" },
    { key: "post", label: "Posts" },
    { key: "mention", label: "Mentions", count: mentionUnread },
    { key: "traffic", label: "Traffic", count: waitingTraffic },
  ];

  // Owned profiles plus any locally-known ones (e.g. the seeded review agent),
  // so stream bylines show handles instead of raw agent ids.
  const profileIndex = new Map(
    [...knownProfiles(state), ...profiles].map((profile) => [profile.agent_id, profile]),
  );
  const authorOf = (agentId: string): AgentProfile | null => profileIndex.get(agentId) ?? null;

  const perchFlock = profiles.slice(0, 5);
  if (routed && !perchFlock.some((profile) => profile.agent_id === routed.agent_id)) {
    perchFlock[Math.max(0, perchFlock.length - 1)] = routed;
  }

  return (
    <div className="mx-auto w-[min(680px,100%)]">
      <header className="mb-[34px] flex flex-wrap items-baseline gap-3">
        <h1 className="m-0 text-[1.4rem] font-extrabold tracking-[-0.02em]">
          The sky<span className="text-accent">.</span>
        </h1>
        <span className="text-[0.84rem] font-bold text-faint">{skySub}</span>
      </header>

      {activeProfile ? (
        <form
          onSubmit={submitDraft}
          className="relative mb-[26px] box-border rounded-[10px] border-2 bg-card px-2 py-1 shadow-panel transition-colors"
          style={{ borderColor: draft ? "var(--accent)" : "var(--line)" }}
        >
          <div
            role="group"
            aria-label="Your flock — click a gull to chat"
            className="absolute top-0 right-[18px] flex -translate-y-full items-end gap-4"
          >
            {perchFlock.map((profile, index) => {
              const isRouted = routed?.agent_id === profile.agent_id;
              return (
                <button
                  key={profile.agent_id}
                  type="button"
                  onClick={() => openChatMutation.mutate(profile.handle)}
                  title={`Chat with ${shortHandle(profile.handle)} · ${profile.status}`}
                  className="relative block border-0 bg-transparent px-0.5 pt-0.5 pb-0 text-(--tint) transition-colors hover:text-accent-strong"
                  style={{ "--tint": isRouted ? "var(--accent)" : tintFor(profile.handle) } as CSSProperties}
                >
                  <Wing
                    path={wingFor(profile.handle)}
                    size={[22, 18, 16, 20, 17][index % 5]}
                    style={isRouted ? { animation: "gull-flap 0.6s ease-in-out infinite" } : undefined}
                  />
                  <span
                    aria-hidden="true"
                    className="absolute -bottom-0.5 left-1/2 h-1 w-1 -translate-x-1/2 rounded-full"
                    style={{ background: statusDotColor(profile.status) }}
                  />
                </button>
              );
            })}
            <button
              type="button"
              onClick={() => navigate("/flock")}
              title="Register a new gull"
              aria-label="Register a new gull"
              className="mb-[3px] grid h-[18px] w-[18px] place-items-center rounded-full border border-dashed border-faint bg-card p-0 text-[0.7rem] font-black text-muted hover:border-accent hover:text-accent-strong"
            >
              +
            </button>
          </div>

          {flyingWing ? (
            <span
              aria-hidden="true"
              className="pointer-events-none absolute -top-1 right-[60px] text-accent"
              style={{ animation: "fly-off 0.9s ease-in forwards" }}
            >
              <Wing path={flyingWing} size={26} style={{ animation: "gull-flap 0.3s ease-in-out infinite" }} />
            </span>
          ) : null}

          <div className="flex items-end gap-2 px-1.5 py-0.5">
            <textarea
              rows={1}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={onDraftKey}
              placeholder="Speak to the sky — @gull to send direct"
              aria-label="Composer"
              className="box-border max-h-[140px] min-h-[44px] flex-1 resize-none border-0 bg-transparent px-1 py-[11px] text-base leading-[1.45]"
            />
          </div>
          <div className="flex items-center gap-2.5 px-1.5 pb-2 pl-2.5">
            <span
              className="text-[0.72rem] font-extrabold"
              style={{ color: routed ? "var(--accent-strong)" : "var(--faint)" }}
            >
              {routed
                ? `direct to ${shortHandle(routed.handle)} — flies now`
                : "@gull sends direct · plain text posts to the sky"}
            </span>
            {state.room ? (
              <button
                type="button"
                onClick={() => setPostToRoom((current) => !current)}
                className={`rounded-full border-0 px-2.5 py-1 text-[0.7rem] font-extrabold ${
                  postToRoom ? "bg-indigo-soft text-indigo" : "bg-bg text-faint"
                }`}
                title={postToRoom ? `Posting to ${state.room.name}` : `Post to ${state.room.name}`}
              >
                {state.room.name}
              </button>
            ) : null}
            <span className="flex-1" />
            {draft.trim() ? (
              <span aria-hidden="true" className="whitespace-nowrap text-[0.74rem] font-extrabold text-accent">
                ⏎ Enter
              </span>
            ) : null}
            <button
              type="submit"
              className="min-h-8 rounded-[7px] border-0 px-3.5 text-[0.82rem] font-extrabold text-white"
              style={{ background: draft.trim() ? "var(--accent)" : "var(--faint)" }}
            >
              Send
            </button>
          </div>
        </form>
      ) : (
        <div className="mb-[26px] grid justify-items-center gap-3 rounded-[10px] border-2 border-dashed border-line bg-card px-5 py-8 text-center">
          <Wing path={wingFor("@you")} size={34} className="text-faint" />
          <strong className="text-[1.02rem]">Register your first gull</strong>
          <span className="max-w-[42ch] text-[0.86rem] leading-normal text-muted">
            Gulls carry your words across the sky. Give one a handle and it can post, chat, and receive traffic for
            you.
          </span>
          <button
            type="button"
            onClick={() => navigate("/flock")}
            className="min-h-10 rounded-lg border-0 bg-accent px-4 font-extrabold text-white hover:bg-accent-strong"
          >
            Meet your flock
          </button>
        </div>
      )}

      <div className="mb-3.5 flex flex-wrap items-center gap-2.5">
        <h2 className="m-0 text-[0.72rem] font-black tracking-[0.08em] text-faint uppercase">The stream</h2>
        <span className="flex-1" />
        <div role="tablist" aria-label="Stream filter" className="flex flex-wrap gap-1.5">
          {filters.map((entry) => {
            const selected = filter === entry.key;
            return (
              <button
                key={entry.key}
                type="button"
                role="tab"
                aria-selected={selected}
                onClick={() => setFilter(entry.key)}
                className={`flex items-center gap-1.5 rounded-full border-0 px-3.5 py-1.5 text-[0.78rem] font-extrabold ${
                  selected ? "bg-ink text-bg" : "bg-card text-muted"
                }`}
              >
                {entry.label}
                {entry.count ? (
                  <span className="grid min-w-4 place-items-center rounded-full bg-accent px-1 text-[0.64rem] font-black text-white">
                    {entry.count}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid gap-2.5">
        {hubNotRegistered && activeProfile && (filter === "all" || filter === "traffic") ? (
          <div className="flex flex-wrap items-center gap-2.5 rounded-xl border border-dashed border-line px-[18px] py-3 text-[0.84rem] text-body">
            <Wing path={wingFor(activeProfile.handle)} size={16} className="text-muted" />
            <span className="min-w-0 flex-1">
              <strong className="text-[0.8rem]">{shortHandle(activeProfile.handle)}</strong>
              <span className="text-faint"> is not on the wire yet — register it to receive traffic.</span>
            </span>
            <button
              type="button"
              onClick={() => registerHubMutation.mutate()}
              disabled={registerHubMutation.isPending}
              className="min-h-[30px] rounded-[7px] border-0 bg-accent px-3 text-[0.76rem] font-extrabold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
            >
              Register
            </button>
          </div>
        ) : null}

        {visibleItems.length === 0 ? (
          <div className="rounded-xl border border-line bg-card">
            <EmptyState
              title="A quiet sky"
              detail={
                filter === "traffic"
                  ? "Deliveries between gulls will appear here."
                  : "Posts from your flock and mentions will appear here."
              }
            />
          </div>
        ) : (
          visibleItems.map((item) =>
            item.kind === "post" ? (
              <StreamPost
                key={item.id}
                api={api}
                state={state}
                post={item.post}
                replies={item.replies}
                author={authorOf(item.post.author_agent_id)}
                mentionsYou={mentionsPost(item.post)}
                unread={unreadMentionPostIds.has(item.post.post_id)}
                expanded={expandedId === item.id}
                onToggle={() => setExpandedId((current) => (current === item.id ? null : item.id))}
                rememberPost={rememberPost}
                onNotice={onNotice}
                authorOf={authorOf}
              />
            ) : (
              <StreamTraffic
                key={item.id}
                item={item.item}
                agentHandle={activeProfile?.handle ?? ""}
                messageApi={messageApi}
                expanded={expandedId === item.id}
                onToggle={() => setExpandedId((current) => (current === item.id ? null : item.id))}
                onChanged={() => {
                  void inboxQuery.refetch();
                }}
                onNotice={onNotice}
              />
            ),
          )
        )}
      </div>
    </div>
  );
}

function StreamPost({
  api,
  state,
  post,
  replies,
  author,
  mentionsYou,
  unread,
  expanded,
  onToggle,
  rememberPost,
  onNotice,
  authorOf,
}: {
  api: SocialApiClient;
  state: LoopState;
  post: Post;
  replies: Post[];
  author: AgentProfile | null;
  mentionsYou: boolean;
  unread: boolean;
  expanded: boolean;
  onToggle: () => void;
  rememberPost: (post: Post) => void;
  onNotice: (notice: Notice) => void;
  authorOf: (agentId: string) => AgentProfile | null;
}) {
  const queryClient = useQueryClient();
  const [replyDraft, setReplyDraft] = useState("");
  const authorHandle = author?.handle ?? post.author_agent_id;
  const roomLabel = state.room && state.room.room_id === post.room_id ? state.room.name : post.visibility;
  const isRecent = formatRelativeTime(post.created_at) === "now";

  const replyMutation = useMutation({
    mutationFn: async () => {
      if (!state.activeUser || !state.activeProfile) {
        throw new Error("Register a gull before replying.");
      }
      const result = await api.createPost({
        owner_user_id: state.activeUser.user_id,
        author_handle: state.activeProfile.handle,
        content: replyDraft,
        visibility: "public",
        reply_to_post_id: post.post_id,
      });
      return result.post;
    },
    onSuccess: (created) => {
      setReplyDraft("");
      rememberPost(created);
      void queryClient.invalidateQueries({ queryKey: ["social-feed"] });
      void queryClient.invalidateQueries({ queryKey: ["social-notifications"] });
    },
    onError: (error: Error | SocialApiError) => onNotice({ tone: "error", message: error.message }),
  });

  return (
    <article
      className="rounded-xl border bg-card px-[18px] py-4"
      style={{
        borderColor: unread ? "var(--accent)" : "var(--line)",
        animation: isRecent ? "msg-in 0.3s ease-out" : "none",
      }}
    >
      <div className="flex items-center gap-2.5">
        <GullAvatar handle={authorHandle} background={tintFor(authorHandle)} />
        <span className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <strong className="text-[0.9rem]" title={authorHandle}>
            {author ? displayLabel(author) : shortHandle(authorHandle)}
          </strong>
          <Chip tone={roomLabel === "public" ? "neutral" : "indigo"}>{roomLabel}</Chip>
          {mentionsYou ? <Chip tone="accent">mentions you</Chip> : null}
        </span>
        {unread ? <span aria-label="unread" className="h-[7px] w-[7px] flex-none rounded-full bg-accent" /> : null}
        <span className="flex-none text-[0.72rem] font-extrabold text-faint">
          {formatRelativeTime(post.created_at)}
        </span>
      </div>
      <p className="mx-0 mt-2.5 mb-0 ml-10 leading-normal text-body [overflow-wrap:anywhere]">{post.content}</p>
      <div className="mt-2.5 ml-10 flex items-center gap-3.5">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          className="border-0 bg-transparent p-0 text-[0.78rem] font-extrabold text-accent-strong hover:text-accent"
        >
          {expanded
            ? "Hide thread"
            : replies.length > 0
              ? `${replies.length} ${replies.length === 1 ? "reply" : "replies"}`
              : "Reply"}
        </button>
      </div>
      {expanded ? (
        <div className="mt-3 ml-10 grid gap-2">
          {replies.map((reply) => {
            const replyAuthor = authorOf(reply.author_agent_id);
            const replyHandle = replyAuthor?.handle ?? reply.author_agent_id;
            return (
              <div
                key={reply.post_id}
                className="flex items-start gap-2 border-l-2 border-line py-0.5 pl-3"
              >
                <GullAvatar handle={replyHandle} size={22} background={tintFor(replyHandle)} />
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-2">
                    <strong className="text-[0.8rem]" title={replyHandle}>
                      {replyAuthor ? displayLabel(replyAuthor) : shortHandle(replyHandle)}
                    </strong>
                    <span className="text-[0.68rem] font-extrabold text-faint">
                      {formatRelativeTime(reply.created_at)}
                    </span>
                  </span>
                  <span className="mt-0.5 block text-[0.86rem] leading-[1.45] text-body [overflow-wrap:anywhere]">
                    {reply.content}
                  </span>
                </span>
              </div>
            );
          })}
          <form
            className="mt-0.5 flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (replyDraft.trim()) {
                replyMutation.mutate();
              }
            }}
          >
            <input
              value={replyDraft}
              onChange={(event) => setReplyDraft(event.target.value)}
              placeholder="Reply in thread…"
              aria-label="Reply"
              className="min-h-9 min-w-0 flex-1 bg-bg px-3"
            />
            <button
              type="submit"
              disabled={!replyDraft.trim() || replyMutation.isPending}
              className="min-h-9 rounded-lg border-0 bg-accent px-3.5 text-[0.8rem] font-extrabold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
            >
              Reply
            </button>
          </form>
        </div>
      ) : null}
    </article>
  );
}

function trafficText(item: InboxItem): string {
  return (
    item.current_message?.content_inline ??
    item.delivery.current_content_inline ??
    item.message.content_inline ??
    item.message.refs?.[0]?.url ??
    "(no text)"
  );
}

function StreamTraffic({
  item,
  agentHandle,
  messageApi,
  expanded,
  onToggle,
  onChanged,
  onNotice,
}: {
  item: InboxItem;
  agentHandle: string;
  messageApi: MessageHubClient;
  expanded: boolean;
  onToggle: () => void;
  onChanged: () => void;
  onNotice: (notice: Notice) => void;
}) {
  const delivery = item.delivery;
  const fromHandle = delivery.sender_handle ?? item.message.sender_agent_id;
  const toHandle = delivery.recipient_handle ?? agentHandle;
  const waitingOnAgent = delivery.current_stage === "agent.wait";

  return (
    <div className="rounded-xl border border-dashed border-line">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        data-testid={`traffic-toggle-${delivery.delivery_id}`}
        className="flex w-full flex-wrap items-center gap-2.5 border-0 bg-transparent px-[18px] py-3 text-left text-ink"
      >
        <span aria-hidden="true" className="flex flex-none items-center gap-1.5 text-muted">
          <Wing path={wingFor(fromHandle)} size={16} strokeWidth={3.2} />
          <span className="text-[0.72rem] font-black">→</span>
          <Wing path={wingFor(toHandle)} size={16} strokeWidth={3.2} />
        </span>
        <span className="min-w-0 flex-1 text-[0.84rem] text-body">
          <strong className="text-[0.8rem]">{shortHandle(fromHandle)}</strong>
          <span className="text-faint"> to </span>
          <strong className="text-[0.8rem]">{shortHandle(toHandle)}</strong>
          <span className="text-faint"> · </span>
          {trafficText(item)}
        </span>
        <span className="ml-auto flex flex-none items-center gap-2">
          <span className="text-[0.72rem] font-extrabold text-faint">
            {formatRelativeTime(delivery.created_at)}
          </span>
          {waitingOnAgent ? <Chip tone="amber">waiting on you</Chip> : <Chip>{delivery.status}</Chip>}
        </span>
      </button>
      {expanded ? (
        <DeliveryDetail
          item={item}
          agentHandle={agentHandle}
          messageApi={messageApi}
          onChanged={onChanged}
          onNotice={onNotice}
        />
      ) : null}
    </div>
  );
}

function DeliveryDetail({
  item,
  agentHandle,
  messageApi,
  onChanged,
  onNotice,
}: {
  item: InboxItem;
  agentHandle: string;
  messageApi: MessageHubClient;
  onChanged: () => void;
  onNotice: (notice: Notice) => void;
}) {
  const [preparedText, setPreparedText] = useState(
    item.current_message?.content_inline ?? item.message.content_inline ?? "",
  );
  const [replyText, setReplyText] = useState("");
  // Bumped after a recorded action so the review form starts over.
  const [actionReviewKey, setActionReviewKey] = useState(0);
  const currentRefs = item.current_message?.refs?.length ? item.current_message.refs : item.message.refs ?? [];
  const senderUrls = [...(item.message.refs ?? []), ...(item.current_message?.refs ?? [])].flatMap((ref) =>
    ref.url ? [ref.url] : [],
  );

  const hookMutation = useMutation({
    mutationFn: () =>
      messageApi.submitHookResult(item.delivery.delivery_id, {
        hook: "receive.before",
        runtime: "cloud_node",
        actor: agentHandle,
        content: preparedText,
      }),
    onSuccess: () => {
      onNotice({ tone: "ok", message: "Hook result saved." });
      onChanged();
    },
    onError: (error: Error | MessageHubError) => onNotice({ tone: "error", message: error.message }),
  });

  const decisionMutation = useMutation({
    mutationFn: (
      choice:
        | { decision: "reply" | "ignore" | "ask_human" }
        | { decision: "action"; effect: OpenUrlEffect },
    ) => {
      if (choice.decision === "reply") {
        return messageApi.submitDecision(item.delivery.delivery_id, {
          agent_handle: agentHandle,
          decision: choice.decision,
          content: replyText,
        });
      }
      if (choice.decision === "action") {
        // Only the reviewed effect is sent, including the approval requirement
        // the summary promised, rather than relying on the hub's default.
        return messageApi.submitDecision(item.delivery.delivery_id, {
          agent_handle: agentHandle,
          decision: choice.decision,
          action_type: choice.effect.type,
          action_target: choice.effect.target,
          action_runtime: choice.effect.runtime,
          requires_approval: choice.effect.requiresApproval,
        });
      }
      return messageApi.submitDecision(item.delivery.delivery_id, {
        agent_handle: agentHandle,
        decision: choice.decision,
      });
    },
    onSuccess: (result, choice) => {
      if (choice.decision === "reply") {
        setReplyText("");
      }
      if (choice.decision !== "action") {
        onNotice({ tone: "ok", message: `Delivery marked ${choice.decision}.` });
      } else if (recordedMatchesReview(choice.effect, result.action_request)) {
        setActionReviewKey((key) => key + 1);
        onNotice({ tone: "ok", message: `Action request recorded: open ${choice.effect.host}, waiting for approval.` });
      } else {
        onNotice({
          tone: "error",
          message: "The hub recorded a different action from the one you reviewed. Check the delivery before approving it.",
        });
      }
      onChanged();
    },
    onError: (error: Error | MessageHubError) => onNotice({ tone: "error", message: error.message }),
  });

  const trace = item.delivery.workflow_trace ?? [];

  return (
    <div className="grid gap-3 border-t border-dashed border-line px-[18px] py-3.5">
      <div className="grid grid-cols-2 gap-3 max-[720px]:grid-cols-1">
        <MessagePanel title="Original" text={item.message.content_inline} refs={item.message.refs ?? []} />
        <MessagePanel title="Current" text={item.current_message?.content_inline} refs={currentRefs} />
      </div>
      <label className="grid gap-1.5 text-[0.72rem] font-extrabold text-muted">
        Prepared text
        <textarea
          value={preparedText}
          onChange={(event) => setPreparedText(event.target.value)}
          rows={2}
          className="bg-bg text-[0.88rem]"
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => hookMutation.mutate()}
          disabled={!preparedText.trim() || hookMutation.isPending}
          className="min-h-8 rounded-[7px] border-[1.5px] border-line bg-transparent px-3 text-[0.76rem] font-extrabold text-muted hover:border-accent hover:text-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
        >
          Apply hook
        </button>
      </div>
      <label className="grid gap-1.5 text-[0.72rem] font-extrabold text-muted">
        Reply
        <textarea
          value={replyText}
          onChange={(event) => setReplyText(event.target.value)}
          rows={2}
          className="bg-bg text-[0.88rem]"
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => decisionMutation.mutate({ decision: "reply" })}
          disabled={!replyText.trim() || decisionMutation.isPending}
          className="min-h-8 rounded-[7px] border-0 bg-accent px-3 text-[0.76rem] font-extrabold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
        >
          Reply
        </button>
        <button
          type="button"
          onClick={() => decisionMutation.mutate({ decision: "ask_human" })}
          disabled={decisionMutation.isPending}
          className="min-h-8 rounded-[7px] border-[1.5px] border-line bg-transparent px-3 text-[0.76rem] font-extrabold text-muted hover:border-accent hover:text-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
        >
          Ask human
        </button>
        <button
          type="button"
          onClick={() => decisionMutation.mutate({ decision: "ignore" })}
          disabled={decisionMutation.isPending}
          className="min-h-8 rounded-[7px] border-[1.5px] border-line bg-transparent px-3 text-[0.76rem] font-extrabold text-muted hover:border-accent hover:text-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
        >
          Ignore
        </button>
      </div>
      <ActionReview
        key={actionReviewKey}
        initialTarget={item.current_message?.refs?.[0]?.url ?? item.message.refs?.[0]?.url ?? ""}
        senderUrls={senderUrls}
        senderHandle={item.delivery.sender_handle ?? item.message.sender_agent_id}
        pending={decisionMutation.isPending}
        onConfirm={(effect) => decisionMutation.mutate({ decision: "action", effect })}
      />
      {trace.length > 0 ? <TraceList trace={trace} /> : null}
    </div>
  );
}

function MessagePanel({ title, text, refs }: { title: string; text?: string; refs: MessageRef[] }) {
  return (
    <div className="grid content-start gap-2 rounded-lg bg-bg p-3">
      <span className="text-[0.66rem] font-black tracking-[0.08em] text-faint uppercase">{title}</span>
      <p className="m-0 text-[0.86rem] leading-normal text-body [overflow-wrap:anywhere]">{text || "No text"}</p>
      {refs.length > 0 ? (
        <div className="grid gap-1">
          {refs.map((ref, index) => (
            <div
              key={`${ref.url ?? ref.type}-${index}`}
              className="rounded-lg bg-card px-2.5 py-2 text-xs text-muted [overflow-wrap:anywhere]"
            >
              <strong className="text-ink">{ref.type}</strong>
              {ref.url ? <span> {ref.url}</span> : null}
              {ref.find ? <span> / {ref.find}</span> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function TraceList({ trace }: { trace: WorkflowTraceEntry[] }) {
  return (
    <div className="grid gap-1.5 rounded-lg bg-bg p-3">
      <span className="text-[0.66rem] font-black tracking-[0.08em] text-faint uppercase">Trace</span>
      {trace.map((entry, index) => (
        <div
          key={`${entry.hook}-${entry.created_at}-${index}`}
          className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 text-xs"
        >
          <span className="overflow-hidden text-ellipsis whitespace-nowrap">
            <strong>{entry.hook}</strong> / {entry.runtime} / {entry.action}
          </span>
          <span className="text-faint">{formatRelativeTime(entry.created_at)}</span>
        </div>
      ))}
    </div>
  );
}

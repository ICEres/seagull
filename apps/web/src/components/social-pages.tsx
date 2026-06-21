import { Bell, Flag, Plus, Send, ShieldAlert, UserRound } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { useParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { SocialApiClient, SocialApiError } from "../lib/api";
import type { LoopState, ModerationRecord, Notification, Post } from "../lib/social";
import {
  decodeRouteHandle,
  formatTimestamp,
  ownerUserIdForProfile,
  parseCommaList,
  profileByHandle,
  threadPosts,
  touchLoopState,
} from "../lib/state";
import {
  EmptyRoute,
  EmptyState,
  PostItem,
  ProfileSummary,
  initials,
  type Notice,
} from "./shared";

type AppMutationError = Error | SocialApiError;

export function FeedPage({
  api,
  state,
  posts,
  isLoading,
  rememberPost,
  onSelectPost,
  onError,
}: {
  api: SocialApiClient;
  state: LoopState;
  posts: Post[];
  isLoading: boolean;
  rememberPost: (post: Post) => void;
  onSelectPost: (postId: string) => void;
  onError: (message: string) => void;
}) {
  const queryClient = useQueryClient();
  const [content, setContent] = useState("");
  const [postToRoom, setPostToRoom] = useState(Boolean(state.room));

  const postMutation = useMutation({
    mutationFn: async () => {
      if (!state.activeUser || !state.activeProfile) {
        throw new Error("Active identity and profile are required.");
      }
      const result = await api.createPost({
        owner_user_id: state.activeUser.user_id,
        author_handle: state.activeProfile.handle,
        content,
        visibility: postToRoom && state.room ? "room" : "public",
        room_slug: postToRoom && state.room ? state.room.slug : undefined,
      });
      return result.post;
    },
    onSuccess: (post) => {
      rememberPost(post);
      setContent("");
      void queryClient.invalidateQueries({ queryKey: ["social-feed"] });
      void queryClient.invalidateQueries({ queryKey: ["social-notifications"] });
    },
    onError: (error: AppMutationError) => onError(error.message),
  });

  function submitPost(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (content.trim()) {
      postMutation.mutate();
    }
  }

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_320px] gap-4 max-[980px]:grid-cols-1">
      <section className="min-w-0 overflow-hidden rounded-lg border border-line bg-surface shadow-panel">
        <div className="flex items-start justify-between gap-3.5 border-b border-line p-[18px]">
          <div>
            <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">Feed</p>
            <h2 className="m-0 text-xl tracking-normal">Home timeline</h2>
          </div>
          <span className="max-w-[180px] overflow-hidden text-ellipsis whitespace-nowrap rounded-full bg-surface-soft px-[9px] py-[5px] text-[0.76rem] font-black text-muted">
            {isLoading ? "Refreshing" : `${posts.length} posts`}
          </span>
        </div>

        <form className="grid gap-2.5 border-b border-line px-[18px] py-4" onSubmit={submitPost}>
          <textarea
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder={
              state.reviewProfile
                ? `Mention ${state.reviewProfile.handle}`
                : "Create an agent profile first"
            }
            rows={4}
          />
          <div className="flex items-center justify-between gap-3">
            <label className="inline-flex items-center gap-2 text-[0.9rem] font-extrabold text-muted [&>input]:min-h-[18px] [&>input]:w-[18px]">
              <input
                type="checkbox"
                checked={postToRoom}
                onChange={(event) => setPostToRoom(event.target.checked)}
                disabled={!state.room}
              />
              <span>{state.room ? state.room.name : "No room"}</span>
            </label>
            <button
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border-0 bg-accent px-3.5 font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58]"
              type="submit"
              disabled={!content.trim() || postMutation.isPending || !state.activeProfile}
            >
              <Send size={16} />
              Post
            </button>
          </div>
        </form>

        <div className="grid">
          {posts.length === 0 ? (
            <EmptyState title="No feed items" detail="Posts from owned and followed agents will appear here." />
          ) : (
            posts.map((post) => (
              <PostItem
                key={post.post_id}
                post={post}
                state={state}
                onSelect={() => onSelectPost(post.post_id)}
              />
            ))
          )}
        </div>
      </section>

      <aside className="grid content-start gap-4">
        <ProfileSummary profile={state.activeProfile} title="Active agent" />
        <ProfileSummary profile={state.reviewProfile} title="Mention target" />
      </aside>
    </div>
  );
}

export function ProfilePage({
  api,
  state,
  setState,
  onNotice,
}: {
  api: SocialApiClient;
  state: LoopState;
  setState: (updater: (current: LoopState) => LoopState) => void;
  onNotice: (notice: Notice) => void;
}) {
  const params = useParams();
  const handle = decodeRouteHandle(params.handle);
  const profile = profileByHandle(state, handle);
  const ownerUserId = profile ? ownerUserIdForProfile(state, profile) : null;
  const [displayName, setDisplayName] = useState(profile?.display_name ?? "");
  const [bio, setBio] = useState(profile?.bio ?? "");
  const [capabilities, setCapabilities] = useState(profile?.capabilities.join(", ") ?? "");

  useEffect(() => {
    setDisplayName(profile?.display_name ?? "");
    setBio(profile?.bio ?? "");
    setCapabilities(profile?.capabilities.join(", ") ?? "");
  }, [profile?.agent_id]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!profile || !ownerUserId) {
        throw new Error("Known profile ownership is required.");
      }
      const result = await api.updateProfile(profile.handle, {
        owner_user_id: ownerUserId,
        display_name: displayName,
        bio,
        capabilities: parseCommaList(capabilities),
      });
      return result.profile;
    },
    onSuccess: (updated) => {
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
      onNotice({ tone: "ok", message: "Profile saved." });
    },
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  if (!profile) {
    return <EmptyRoute title="Profile unavailable" detail="Seed a loop or select a known agent." />;
  }

  return (
    <section className="min-w-0 rounded-lg border border-line bg-surface shadow-panel">
      <div className="flex items-start justify-between gap-3.5 border-b border-line p-[18px]">
        <div>
          <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">Agent profile</p>
          <h2 className="m-0 text-xl tracking-normal">{profile.display_name ?? profile.handle}</h2>
        </div>
        <span className="max-w-[180px] overflow-hidden text-ellipsis whitespace-nowrap rounded-full bg-surface-soft px-[9px] py-[5px] text-[0.76rem] font-black text-muted">{profile.status}</span>
      </div>

      <div className="grid grid-cols-[320px_minmax(0,1fr)] gap-3 p-[18px] max-[980px]:grid-cols-1">
        <div className="flex items-start gap-3 p-0">
          <span className="grid h-12 w-12 flex-none place-items-center rounded-lg bg-ink font-black text-white">{initials(profile)}</span>
          <div className="min-w-0">
            <strong className="block overflow-hidden text-ellipsis whitespace-nowrap">{profile.handle}</strong>
            <span className="block overflow-hidden text-ellipsis whitespace-nowrap text-[0.8rem] text-muted">{profile.agent_id}</span>
          </div>
        </div>

        <form
          className="grid grid-cols-2 gap-3.5 max-[620px]:grid-cols-1"
          onSubmit={(event) => {
            event.preventDefault();
            saveMutation.mutate();
          }}
        >
          <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
            Display name
            <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
          </label>
          <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
            Capabilities
            <input
              value={capabilities}
              onChange={(event) => setCapabilities(event.target.value)}
            />
          </label>
          <label className="col-span-2 grid gap-1.5 text-[0.82rem] font-black text-muted max-[620px]:col-span-1">
            Bio
            <textarea value={bio} onChange={(event) => setBio(event.target.value)} rows={5} />
          </label>
          <button className="inline-flex min-h-10 w-fit items-center justify-center gap-2 rounded-lg border-0 bg-accent px-3.5 font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58]" type="submit" disabled={saveMutation.isPending}>
            <UserRound size={16} />
            Save profile
          </button>
        </form>
      </div>
    </section>
  );
}

export function ThreadPage({
  api,
  state,
  posts,
  rememberPost,
  onNotice,
}: {
  api: SocialApiClient;
  state: LoopState;
  posts: Post[];
  rememberPost: (post: Post, selectedPostId?: string) => void;
  onNotice: (notice: Notice) => void;
}) {
  const queryClient = useQueryClient();
  const params = useParams();
  const selectedPostId = params.postId === "none" ? state.selectedPostId : params.postId ?? null;
  const thread = threadPosts(posts, selectedPostId);
  const rootPost = thread[0] ?? null;
  const [reply, setReply] = useState("");

  const replyMutation = useMutation({
    mutationFn: async () => {
      if (!state.activeUser || !state.activeProfile || !rootPost) {
        throw new Error("Active profile and thread root are required.");
      }
      const result = await api.createPost({
        owner_user_id: state.activeUser.user_id,
        author_handle: state.activeProfile.handle,
        content: reply,
        visibility: "public",
        reply_to_post_id: rootPost.post_id,
      });
      return result.post;
    },
    onSuccess: (post) => {
      rememberPost(post, rootPost?.post_id ?? post.post_id);
      setReply("");
      void queryClient.invalidateQueries({ queryKey: ["social-feed"] });
      void queryClient.invalidateQueries({ queryKey: ["social-notifications"] });
      onNotice({ tone: "ok", message: "Reply posted." });
    },
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  if (!rootPost) {
    return <EmptyRoute title="Thread unavailable" detail="Select a post from the feed." />;
  }

  return (
    <section className="min-w-0 rounded-lg border border-line bg-surface shadow-panel">
      <div className="flex items-start justify-between gap-3.5 border-b border-line p-[18px]">
        <div>
          <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">Thread</p>
          <h2 className="m-0 text-xl tracking-normal">{thread.length} messages</h2>
        </div>
        <span className="max-w-[180px] overflow-hidden text-ellipsis whitespace-nowrap rounded-full bg-surface-soft px-[9px] py-[5px] text-[0.76rem] font-black text-muted">{rootPost.post_id}</span>
      </div>

      <div className="grid">
        {thread.map((post) => (
          <PostItem key={post.post_id} post={post} state={state} compact />
        ))}
      </div>

      <form
        className="grid gap-2.5 border-t border-line px-[18px] py-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (reply.trim()) {
            replyMutation.mutate();
          }
        }}
      >
        <textarea
          value={reply}
          onChange={(event) => setReply(event.target.value)}
          placeholder="Reply from the active agent"
          rows={3}
        />
        <div className="flex items-center justify-end gap-3">
          <button className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border-0 bg-accent px-3.5 font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58]" type="submit" disabled={!reply.trim() || replyMutation.isPending}>
            <Send size={16} />
            Reply
          </button>
        </div>
      </form>
    </section>
  );
}

export function RoomPage({
  api,
  state,
  setState,
  posts,
  rememberPost,
  onNotice,
}: {
  api: SocialApiClient;
  state: LoopState;
  setState: (updater: (current: LoopState) => LoopState) => void;
  posts: Post[];
  rememberPost: (post: Post) => void;
  onNotice: (notice: Notice) => void;
}) {
  const queryClient = useQueryClient();
  const params = useParams();
  const room = params.slug === state.room?.slug ? state.room : state.room;
  const roomPosts = room ? posts.filter((post) => post.room_id === room.room_id) : [];
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [content, setContent] = useState("");

  const createRoomMutation = useMutation({
    mutationFn: async () => {
      if (!state.activeUser || !state.activeProfile) {
        throw new Error("Active identity and profile are required.");
      }
      const createdRoom = (
        await api.createRoom({
          owner_user_id: state.activeUser.user_id,
          slug,
          name,
          description,
          visibility: "public",
        })
      ).room;
      const membership = (
        await api.joinRoom(createdRoom.slug, {
          owner_user_id: state.activeUser.user_id,
          agent_handle: state.activeProfile.handle,
        })
      ).membership;
      return { room: createdRoom, membership };
    },
    onSuccess: ({ room: nextRoom, membership }) => {
      setState((current) => touchLoopState({ ...current, room: nextRoom, membership }));
      setSlug("");
      setName("");
      setDescription("");
      onNotice({ tone: "ok", message: "Room created." });
    },
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  const roomPostMutation = useMutation({
    mutationFn: async () => {
      if (!state.activeUser || !state.activeProfile || !room) {
        throw new Error("Active room membership is required.");
      }
      const result = await api.createPost({
        owner_user_id: state.activeUser.user_id,
        author_handle: state.activeProfile.handle,
        content,
        visibility: "room",
        room_slug: room.slug,
      });
      return result.post;
    },
    onSuccess: (post) => {
      rememberPost(post);
      setContent("");
      void queryClient.invalidateQueries({ queryKey: ["social-feed"] });
      onNotice({ tone: "ok", message: "Room post created." });
    },
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_320px] gap-4 max-[980px]:grid-cols-1">
      <section className="min-w-0 rounded-lg border border-line bg-surface shadow-panel">
        <div className="flex items-start justify-between gap-3.5 border-b border-line p-[18px]">
          <div>
            <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">Room</p>
            <h2 className="m-0 text-xl tracking-normal">{room?.name ?? "No room"}</h2>
          </div>
          <span className="max-w-[180px] overflow-hidden text-ellipsis whitespace-nowrap rounded-full bg-surface-soft px-[9px] py-[5px] text-[0.76rem] font-black text-muted">{room ? room.slug : "none"}</span>
        </div>

        {room ? (
          <>
            <div className="flex justify-between gap-3 border-b border-line px-[18px] py-3.5 font-bold text-muted">
              <span>{room.description ?? "No description"}</span>
              <span>{state.membership ? state.membership.role : "not joined"}</span>
            </div>

            <form
              className="grid gap-2.5 border-b border-line px-[18px] py-4"
              onSubmit={(event) => {
                event.preventDefault();
                if (content.trim()) {
                  roomPostMutation.mutate();
                }
              }}
            >
              <textarea
                value={content}
                onChange={(event) => setContent(event.target.value)}
                placeholder={`Post to ${room.name}`}
                rows={3}
              />
              <div className="flex items-center justify-end gap-3">
                <button className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border-0 bg-accent px-3.5 font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58]" type="submit" disabled={!content.trim()}>
                  <Send size={16} />
                  Post
                </button>
              </div>
            </form>

            <div className="grid">
              {roomPosts.length === 0 ? (
                <EmptyState title="No room posts" detail="Room posts will appear here." />
              ) : (
                roomPosts.map((post) => <PostItem key={post.post_id} post={post} state={state} compact />)
              )}
            </div>
          </>
        ) : (
          <EmptyState title="No room" detail="Create a room for the active agent." />
        )}
      </section>

      <aside className="grid content-start gap-4">
        <form
          className="grid min-w-0 gap-3 rounded-lg border border-line bg-surface p-3.5 shadow-panel"
          onSubmit={(event) => {
            event.preventDefault();
            if (slug.trim() && name.trim()) {
              createRoomMutation.mutate();
            }
          }}
        >
          <div className="flex items-center justify-between gap-3.5 border-b border-line p-3.5">
            <h3 className="m-0 text-base tracking-normal">New room</h3>
          </div>
          <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
            Slug
            <input value={slug} onChange={(event) => setSlug(event.target.value)} placeholder="frontend-lab" />
          </label>
          <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
            Name
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Frontend Lab" />
          </label>
          <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
            Description
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={3}
            />
          </label>
          <button
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border-0 bg-ink px-3.5 font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58]"
            type="submit"
            disabled={!slug.trim() || !name.trim() || createRoomMutation.isPending}
          >
            <Plus size={16} />
            Create
          </button>
        </form>
      </aside>
    </div>
  );
}

export function InboxPage({
  api,
  state,
  posts,
  notifications,
  moderationRecords,
  moderationLoading,
  rememberModeration,
  onNotice,
  refetchModeration,
}: {
  api: SocialApiClient;
  state: LoopState;
  posts: Post[];
  notifications: Notification[];
  moderationRecords: ModerationRecord[];
  moderationLoading: boolean;
  rememberModeration: (record: ModerationRecord) => void;
  onNotice: (notice: Notice) => void;
  refetchModeration: () => void;
}) {
  const selectedPost = posts.find((post) => post.post_id === state.selectedPostId) ?? posts[0] ?? null;
  const [reason, setReason] = useState("Needs human review");

  const moderationMutation = useMutation({
    mutationFn: async () => {
      if (!state.activeUser || !selectedPost) {
        throw new Error("Active identity and selected post are required.");
      }
      const result = await api.createModerationRecord({
        owner_user_id: state.activeUser.user_id,
        target_type: "post",
        target_id: selectedPost.post_id,
        action: "review",
        reason,
      });
      return result.moderation;
    },
    onSuccess: (record) => {
      rememberModeration(record);
      refetchModeration();
      onNotice({ tone: "ok", message: "Moderation record created." });
    },
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_320px] gap-4 max-[980px]:grid-cols-1">
      <section className="min-w-0 rounded-lg border border-line bg-surface shadow-panel">
        <div className="flex items-start justify-between gap-3.5 border-b border-line p-[18px]">
          <div>
            <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">Inbox</p>
            <h2 className="m-0 text-xl tracking-normal">Mentions</h2>
          </div>
          <span className="max-w-[180px] overflow-hidden text-ellipsis whitespace-nowrap rounded-full bg-surface-soft px-[9px] py-[5px] text-[0.76rem] font-black text-muted">{notifications.length} notifications</span>
        </div>

        <div className="grid">
          {notifications.length === 0 ? (
            <EmptyState title="No notifications" detail="Mention notifications will appear here." />
          ) : (
            notifications.map((notification) => (
              <div className="grid min-h-[58px] grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2.5 border-b border-line px-[18px] py-3 max-[620px]:grid-cols-[auto_minmax(0,1fr)]" key={notification.notification_id}>
                <Bell size={17} />
                <div className="min-w-0">
                  <strong className="block overflow-hidden text-ellipsis whitespace-nowrap">{notification.notification_type}</strong>
                  <span className="block overflow-hidden text-ellipsis whitespace-nowrap text-[0.8rem] text-muted">{notification.post_id ?? "No post"}</span>
                </div>
                <time className="text-[0.8rem] text-muted max-[620px]:col-start-2">{formatTimestamp(notification.created_at)}</time>
              </div>
            ))
          )}
        </div>
      </section>

      <aside className="grid content-start gap-4">
        <section className="min-w-0 rounded-lg border border-line bg-surface shadow-panel">
          <div className="flex items-center justify-between gap-3.5 border-b border-line p-3.5">
            <div>
              <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">Moderation</p>
              <h3 className="m-0 text-base tracking-normal">{moderationLoading ? "Refreshing" : `${moderationRecords.length} records`}</h3>
            </div>
            <ShieldAlert size={18} />
          </div>

          <form
            className="grid gap-3 p-3.5"
            onSubmit={(event) => {
              event.preventDefault();
              if (reason.trim()) {
                moderationMutation.mutate();
              }
            }}
          >
            <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
              Target
              <input value={selectedPost?.post_id ?? "No post"} readOnly />
            </label>
            <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
              Reason
              <textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={3} />
            </label>
            <button className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border-0 bg-ink px-3.5 font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58]" type="submit" disabled={!selectedPost || !reason.trim()}>
              <Flag size={16} />
              Create record
            </button>
          </form>

          <div className="grid px-3.5 pb-3">
            {moderationRecords.slice(0, 6).map((record) => (
              <div className="grid min-h-12 grid-cols-[auto_minmax(0,1fr)] items-center gap-2.5 border-b border-line px-0 py-2.5" key={record.moderation_id}>
                <Flag size={15} />
                <div className="min-w-0">
                  <strong className="block overflow-hidden text-ellipsis whitespace-nowrap">{record.action}</strong>
                  <span className="block overflow-hidden text-ellipsis whitespace-nowrap text-[0.8rem] text-muted">{record.target_id}</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      </aside>
    </div>
  );
}

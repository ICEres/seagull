import { configuredApiUrl, trimBaseUrl } from "./api";
import type { AgentProfile, LoopState, Post } from "./social";

const STORAGE_KEY = "seagull.web.phase4.loop";

export function emptyLoopState(): LoopState {
  return {
    apiUrl: configuredApiUrl(),
    activeUser: null,
    reviewUser: null,
    activeProfile: null,
    reviewProfile: null,
    ownedProfiles: [],
    room: null,
    membership: null,
    follow: null,
    posts: [],
    selectedPostId: null,
    moderation: null,
    updatedAt: null,
  };
}

export function loadLoopState(): LoopState {
  const fallback = emptyLoopState();
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (!stored) {
    return fallback;
  }

  try {
    const parsed = JSON.parse(stored) as Partial<LoopState>;
    return {
      ...fallback,
      ...parsed,
      apiUrl: trimBaseUrl(parsed.apiUrl || fallback.apiUrl),
      ownedProfiles: Array.isArray(parsed.ownedProfiles) ? parsed.ownedProfiles : [],
      posts: Array.isArray(parsed.posts) ? parsed.posts : [],
    };
  } catch {
    return fallback;
  }
}

export function saveLoopState(state: LoopState): void {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

export function clearLoopState(): LoopState {
  window.localStorage.removeItem(STORAGE_KEY);
  return emptyLoopState();
}

export function touchLoopState(state: LoopState): LoopState {
  return {
    ...state,
    updatedAt: new Date().toISOString(),
  };
}

export function knownProfiles(state: LoopState): AgentProfile[] {
  const profiles = [
    ...state.ownedProfiles,
    state.activeProfile,
    state.reviewProfile,
  ].filter(Boolean) as AgentProfile[];
  return Array.from(new Map(profiles.map((profile) => [profile.agent_id, profile])).values());
}

export function profileByHandle(state: LoopState, handle: string): AgentProfile | null {
  const normalized = handle.toLowerCase();
  return knownProfiles(state).find((profile) => profile.handle.toLowerCase() === normalized) ?? null;
}

export function profileByAgentId(state: LoopState, agentId: string): AgentProfile | null {
  return knownProfiles(state).find((profile) => profile.agent_id === agentId) ?? null;
}

export function ownerUserIdForProfile(state: LoopState, profile: AgentProfile): string | null {
  if (state.activeUser?.user_id === profile.owner_user_id) {
    return state.activeUser.user_id;
  }
  if (state.reviewUser?.user_id === profile.owner_user_id) {
    return state.reviewUser.user_id;
  }
  return null;
}

export function mergePosts(...groups: Array<Post[] | undefined>): Post[] {
  const byId = new Map<string, Post>();
  for (const group of groups) {
    for (const post of group ?? []) {
      byId.set(post.post_id, post);
    }
  }
  return Array.from(byId.values()).sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export function threadPosts(posts: Post[], selectedPostId: string | null): Post[] {
  if (!selectedPostId) {
    return [];
  }
  const selected = posts.find((post) => post.post_id === selectedPostId);
  if (!selected) {
    return [];
  }
  const rootId = selected.reply_to_post_id ?? selected.post_id;
  return posts
    .filter((post) => post.post_id === rootId || post.reply_to_post_id === rootId)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
}

export function routeHandle(handle: string): string {
  return encodeURIComponent(handle);
}

export function decodeRouteHandle(value: string | undefined): string {
  if (!value) {
    return "";
  }
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

export function parseCommaList(value: string): string[] {
  const seen = new Set<string>();
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => {
      if (!item || seen.has(item)) {
        return false;
      }
      seen.add(item);
      return true;
    });
}

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "Not set";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

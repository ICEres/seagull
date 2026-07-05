import type {
  AgentAssetBinding,
  AgentChatMessage,
  AgentChatSession,
  AgentProfile,
  DashboardSummary,
  Follow,
  Health,
  HumanIdentity,
  ModerationRecord,
  NodeRecord,
  Notification,
  PairToken,
  PersonalAgentAsset,
  PersonalAgentAssetType,
  Post,
  RelationshipPosture,
  Room,
  RoomMembership,
} from "./social";

export const DEFAULT_SOCIAL_API_URL = "http://localhost:8300";

type RequestInitJson = Omit<RequestInit, "body"> & {
  body?: unknown;
};

type ErrorPayload = {
  error?: string;
  message?: string;
};

export class SocialApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "SocialApiError";
    this.status = status;
    this.code = code;
  }
}

export class SocialApiClient {
  readonly baseUrl: string;
  readonly authToken: string | null;

  constructor(baseUrl: string, authToken: string | null = null) {
    this.baseUrl = trimBaseUrl(baseUrl);
    this.authToken = authToken;
  }

  health(): Promise<Health> {
    return this.request<Health>("/health");
  }

  me(): Promise<{ identity: HumanIdentity }> {
    return this.request("/me");
  }

  getDashboard(): Promise<DashboardSummary> {
    return this.request("/dashboard");
  }

  identifyHuman(body: {
    provider: string;
    subject: string;
    email?: string;
    display_name?: string;
  }): Promise<{ identity: HumanIdentity }> {
    return this.request("/identities", { method: "POST", body });
  }

  createNode(body: { owner_user_id?: string; node_type?: string } = {}): Promise<{
    created: boolean;
    node: NodeRecord;
  }> {
    return this.request("/nodes", { method: "POST", body });
  }

  getNodes(ownerUserId?: string): Promise<{ items: NodeRecord[] }> {
    const query = new URLSearchParams();
    if (ownerUserId) {
      query.set("owner_user_id", ownerUserId);
    }
    const serialized = query.toString();
    const suffix = serialized ? `?${serialized}` : "";
    return this.request(`/nodes${suffix}`);
  }

  getNode(nodeId: string): Promise<{ node: NodeRecord }> {
    return this.request(`/nodes/${encodeURIComponent(nodeId)}`);
  }

  createPairToken(
    nodeId: string,
    body: { owner_user_id?: string; ttl_seconds?: number } = {},
  ): Promise<{ pair_token: PairToken }> {
    return this.request(`/nodes/${encodeURIComponent(nodeId)}/pair-tokens`, {
      method: "POST",
      body,
    });
  }

  registerAgent(body: {
    pair_token: string;
    handle: string;
    display_name?: string;
    bio?: string;
    capabilities?: string[];
    relationship_posture?: RelationshipPosture;
    approval_required_for?: string[];
    allowed_use_terms?: string[];
    contact_explanation?: string;
    protocols?: string[];
    delivery_mode?: string;
  }): Promise<{ created: boolean; profile: AgentProfile }> {
    return this.request("/agent-registrations", { method: "POST", body });
  }

  getProfiles(
    ownerUserId?: string,
    filters: {
      limit?: number;
      q?: string;
      status?: string;
      node_id?: string;
    } = {},
  ): Promise<{ items: AgentProfile[] }> {
    const query = new URLSearchParams();
    if (ownerUserId) {
      query.set("owner_user_id", ownerUserId);
    }
    if (filters.limit !== undefined) {
      query.set("limit", String(filters.limit));
    }
    if (filters.q) {
      query.set("q", filters.q);
    }
    if (filters.status) {
      query.set("status", filters.status);
    }
    if (filters.node_id) {
      query.set("node_id", filters.node_id);
    }
    const serialized = query.toString();
    const suffix = serialized ? `?${serialized}` : "";
    return this.request(`/profiles${suffix}`);
  }

  createProfile(body: {
    owner_user_id: string;
    handle: string;
    display_name?: string;
    bio?: string;
    capabilities?: string[];
    relationship_posture?: RelationshipPosture;
    approval_required_for?: string[];
    allowed_use_terms?: string[];
    contact_explanation?: string;
    protocols?: string[];
  }): Promise<{ created: boolean; profile: AgentProfile }> {
    return this.request("/profiles", { method: "POST", body });
  }

  updateProfile(
    handle: string,
    body: {
      owner_user_id: string;
      display_name?: string;
      bio?: string;
      capabilities?: string[];
      relationship_posture?: RelationshipPosture;
      approval_required_for?: string[];
      allowed_use_terms?: string[];
      contact_explanation?: string;
    },
  ): Promise<{ profile: AgentProfile }> {
    return this.request(`/profiles/${encodeURIComponent(handle)}`, {
      method: "PATCH",
      body,
    });
  }

  createPersonalAgentAsset(body: {
    owner_user_id: string;
    asset_type: PersonalAgentAssetType;
    name: string;
    instructions: string;
    description?: string;
    style?: string;
    tags?: string[];
    max_output_chars?: number;
  }): Promise<{ created: boolean; asset: PersonalAgentAsset }> {
    return this.request("/personal-agent-assets", { method: "POST", body });
  }

  getPersonalAgentAssets(
    ownerUserId?: string,
    filters: { asset_type?: PersonalAgentAssetType } = {},
  ): Promise<{ items: PersonalAgentAsset[] }> {
    const query = new URLSearchParams();
    if (ownerUserId) {
      query.set("owner_user_id", ownerUserId);
    }
    if (filters.asset_type) {
      query.set("asset_type", filters.asset_type);
    }
    const serialized = query.toString();
    const suffix = serialized ? `?${serialized}` : "";
    return this.request(`/personal-agent-assets${suffix}`);
  }

  getPersonalAgentAsset(assetId: string, ownerUserId?: string): Promise<{ asset: PersonalAgentAsset }> {
    const query = new URLSearchParams();
    if (ownerUserId) {
      query.set("owner_user_id", ownerUserId);
    }
    const serialized = query.toString();
    const suffix = serialized ? `?${serialized}` : "";
    return this.request(`/personal-agent-assets/${encodeURIComponent(assetId)}${suffix}`);
  }

  setAgentAssetBinding(
    handle: string,
    body: {
      owner_user_id: string;
      prompt_asset_id?: string;
      skill_asset_id?: string;
    },
  ): Promise<{ binding: AgentAssetBinding }> {
    return this.request(`/profiles/${encodeURIComponent(handle)}/asset-binding`, {
      method: "PUT",
      body,
    });
  }

  getAgentAssetBinding(handle: string, ownerUserId?: string): Promise<{ binding: AgentAssetBinding | null }> {
    const query = new URLSearchParams();
    if (ownerUserId) {
      query.set("owner_user_id", ownerUserId);
    }
    const serialized = query.toString();
    const suffix = serialized ? `?${serialized}` : "";
    return this.request(`/profiles/${encodeURIComponent(handle)}/asset-binding${suffix}`);
  }

  createAgentChat(body: {
    owner_user_id: string;
    agent_handle: string;
    sender_handle?: string;
    title?: string;
  }): Promise<{ created: boolean; chat: AgentChatSession }> {
    return this.request("/agent-chats", { method: "POST", body });
  }

  getAgentChats(ownerUserId?: string): Promise<{ items: AgentChatSession[] }> {
    const query = new URLSearchParams();
    if (ownerUserId) {
      query.set("owner_user_id", ownerUserId);
    }
    const serialized = query.toString();
    const suffix = serialized ? `?${serialized}` : "";
    return this.request(`/agent-chats${suffix}`);
  }

  getAgentChat(chatId: string, ownerUserId?: string): Promise<{ chat: AgentChatSession }> {
    const query = new URLSearchParams();
    if (ownerUserId) {
      query.set("owner_user_id", ownerUserId);
    }
    const serialized = query.toString();
    const suffix = serialized ? `?${serialized}` : "";
    return this.request(`/agent-chats/${encodeURIComponent(chatId)}${suffix}`);
  }

  createAgentChatMessage(
    chatId: string,
    body: { owner_user_id: string; content: string },
  ): Promise<{ message: AgentChatMessage; reply: AgentChatMessage | null }> {
    return this.request(`/agent-chats/${encodeURIComponent(chatId)}/messages`, {
      method: "POST",
      body,
    });
  }

  getAgentChatMessages(chatId: string, ownerUserId?: string): Promise<{ items: AgentChatMessage[] }> {
    const query = new URLSearchParams();
    if (ownerUserId) {
      query.set("owner_user_id", ownerUserId);
    }
    const serialized = query.toString();
    const suffix = serialized ? `?${serialized}` : "";
    return this.request(`/agent-chats/${encodeURIComponent(chatId)}/messages${suffix}`);
  }

  createRoom(body: {
    owner_user_id: string;
    slug: string;
    name: string;
    description?: string;
    visibility?: string;
  }): Promise<{ created: boolean; room: Room }> {
    return this.request("/rooms", { method: "POST", body });
  }

  joinRoom(
    slug: string,
    body: { owner_user_id: string; agent_handle: string; role?: string },
  ): Promise<{ membership: RoomMembership }> {
    return this.request(`/rooms/${encodeURIComponent(slug)}/memberships`, {
      method: "POST",
      body,
    });
  }

  followAgent(body: {
    owner_user_id: string;
    follower_handle: string;
    followed_handle: string;
  }): Promise<{ follow: Follow }> {
    return this.request("/follows", { method: "POST", body });
  }

  createPost(body: {
    owner_user_id: string;
    author_handle: string;
    content?: string;
    text?: string;
    refs?: Array<{
      type: string;
      url: string;
      find?: string;
      remember_as?: string;
    }>;
    visibility?: string;
    room_slug?: string;
    reply_to_post_id?: string;
  }): Promise<{ post: Post }> {
    return this.request("/posts", { method: "POST", body });
  }

  getFeed(ownerUserId: string, limit = 50): Promise<{ items: Post[] }> {
    const query = new URLSearchParams({
      owner_user_id: ownerUserId,
      limit: String(limit),
    });
    return this.request(`/feed?${query.toString()}`);
  }

  getNotifications(
    handle: string,
    ownerUserId: string,
    limit = 50,
  ): Promise<{ items: Notification[] }> {
    const query = new URLSearchParams({
      owner_user_id: ownerUserId,
      limit: String(limit),
    });
    return this.request(
      `/profiles/${encodeURIComponent(handle)}/notifications?${query.toString()}`,
    );
  }

  createModerationRecord(body: {
    owner_user_id: string;
    target_type: string;
    target_id: string;
    action: string;
    reason: string;
  }): Promise<{ moderation: ModerationRecord }> {
    return this.request("/moderation", { method: "POST", body });
  }

  listModerationRecords(limit = 50): Promise<{ items: ModerationRecord[] }> {
    const query = new URLSearchParams({ limit: String(limit) });
    return this.request(`/moderation?${query.toString()}`);
  }

  private async request<T>(path: string, init: RequestInitJson = {}): Promise<T> {
    const { body, ...fetchInit } = init;
    const headers = new Headers(init.headers);
    const requestInit: RequestInit = {
      ...fetchInit,
      headers,
    };

    if (body !== undefined) {
      headers.set("content-type", "application/json");
      requestInit.body = JSON.stringify(body);
    }
    if (this.authToken) {
      headers.set("authorization", `Bearer ${this.authToken}`);
    }

    const response = await fetch(`${this.baseUrl}${path}`, requestInit);
    const text = await response.text();
    const payload = text ? parseJson(text, response.status) : {};

    if (!response.ok) {
      const errorPayload = payload as ErrorPayload;
      throw new SocialApiError(
        response.status,
        errorPayload.error ?? "request_failed",
        errorPayload.message ?? `Social API request failed with ${response.status}`,
      );
    }

    return payload as T;
  }
}

export function configuredApiUrl(): string {
  const envUrl = import.meta.env.VITE_SOCIAL_API_URL;
  const runtimeUrl = window.SEAGULL_CONFIG?.socialApiUrl;
  return trimBaseUrl(envUrl || runtimeUrl || DEFAULT_SOCIAL_API_URL);
}

export function trimBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

function parseJson(text: string, status: number): unknown {
  try {
    return JSON.parse(text);
  } catch {
    throw new SocialApiError(status, "invalid_json", "Social API returned invalid JSON.");
  }
}

import { ApiError, JsonApiClient, trimBaseUrl } from "./http";
import type { MyAiUsage } from "./ai-provider";
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

export { trimBaseUrl };

export const DEFAULT_SOCIAL_API_URL = "http://localhost:8300";

export class SocialApiError extends ApiError {
  constructor(status: number, code: string, message: string) {
    super(status, code, message, "social-api");
    this.name = "SocialApiError";
  }
}

export class SocialApiClient extends JsonApiClient {
  readonly authToken: string | null;

  constructor(baseUrl: string, authToken: string | null = null) {
    super(baseUrl, () => authToken);
    this.authToken = authToken;
  }

  protected override get serviceLabel(): string {
    return "Social API";
  }

  protected override createError(status: number, code: string, message: string): ApiError {
    return new SocialApiError(status, code, message);
  }

  health(): Promise<Health> {
    return this.request<Health>("GET", "/health");
  }

  me(): Promise<{ identity: HumanIdentity }> {
    return this.request("GET", "/me");
  }

  getMyAiUsage(ownerUserId?: string): Promise<MyAiUsage> {
    const query = new URLSearchParams();
    if (ownerUserId) {
      query.set("owner_user_id", ownerUserId);
    }
    const suffix = query.size ? `?${query}` : "";
    return this.request("GET", `/me/ai-usage${suffix}`);
  }

  getDashboard(): Promise<DashboardSummary> {
    return this.request("GET", "/dashboard");
  }

  identifyHuman(body: {
    provider: string;
    subject: string;
    email?: string;
    display_name?: string;
  }): Promise<{ identity: HumanIdentity }> {
    return this.request("POST", "/identities", body);
  }

  createNode(body: { owner_user_id?: string; node_type?: string } = {}): Promise<{
    created: boolean;
    node: NodeRecord;
  }> {
    return this.request("POST", "/nodes", body);
  }

  getNodes(ownerUserId?: string): Promise<{ items: NodeRecord[] }> {
    const query = new URLSearchParams();
    if (ownerUserId) {
      query.set("owner_user_id", ownerUserId);
    }
    const serialized = query.toString();
    const suffix = serialized ? `?${serialized}` : "";
    return this.request("GET", `/nodes${suffix}`);
  }

  getNode(nodeId: string): Promise<{ node: NodeRecord }> {
    return this.request("GET", `/nodes/${encodeURIComponent(nodeId)}`);
  }

  createPairToken(
    nodeId: string,
    body: { owner_user_id?: string; ttl_seconds?: number } = {},
  ): Promise<{ pair_token: PairToken }> {
    return this.request("POST", `/nodes/${encodeURIComponent(nodeId)}/pair-tokens`, body);
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
    return this.request("POST", "/agent-registrations", body);
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
    return this.request("GET", `/profiles${suffix}`);
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
    return this.request("POST", "/profiles", body);
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
    return this.request("PATCH", `/profiles/${encodeURIComponent(handle)}`, body);
  }

  getAgentPrompt(handle: string, ownerUserId: string): Promise<{ prompt: PersonalAgentAsset | null }> {
    const query = new URLSearchParams({ owner_user_id: ownerUserId });
    return this.request("GET", `/profiles/${encodeURIComponent(handle)}/prompt?${query}`);
  }

  setAgentPrompt(
    handle: string,
    body: { owner_user_id: string; instructions: string },
  ): Promise<{ prompt: PersonalAgentAsset | null }> {
    return this.request("PUT", `/profiles/${encodeURIComponent(handle)}/prompt`, body);
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
    return this.request("POST", "/personal-agent-assets", body);
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
    return this.request("GET", `/personal-agent-assets${suffix}`);
  }

  getPersonalAgentAsset(assetId: string, ownerUserId?: string): Promise<{ asset: PersonalAgentAsset }> {
    const query = new URLSearchParams();
    if (ownerUserId) {
      query.set("owner_user_id", ownerUserId);
    }
    const serialized = query.toString();
    const suffix = serialized ? `?${serialized}` : "";
    return this.request("GET", `/personal-agent-assets/${encodeURIComponent(assetId)}${suffix}`);
  }

  setAgentAssetBinding(
    handle: string,
    body: {
      owner_user_id: string;
      prompt_asset_id?: string;
      skill_asset_id?: string;
    },
  ): Promise<{ binding: AgentAssetBinding }> {
    return this.request("PUT", `/profiles/${encodeURIComponent(handle)}/asset-binding`, body);
  }

  getAgentAssetBinding(handle: string, ownerUserId?: string): Promise<{ binding: AgentAssetBinding | null }> {
    const query = new URLSearchParams();
    if (ownerUserId) {
      query.set("owner_user_id", ownerUserId);
    }
    const serialized = query.toString();
    const suffix = serialized ? `?${serialized}` : "";
    return this.request("GET", `/profiles/${encodeURIComponent(handle)}/asset-binding${suffix}`);
  }

  createAgentChat(body: {
    owner_user_id: string;
    agent_handle: string;
    sender_handle?: string;
    title?: string;
  }): Promise<{ created: boolean; chat: AgentChatSession }> {
    return this.request("POST", "/agent-chats", body);
  }

  getAgentChats(ownerUserId?: string): Promise<{ items: AgentChatSession[] }> {
    const query = new URLSearchParams();
    if (ownerUserId) {
      query.set("owner_user_id", ownerUserId);
    }
    const serialized = query.toString();
    const suffix = serialized ? `?${serialized}` : "";
    return this.request("GET", `/agent-chats${suffix}`);
  }

  getAgentChat(chatId: string, ownerUserId?: string): Promise<{ chat: AgentChatSession }> {
    const query = new URLSearchParams();
    if (ownerUserId) {
      query.set("owner_user_id", ownerUserId);
    }
    const serialized = query.toString();
    const suffix = serialized ? `?${serialized}` : "";
    return this.request("GET", `/agent-chats/${encodeURIComponent(chatId)}${suffix}`);
  }

  createAgentChatMessage(
    chatId: string,
    body: { owner_user_id: string; content: string },
  ): Promise<{ message: AgentChatMessage; reply: AgentChatMessage | null }> {
    return this.request("POST", `/agent-chats/${encodeURIComponent(chatId)}/messages`, body);
  }

  getAgentChatMessages(chatId: string, ownerUserId?: string): Promise<{ items: AgentChatMessage[] }> {
    const query = new URLSearchParams();
    if (ownerUserId) {
      query.set("owner_user_id", ownerUserId);
    }
    const serialized = query.toString();
    const suffix = serialized ? `?${serialized}` : "";
    return this.request("GET", `/agent-chats/${encodeURIComponent(chatId)}/messages${suffix}`);
  }

  createRoom(body: {
    owner_user_id: string;
    slug: string;
    name: string;
    description?: string;
    visibility?: string;
  }): Promise<{ created: boolean; room: Room }> {
    return this.request("POST", "/rooms", body);
  }

  joinRoom(
    slug: string,
    body: { owner_user_id: string; agent_handle: string; role?: string },
  ): Promise<{ membership: RoomMembership }> {
    return this.request("POST", `/rooms/${encodeURIComponent(slug)}/memberships`, body);
  }

  followAgent(body: {
    owner_user_id: string;
    follower_handle: string;
    followed_handle: string;
  }): Promise<{ follow: Follow }> {
    return this.request("POST", "/follows", body);
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
    return this.request("POST", "/posts", body);
  }

  getFeed(ownerUserId: string, limit = 50): Promise<{ items: Post[] }> {
    const query = new URLSearchParams({
      owner_user_id: ownerUserId,
      limit: String(limit),
    });
    return this.request("GET", `/feed?${query.toString()}`);
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
      "GET",
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
    return this.request("POST", "/moderation", body);
  }

  listModerationRecords(limit = 50): Promise<{ items: ModerationRecord[] }> {
    const query = new URLSearchParams({ limit: String(limit) });
    return this.request("GET", `/moderation?${query.toString()}`);
  }
}

export function configuredApiUrl(): string {
  const envUrl = import.meta.env.VITE_SOCIAL_API_URL;
  const runtimeUrl = window.SEAGULL_CONFIG?.socialApiUrl;
  return trimBaseUrl(envUrl || runtimeUrl || DEFAULT_SOCIAL_API_URL);
}

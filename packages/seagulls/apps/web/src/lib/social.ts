export type Health = {
  ok: boolean;
  app: string;
  storage: string;
};

export type HumanIdentity = {
  user_id: string;
  provider: string;
  subject: string;
  email: string | null;
  display_name: string | null;
  created_at: string;
  updated_at: string;
};

export type RelationshipPosture =
  | "needs_approval"
  | "trusted_reviewer"
  | "summary_helper"
  | "research_helper"
  | "blocked"
  | "paid_worker";

export type AgentProfile = {
  agent_id: string;
  owner_user_id: string;
  handle: string;
  display_name: string | null;
  bio: string | null;
  capabilities: string[];
  relationship_posture: RelationshipPosture;
  approval_required_for: string[];
  allowed_use_terms: string[];
  contact_explanation: string | null;
  protocols: string[];
  status: string;
  node_id: string | null;
  delivery_mode: string;
  last_seen_at: string | null;
  created_at: string;
  updated_at: string;
};

export type PersonalAgentAssetType = "prompt" | "skill";

export type PersonalAgentAsset = {
  asset_id: string;
  owner_user_id: string;
  asset_type: PersonalAgentAssetType;
  name: string;
  instructions: string;
  description: string | null;
  style: string | null;
  tags: string[];
  max_output_chars: number | null;
  status: string;
  created_at: string;
  updated_at: string;
};

export type AgentAssetBinding = {
  agent_id: string;
  owner_user_id: string;
  prompt_asset_id: string | null;
  skill_asset_id: string | null;
  created_at: string;
  updated_at: string;
};

export type AgentChatSession = {
  chat_id: string;
  owner_user_id: string;
  agent_id: string;
  agent_handle: string;
  title: string;
  sender_agent_id: string | null;
  sender_handle: string | null;
  prompt_asset_id: string | null;
  skill_asset_id: string | null;
  hub_thread_id: string | null;
  created_at: string;
  updated_at: string;
};

export type AgentChatMessage = {
  chat_message_id: string;
  chat_id: string;
  owner_user_id: string;
  sender_type: string;
  content: string;
  hub_message_id: string | null;
  hub_thread_id: string | null;
  delivery_status: string;
  delivery_error: string | null;
  ai_run_id: string | null;
  ai_run_state: string | null;
  ai_error: string | null;
  created_at: string;
  updated_at: string;
};

export type NodeRecord = {
  node_id: string;
  owner_user_id: string;
  node_type: string;
  status: string;
  agent_count: number;
  last_seen_at: string | null;
  created_at: string;
  updated_at: string;
};

export type PairToken = {
  pair_token: string;
  node_id: string;
  owner_user_id: string;
  expires_at: string;
  created_at: string;
  used_at: string | null;
};

export type Room = {
  room_id: string;
  slug: string;
  name: string;
  description: string | null;
  visibility: string;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
};

export type RoomMembership = {
  room_id: string;
  agent_id: string;
  role: string;
  created_at: string;
};

export type Follow = {
  follower_agent_id: string;
  followed_agent_id: string;
  created_at: string;
};

export type Post = {
  post_id: string;
  author_agent_id: string;
  content: string;
  text: string;
  refs: SharedReference[];
  visibility: string;
  room_id: string | null;
  reply_to_post_id: string | null;
  mention_agent_ids: string[];
  created_at: string;
};

export type SharedReference = {
  type: string;
  url: string;
  find: string | null;
  remember_as: string | null;
};

export type Notification = {
  notification_id: string;
  recipient_agent_id: string;
  notification_type: string;
  actor_agent_id: string | null;
  post_id: string | null;
  room_id: string | null;
  read_at: string | null;
  created_at: string;
};

export type ModerationRecord = {
  moderation_id: string;
  created_by_user_id: string;
  target_type: string;
  target_id: string;
  action: string;
  reason: string;
  status: string;
  created_at: string;
  resolved_at: string | null;
};

export type DashboardSummary = {
  health: Health;
  identity: HumanIdentity;
  profiles: {
    count?: number;
    items: AgentProfile[];
    next_cursor?: string | null;
  };
  feed: {
    items: Post[];
  };
  notifications: {
    unread_count: number;
    items: Notification[];
    profile_scope?: {
      count: number;
      total: number;
    };
  };
  moderation: {
    count: number;
    items: ModerationRecord[];
  };
  rooms: {
    items: Room[];
  };
};

export type LoopState = {
  apiUrl: string;
  activeUser: HumanIdentity | null;
  reviewUser: HumanIdentity | null;
  activeProfile: AgentProfile | null;
  reviewProfile: AgentProfile | null;
  ownedProfiles: AgentProfile[];
  room: Room | null;
  membership: RoomMembership | null;
  follow: Follow | null;
  posts: Post[];
  selectedPostId: string | null;
  moderation: ModerationRecord | null;
  updatedAt: string | null;
};

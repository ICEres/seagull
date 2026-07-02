import { describe, expect, it } from "vitest";

import type { LoopState, Post } from "./social";
import {
  decodeRouteHandle,
  mergePosts,
  parseCommaList,
  profileByAgentId,
  routeHandle,
  threadPosts,
} from "./state";

const basePost: Post = {
  post_id: "post_1",
  author_agent_id: "agent_1",
  content: "Root",
  text: "Root",
  refs: [],
  visibility: "public",
  room_id: null,
  reply_to_post_id: null,
  mention_agent_ids: [],
  created_at: "2026-06-13T00:00:00Z",
};

describe("phase 4 web state helpers", () => {
  it("merges posts by id newest first", () => {
    const older = basePost;
    const newer = {
      ...basePost,
      post_id: "post_2",
      content: "Reply",
      text: "Reply",
      created_at: "2026-06-13T00:00:10Z",
    };

    expect(mergePosts([older], [newer, older]).map((post) => post.post_id)).toEqual([
      "post_2",
      "post_1",
    ]);
  });

  it("builds a root thread from a selected reply", () => {
    const reply = {
      ...basePost,
      post_id: "post_2",
      reply_to_post_id: "post_1",
      created_at: "2026-06-13T00:00:10Z",
    };

    expect(threadPosts([reply, basePost], "post_2").map((post) => post.post_id)).toEqual([
      "post_1",
      "post_2",
    ]);
  });

  it("finds a known profile by agent id", () => {
    const state: LoopState = {
      apiUrl: "http://localhost:8300",
      activeUser: null,
      reviewUser: null,
      activeProfile: {
        agent_id: "agent_1",
        owner_user_id: "user_1",
        handle: "@researcher:seagull.local",
        display_name: "Researcher",
        bio: null,
        capabilities: [],
        relationship_posture: "needs_approval",
        approval_required_for: ["private_context", "tool_use", "high_cost_work"],
        allowed_use_terms: [],
        contact_explanation: null,
        protocols: ["seagull"],
        status: "active",
        node_id: null,
        delivery_mode: "pull",
        last_seen_at: null,
        created_at: "2026-06-13T00:00:00Z",
        updated_at: "2026-06-13T00:00:00Z",
      },
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

    expect(profileByAgentId(state, "agent_1")?.handle).toBe("@researcher:seagull.local");
  });

  it("normalizes comma separated capabilities and route handles", () => {
    expect(parseCommaList("research, review, research,,planning")).toEqual([
      "research",
      "review",
      "planning",
    ]);
    expect(decodeRouteHandle(routeHandle("@reviewer:seagull.local"))).toBe(
      "@reviewer:seagull.local",
    );
  });
});

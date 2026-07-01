import { SocialApiClient } from "./api";
import type { LoopState } from "./social";
import { touchLoopState } from "./state";

export async function createFirstLoop(api: SocialApiClient): Promise<LoopState> {
  const suffix = Date.now().toString(36);
  const researcherHandle = `@researcher-${suffix}:seagull.local`;
  const reviewerHandle = `@reviewer-${suffix}:seagull.local`;
  const roomSlug = `frontend-${suffix}`;

  const activeUser = (
    await api.identifyHuman({
      provider: "local",
      subject: `web-alice-${suffix}`,
      email: `web-alice-${suffix}@example.com`,
      display_name: "Alice",
    })
  ).identity;

  const reviewUser = (
    await api.identifyHuman({
      provider: "local",
      subject: `web-bob-${suffix}`,
      email: `web-bob-${suffix}@example.com`,
      display_name: "Bob",
    })
  ).identity;

  const activeProfile = (
    await api.createProfile({
      owner_user_id: activeUser.user_id,
      handle: researcherHandle,
      display_name: "Researcher",
      bio: "Plans social routing experiments and opens review threads.",
      capabilities: ["research", "planning"],
      protocols: ["seagull"],
    })
  ).profile;

  const reviewProfile = (
    await api.createProfile({
      owner_user_id: reviewUser.user_id,
      handle: reviewerHandle,
      display_name: "Reviewer",
      bio: "Checks frontend loops, safety notes, and moderation signals.",
      capabilities: ["review", "frontend"],
      protocols: ["seagull"],
    })
  ).profile;

  const room = (
    await api.createRoom({
      owner_user_id: activeUser.user_id,
      slug: roomSlug,
      name: "Frontend Lab",
      description: "Phase 4 browser inspection room.",
      visibility: "public",
    })
  ).room;

  const membership = (
    await api.joinRoom(room.slug, {
      owner_user_id: activeUser.user_id,
      agent_handle: activeProfile.handle,
    })
  ).membership;

  const follow = (
    await api.followAgent({
      owner_user_id: activeUser.user_id,
      follower_handle: activeProfile.handle,
      followed_handle: reviewProfile.handle,
    })
  ).follow;

  const rootPost = (
    await api.createPost({
      owner_user_id: activeUser.user_id,
      author_handle: activeProfile.handle,
      content: `Can ${reviewProfile.handle} inspect the Phase 4 frontend loop?`,
      visibility: "room",
      room_slug: room.slug,
    })
  ).post;

  const replyPost = (
    await api.createPost({
      owner_user_id: reviewUser.user_id,
      author_handle: reviewProfile.handle,
      content: `Replying to ${activeProfile.handle}: the browser loop is visible.`,
      visibility: "public",
      reply_to_post_id: rootPost.post_id,
    })
  ).post;

  const moderation = (
    await api.createModerationRecord({
      owner_user_id: activeUser.user_id,
      target_type: "post",
      target_id: rootPost.post_id,
      action: "review",
      reason: "Phase 4 moderation queue sample",
    })
  ).moderation;

  return touchLoopState({
    apiUrl: api.baseUrl,
    activeUser,
    reviewUser,
    activeProfile,
    reviewProfile,
    ownedProfiles: [activeProfile],
    room,
    membership,
    follow,
    posts: [replyPost, rootPost],
    selectedPostId: rootPost.post_id,
    moderation,
    updatedAt: null,
  });
}

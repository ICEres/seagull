import type { SocialApiClient } from "./api";
import type { AgentNetworkMessage, AgentNetworkDelivery } from "./social";
import type { HubDelivery, HubMessage } from "./message-hub";

export type DirectConversation = {
  threadId: string;
  senderHandle: string;
  recipientHandle: string;
  updatedAt: string;
  snippet: string;
};

export type DirectAttempt = {
  id: string;
  senderHandle: string;
  recipientHandle: string;
  threadId?: string;
  content: string;
  createdAt: string;
  status: "sending" | "unconfirmed" | "failed";
  error?: string;
  messageId?: string;
};

export type DirectNetworkSnapshot = {
  messages: HubMessage[];
  deliveries: HubDelivery[];
  historyLoaded: boolean;
};

type DirectNetworkApi = Pick<
  SocialApiClient,
  "getAgentNetworkInbox" | "getAgentNetworkSent"
>;

const ATTEMPTS_PREFIX = "seagull.web.direct.attempts.v1:";

/** Read every available inbox and sent page for one owned Gull. */
export async function loadDirectNetwork(
  api: DirectNetworkApi,
  ownerId: string,
  senderHandle: string,
  previous?: DirectNetworkSnapshot,
): Promise<DirectNetworkSnapshot> {
  const messages = new Map<string, HubMessage>();
  const deliveries = new Map<string, HubDelivery>();
  for (const message of previous?.messages ?? []) messages.set(message.message_id, message);
  for (const delivery of previous?.deliveries ?? []) deliveries.set(delivery.delivery_id, delivery);
  const knownMessageIds = new Set(previous?.historyLoaded ? previous.messages.map((message) => message.message_id) : []);
  const knownDeliveryIds = new Set(previous?.historyLoaded ? previous.deliveries.map((delivery) => delivery.delivery_id) : []);

  let cursor: string | undefined;
  const inboxCursors = new Set<string>();
  do {
    if (cursor && inboxCursors.has(cursor)) {
      throw new Error("Direct message history is incomplete; refresh to retry.");
    }
    if (cursor) inboxCursors.add(cursor);
    const page = await api.getAgentNetworkInbox(ownerId, senderHandle, {
      limit: 100,
      cursor,
    });
    let overlapped = false;
    for (const item of page.items) {
      if (item.message && knownMessageIds.has(item.message.message_id)) overlapped = true;
      if (item.delivery && knownDeliveryIds.has(item.delivery.delivery_id)) overlapped = true;
      if (item.message) messages.set(item.message.message_id, item.message);
      if (item.delivery) deliveries.set(item.delivery.delivery_id, item.delivery);
    }
    cursor = page.next_cursor ?? undefined;
    if (overlapped) break;
  } while (cursor);

  cursor = undefined;
  const sentCursors = new Set<string>();
  do {
    if (cursor && sentCursors.has(cursor)) {
      throw new Error("Direct message history is incomplete; refresh to retry.");
    }
    if (cursor) sentCursors.add(cursor);
    const page = await api.getAgentNetworkSent(ownerId, senderHandle, {
      limit: 100,
      cursor,
    });
    let overlapped = false;
    for (const message of page.messages) {
      if (knownMessageIds.has(message.message_id)) overlapped = true;
      messages.set(message.message_id, message);
    }
    for (const delivery of page.deliveries ?? []) {
      if (knownDeliveryIds.has(delivery.delivery_id)) overlapped = true;
      deliveries.set(delivery.delivery_id, delivery);
    }
    cursor = page.next_cursor ?? undefined;
    if ((page.truncated || page.has_more) && !cursor) {
      throw new Error("Direct message history is incomplete; refresh to retry.");
    }
    if (overlapped) break;
  } while (cursor);

  return { messages: [...messages.values()], deliveries: [...deliveries.values()], historyLoaded: true };
}

/** Build one-to-one direct conversations from the durable network projection. */
export function collectDirectConversations(
  snapshot: DirectNetworkSnapshot,
  senderHandle: string,
  excludedThreadIds: Set<string> = new Set(),
): DirectConversation[] {
  const local = normalize(senderHandle);
  const byThread = new Map<string, AgentNetworkMessage[]>();

  for (const message of snapshot.messages) {
    if (!message.intent || !["direct", "message", "reply"].includes(message.intent)) continue;
    if (message.visibility !== "direct") continue;
    if (!message.thread_id || excludedThreadIds.has(message.thread_id)) continue;
    const messages = byThread.get(message.thread_id) ?? [];
    messages.push(message);
    byThread.set(message.thread_id, messages);
  }

  const conversations: DirectConversation[] = [];
  for (const [threadId, messages] of byThread) {
    let recipient: string | undefined;
    let latest: HubMessage | undefined;
    let valid = true;
    for (const message of messages) {
      const sender = message.sender_handle?.trim();
      const recipients = message.recipient_handles?.filter(Boolean) ?? [];
      if (!sender || recipients.length !== 1) {
        valid = false;
        break;
      }
      const peer = normalize(sender) === local
        ? recipients[0]
        : normalize(recipients[0]) === local
          ? sender
          : undefined;
      if (!peer || normalize(peer) === local || (recipient && normalize(peer) !== normalize(recipient))) {
        valid = false;
        break;
      }
      recipient ??= peer;
      if (!latest || message.created_at > latest.created_at) latest = message;
    }
    if (!valid || !recipient || !latest) continue;
    conversations.push({
      threadId,
      senderHandle,
      recipientHandle: recipient,
      updatedAt: latest.created_at,
      snippet: latest.content_inline ?? latest.content_ref ?? "",
    });
  }

  return conversations.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

export function readDirectAttempts(apiUrl: string, ownerId: string): DirectAttempt[] {
  const stored = window.localStorage.getItem(attemptsKey(apiUrl, ownerId));
  if (!stored) return [];
  try {
    const parsed = JSON.parse(stored) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap((value) => {
      if (!isDirectAttempt(value)) return [];
      return [{ ...value, status: value.status === "sending" ? "unconfirmed" : value.status }];
    });
  } catch {
    return [];
  }
}

export function writeDirectAttempts(apiUrl: string, ownerId: string, attempts: DirectAttempt[]): void {
  window.localStorage.setItem(attemptsKey(apiUrl, ownerId), JSON.stringify(attempts));
}

function attemptsKey(apiUrl: string, ownerId: string): string {
  return `${ATTEMPTS_PREFIX}${apiUrl.trim().replace(/\/+$/, "")}:${ownerId}`;
}

function normalize(value: string): string {
  return value.trim().toLowerCase();
}

function isDirectAttempt(value: unknown): value is DirectAttempt {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<DirectAttempt>;
  return (
    typeof item.id === "string" &&
    typeof item.senderHandle === "string" &&
    typeof item.recipientHandle === "string" &&
    typeof item.content === "string" &&
    typeof item.createdAt === "string" &&
    (item.status === "sending" || item.status === "unconfirmed" || item.status === "failed")
  );
}

export type { AgentNetworkMessage, AgentNetworkDelivery };

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useMutation, useMutationState, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { GullAvatar, Wing, YOUR_WING } from "@seagulls/ui";

import { SocialApiClient, SocialApiError } from "../lib/api";
import {
  collectDirectConversations,
  loadDirectNetwork,
  readDirectAttempts,
  writeDirectAttempts,
  type DirectAttempt,
  type DirectNetworkSnapshot,
} from "../lib/direct-chat";
import type { HubDelivery, HubMessage } from "../lib/message-hub";
import type { AgentNetworkSendResponse, AgentProfile } from "../lib/social";
import { formatRelativeTime } from "../lib/state";
import { EmptyState, shortHandle, type Notice } from "./shared";

export type DirectChatSelection = {
  senderHandle: string;
  recipientHandle: string;
  threadId?: string;
};

const networkKey = (api: SocialApiClient, owner: string, sender: string) =>
  ["social-direct-network", api.baseUrl, owner, sender] as const;
const threadKey = (api: SocialApiClient, owner: string, sender: string, recipient: string, thread?: string) =>
  ["social-direct-thread", api.baseUrl, owner, sender, recipient, thread] as const;
type DirectThreadData = { messages: HubMessage[]; historyLoaded: boolean };

export function useGullDirectChats(
  api: SocialApiClient,
  ownerUserId: string | null,
  profiles: AgentProfile[],
  excludedThreadIds: Set<string>,
) {
  const queryClient = useQueryClient();
  const queries = useQueries({
    queries: profiles.filter((profile) => profile.owner_user_id === ownerUserId).map((profile) => ({
      queryKey: networkKey(api, ownerUserId!, profile.handle),
      queryFn: () => loadDirectNetwork(
        api,
        ownerUserId!,
        profile.handle,
        queryClient.getQueryData<DirectNetworkSnapshot>(networkKey(api, ownerUserId!, profile.handle)),
      ),
      staleTime: 15000,
      refetchInterval: 15000,
      retry: false,
    })),
  });
  const owned = profiles.filter((profile) => profile.owner_user_id === ownerUserId);
  return {
    conversations: queries.flatMap((query, index) => query.data
      ? collectDirectConversations(query.data, owned[index].handle, excludedThreadIds) : [])
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
    deliveries: queries.flatMap((query) => query.data?.deliveries ?? []),
    isError: queries.some((query) => query.isError),
    refetch: () => queries.forEach((query) => { void query.refetch(); }),
  };
}

function mergeMessages(previous: HubMessage[], incoming: HubMessage[]): HubMessage[] {
  const messages = new Map(previous.map((message) => [message.message_id, message]));
  for (const message of incoming) messages.set(message.message_id, message);
  return [...messages.values()].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.message_id.localeCompare(b.message_id));
}

export function DirectChatThread({
  api, ownerUserId, profiles, senderHandle, recipientHandle, threadId, deliveries = [], onSelect, onNotice,
}: {
  api: SocialApiClient;
  ownerUserId: string;
  profiles: AgentProfile[];
  senderHandle: string;
  recipientHandle: string;
  threadId?: string;
  deliveries?: HubDelivery[];
  onSelect: (selection: DirectChatSelection) => void;
  onNotice: (notice: Notice) => void;
}) {
  const queryClient = useQueryClient();
  const owned = profiles.filter((profile) => profile.owner_user_id === ownerUserId);
  const sender = owned.find((profile) => profile.handle === senderHandle);
  const pair = `${senderHandle}\n${recipientHandle}`;
  const [established, setEstablished] = useState<{ pair: string; threadId: string } | null>(null);
  const currentThreadId = threadId || (established?.pair === pair ? established.threadId : undefined);
  const [draft, setDraft] = useState("");
  const [attempts, setAttempts] = useState(() => readDirectAttempts(api.baseUrl, ownerUserId));
  const selectionRef = useRef<DirectChatSelection>({ senderHandle, recipientHandle, threadId: currentThreadId });
  const previousSelection = useRef(selectionRef.current);
  const threadRef = useRef<HTMLDivElement>(null);
  const mounted = useRef(true);
  selectionRef.current = { senderHandle, recipientHandle, threadId: currentThreadId };

  function updateAttempts(update: (current: DirectAttempt[]) => DirectAttempt[], requireStorage = false) {
    // A send from an earlier mount can finish after a newer chat has saved another attempt.
    const next = update(readDirectAttempts(api.baseUrl, ownerUserId));
    try { writeDirectAttempts(api.baseUrl, ownerUserId, next); }
    catch (error) {
      if (requireStorage) throw error;
      onNotice({ tone: "warn", message: "Could not update message recovery." });
    }
    setAttempts(next);
  }

  const messagesQuery = useQuery({
    queryKey: threadKey(api, ownerUserId, senderHandle, recipientHandle, currentThreadId),
    queryFn: async () => {
      const previous = queryClient.getQueryData<DirectThreadData>(threadKey(api, ownerUserId, senderHandle, recipientHandle, currentThreadId));
      let messages = previous?.messages ?? [];
      const known = new Set(previous?.historyLoaded ? messages.map((message) => message.message_id) : []);
      const participants = new Set([senderHandle.toLowerCase(), recipientHandle.toLowerCase()]);
      let cursor: string | undefined;
      const seen = new Set<string>();
      do {
        const page = await api.getAgentNetworkThread(ownerUserId, senderHandle, currentThreadId!, { limit: 100, cursor });
        if (page.messages.some((message) => message.visibility !== "direct" ||
          !message.sender_handle || !participants.has(message.sender_handle.toLowerCase()) ||
          message.recipient_handles?.length !== 1 || !participants.has(message.recipient_handles[0].toLowerCase()))) {
          throw new Error("This is not a direct conversation with this Gull.");
        }
        messages = mergeMessages(messages, page.messages);
        cursor = page.next_cursor ?? undefined;
        if (page.has_more && !cursor) throw new Error("Could not load the full conversation.");
        if (cursor && seen.has(cursor)) throw new Error("Could not load the full conversation.");
        if (cursor) seen.add(cursor);
        if (page.messages.some((message) => known.has(message.message_id))) break;
      } while (cursor);
      return { messages, historyLoaded: true };
    },
    enabled: Boolean(sender && currentThreadId),
    staleTime: 5000,
    refetchInterval: currentThreadId ? 5000 : false,
    retry: false,
  });
  const messages = messagesQuery.data?.messages ?? [];
  const visibleAttempts = attempts.filter((attempt) => attempt.senderHandle === senderHandle &&
    attempt.recipientHandle === recipientHandle && (!attempt.threadId || attempt.threadId === currentThreadId));
  const locked = Boolean(currentThreadId || visibleAttempts.length);

  const sendMutation = useMutation({
    mutationKey: ["social-direct-send", api.baseUrl, ownerUserId],
    mutationFn: async (attempt: DirectAttempt) => {
      const result = await api.sendAgentNetworkMessage({
        owner_user_id: ownerUserId,
        sender_handle: attempt.senderHandle,
        recipient_handles: [attempt.recipientHandle],
        content: attempt.content,
        intent: "direct",
        visibility: "direct",
        ...(attempt.threadId ? { thread_id: attempt.threadId } : {}),
        idempotency_key: attempt.id,
      });
      if (!(result.thread_id || result.message?.thread_id) || !(result.message_id || result.message?.message_id)) {
        throw new Error("Could not confirm delivery.");
      }
      return result;
    },
    onSuccess: (result: AgentNetworkSendResponse, attempt) => {
      const confirmedThread = result.thread_id || result.message!.thread_id;
      const message: HubMessage = {
        message_id: result.message_id || result.message!.message_id,
        thread_id: confirmedThread,
        sender_agent_id: "",
        recipient_agent_ids: [],
        content_inline: attempt.content,
        intent: "direct",
        visibility: "direct",
        schema_version: "seagull.message.v1",
        safety_status: "approved",
        created_at: attempt.createdAt,
        ...result.message,
        sender_handle: attempt.senderHandle,
        recipient_handles: [attempt.recipientHandle],
      };
      queryClient.setQueryData<DirectThreadData>(threadKey(api, ownerUserId, attempt.senderHandle, attempt.recipientHandle, confirmedThread),
        (current) => ({ messages: mergeMessages(current?.messages ?? [], [message]), historyLoaded: current?.historyLoaded ?? false }));
      queryClient.setQueryData<DirectNetworkSnapshot>(networkKey(api, ownerUserId, attempt.senderHandle), (current) => ({
        messages: mergeMessages(current?.messages ?? [], [message]),
        deliveries: [...(current?.deliveries ?? []), ...(result.deliveries ?? [])],
        historyLoaded: current?.historyLoaded ?? false,
      }));
      updateAttempts((current) => current.filter((item) => item.id !== attempt.id));
      const selected = selectionRef.current;
      if (mounted.current && selected.senderHandle === attempt.senderHandle && selected.recipientHandle === attempt.recipientHandle &&
        (!selected.threadId || selected.threadId === attempt.threadId)) {
        setEstablished({ pair: `${attempt.senderHandle}\n${attempt.recipientHandle}`, threadId: confirmedThread });
        onSelect({ senderHandle: attempt.senderHandle, recipientHandle: attempt.recipientHandle, threadId: confirmedThread });
      }
      void queryClient.invalidateQueries({ queryKey: ["social-direct-network", api.baseUrl, ownerUserId] });
    },
    onError: (error: Error, attempt) => {
      const rejected = error instanceof SocialApiError && error.status >= 400 && error.status < 500 &&
        ![408, 429].includes(error.status) && error.code !== "invalid_json";
      updateAttempts((current) => current.map((item) => item.id === attempt.id
        ? { ...item, status: rejected ? "failed" : "unconfirmed", error: error.message } : item));
    },
  });
  const pendingSends = useMutationState({
    filters: { mutationKey: ["social-direct-send", api.baseUrl, ownerUserId], status: "pending" },
    select: (mutation) => mutation.state.variables as DirectAttempt,
  });
  const busy = pendingSends.some((attempt) => attempt.senderHandle === senderHandle && attempt.recipientHandle === recipientHandle);
  const pendingIds = pendingSends.map((attempt) => attempt.id).sort().join(":");

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { setAttempts(readDirectAttempts(api.baseUrl, ownerUserId)); }, [api.baseUrl, ownerUserId, pendingIds]);

  useEffect(() => {
    const previous = previousSelection.current;
    if (previous.senderHandle !== senderHandle || previous.recipientHandle !== recipientHandle ||
      (previous.threadId && currentThreadId && previous.threadId !== currentThreadId)) setDraft("");
    previousSelection.current = { senderHandle, recipientHandle, threadId: currentThreadId };
  }, [senderHandle, recipientHandle, currentThreadId]);

  useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight;
  }, [messages.length, visibleAttempts.length, pair]);

  function retry(attempt: DirectAttempt) {
    if (busy || !owned.some((profile) => profile.handle === attempt.senderHandle)) return;
    updateAttempts((current) => current.map((item) => item.id === attempt.id ? { ...item, status: "sending", error: undefined } : item));
    sendMutation.mutate(attempt);
  }

  function submit(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!sender || !draft.trim() || busy || visibleAttempts.length || (currentThreadId && !messagesQuery.isSuccess)) return;
    const attempt: DirectAttempt = {
      id: crypto.randomUUID(), senderHandle, recipientHandle, threadId: currentThreadId,
      content: draft.trim(), createdAt: new Date().toISOString(), status: "sending",
    };
    try { updateAttempts((current) => [...current, attempt], true); }
    catch { onNotice({ tone: "error", message: "Could not keep this message. Please try again." }); return; }
    setDraft("");
    sendMutation.mutate(attempt);
  }

  function onDraftKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); }
  }

  return (
    <div className="grid min-h-[420px] min-w-0 grid-rows-[auto_minmax(0,1fr)_auto]">
      <div className="flex items-center gap-3 border-b border-line px-5 py-3">
        <GullAvatar handle={recipientHandle} size={34} />
        <span className="min-w-0"><strong className="block text-[0.95rem]">{shortHandle(recipientHandle)}</strong>
          <span className="block text-[0.74rem] font-bold text-faint [overflow-wrap:anywhere]">{recipientHandle}</span></span>
      </div>
      <div ref={threadRef} aria-live="polite" className="grid content-start gap-2.5 overflow-y-auto bg-bg px-[22px] py-5">
        {messagesQuery.isError ? <div role="alert" className="text-[0.8rem] text-danger">Could not open this chat. <button type="button" onClick={() => void messagesQuery.refetch()} className="border-0 bg-transparent p-0 font-extrabold text-accent">Retry</button></div> : null}
        {!sender ? <EmptyState title="Sender unavailable" detail="" /> : currentThreadId && messagesQuery.isPending ? <EmptyState title="Opening…" detail="" /> : null}
        {!currentThreadId && !visibleAttempts.length ? <EmptyState title="Say hello" detail="" /> : null}
        {messages.map((message) => <DirectBubble key={message.message_id} content={message.content_inline || (message.content_ref ? "Shared content" : "")} outgoing={message.sender_handle === senderHandle} handle={message.sender_handle ?? recipientHandle} status={message.sender_handle === senderHandle ? deliveryLabel(deliveries.find((item) => item.message_id === message.message_id)) : ""} createdAt={message.created_at} />)}
        {visibleAttempts.map((attempt) => {
          const sending = pendingSends.some((pending) => pending.id === attempt.id);
          return <div key={attempt.id} role={sending ? "status" : "alert"}>
          <DirectBubble content={attempt.content} outgoing handle={senderHandle} status={sending ? "Sending…" : attempt.status === "failed" ? "Failed" : "Unconfirmed"} createdAt={attempt.createdAt} />
          {!sending ? <div className="mt-1 flex justify-end gap-3 pr-[34px] text-[0.74rem] font-extrabold">
            <button type="button" disabled={busy} onClick={() => retry(attempt)} className="border-0 bg-transparent p-0 text-accent">Retry</button>
            {attempt.status === "failed" ? <button type="button" onClick={() => { setDraft(attempt.content); updateAttempts((current) => current.filter((item) => item.id !== attempt.id)); }} className="border-0 bg-transparent p-0 text-muted">Restore draft</button> : null}
          </div> : null}
          {attempt.error ? <details className="mt-1 text-right text-[0.7rem] text-muted"><summary>Details</summary>{attempt.error}</details> : null}
        </div>; })}
      </div>
      <form onSubmit={submit} className="relative mx-[18px] mt-3.5 mb-4 rounded-[10px] border-2 bg-bg px-2 py-1" style={{ borderColor: draft ? "var(--accent)" : "var(--line)" }}>
        <span className="absolute top-0 right-6 flex -translate-y-[58%] items-center gap-1.5 bg-card px-0.5">
          <Wing path={YOUR_WING} size={24} className="text-ink" />
          {!locked && owned.length > 1 ? <select aria-label="Send as" value={senderHandle} onChange={(event) => onSelect({ senderHandle: event.target.value, recipientHandle })} className="min-h-0! w-auto! rounded-none! border-0! bg-card! px-0! py-0! text-[0.72rem]! font-extrabold text-muted">
            {owned.map((profile) => <option key={profile.handle} value={profile.handle}>{shortHandle(profile.handle)}</option>)}
          </select> : <span className="text-[0.7rem] font-extrabold text-faint">{shortHandle(senderHandle)}</span>}
        </span>
        <div className="flex items-end gap-2 px-1.5 py-0.5">
          <textarea rows={1} aria-label="Message" value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={onDraftKey} placeholder={`Message ${shortHandle(recipientHandle)}…`} className="box-border max-h-[140px] min-h-[44px] flex-1 resize-none border-0 bg-transparent px-1 py-[11px] text-base leading-[1.45]" />
          <button type="submit" disabled={!sender || !draft.trim() || busy || Boolean(visibleAttempts.length) || Boolean(currentThreadId && !messagesQuery.isSuccess)} className="mb-1 min-h-9 rounded-lg border-0 bg-accent px-3.5 text-[0.8rem] font-extrabold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-40">Send</button>
        </div>
      </form>
    </div>
  );
}

function deliveryLabel(delivery?: HubDelivery): string {
  if (delivery?.acked_at || ["acked", "replied"].includes(delivery?.status ?? "")) return "Delivered";
  if (["failed", "rejected", "dropped"].includes(delivery?.status ?? "")) return "Failed";
  if (delivery?.status === "needs_review") return "Needs review";
  return "Submitted";
}

function DirectBubble({ content, outgoing, handle, status, createdAt }: {
  content: string; outgoing: boolean; handle: string; status: string; createdAt: string;
}) {
  return <div className={`flex items-end gap-2 ${outgoing ? "flex-row-reverse" : "flex-row"}`}>
    <GullAvatar handle={handle} size={26} background={outgoing ? "var(--ink)" : "var(--accent)"} color={outgoing ? "var(--bg)" : "#ffffff"} />
    <article className="grid max-w-[78%] gap-1 rounded-md px-3.5 py-[11px]" style={{ background: outgoing ? "var(--accent-soft)" : "var(--card)", boxShadow: outgoing ? "none" : "var(--shadow)" }}>
      <span className="leading-[1.45] whitespace-pre-wrap text-body [overflow-wrap:anywhere]">{content}</span>
      <span className="flex flex-wrap justify-end gap-1.5 text-[0.68rem] font-bold text-faint"><span>{status}</span><span>{formatRelativeTime(createdAt)}</span></span>
    </article>
  </div>;
}

import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { useMutation, useMutationState, useQuery, useQueryClient } from "@tanstack/react-query";

import { SocialApiClient, SocialApiError } from "../lib/api";
import { configuredMessageApiUrl, MessageHubClient, MessageHubError } from "../lib/message-hub";
import type { AgentChatMessage, AgentProfile, LoopState, RuntimeMode } from "../lib/social";
import { formatRelativeTime } from "../lib/state";
import { GullAvatar, Wing, YOUR_WING, statusDotColor, wingFor } from "@seagulls/ui";
import { Chip, EmptyState, shortHandle, shortId, type Notice } from "./shared";
import { DirectChatThread, useGullDirectChats, type DirectChatSelection } from "./direct-chat";

type AppMutationError = Error | SocialApiError;
type SendChatMessage = { chatId: string; content: string; owner: string };
type AgentChatMessagesResponse = {
  items: AgentChatMessage[];
  runtime_mode?: RuntimeMode | null;
};

export function ChatPage({
  api,
  state,
  profiles,
  messageApi,
  onNotice,
}: {
  api: SocialApiClient;
  state: LoopState;
  profiles: AgentProfile[];
  messageApi?: MessageHubClient;
  onNotice: (notice: Notice) => void;
}) {
  const navigate = useNavigate();
  const params = useParams();
  const [searchParams] = useSearchParams();
  const hub = useMemo(() => messageApi ?? new MessageHubClient(configuredMessageApiUrl()), [messageApi]);
  const queryClient = useQueryClient();
  const threadRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const [picking, setPicking] = useState(false);
  const [draft, setDraft] = useState("");
  const [flying, setFlying] = useState(false);
  const [unconfirmedMessages, setUnconfirmedMessages] = useState<AgentChatMessage[]>([]);
  const [recipientInput, setRecipientInput] = useState("");
  const [recipientAddress, setRecipientAddress] = useState("");

  const ownerUserId = state.activeUser?.user_id ?? null;
  const selectedChatId = params.chatId ?? null;
  const directMode = selectedChatId === "direct";
  const ownedProfiles = profiles.filter((profile) => profile.owner_user_id === ownerUserId);
  const directSelection: DirectChatSelection | null = directMode && searchParams.get("sender") && searchParams.get("recipient")
    ? { senderHandle: searchParams.get("sender")!, recipientHandle: searchParams.get("recipient")!, threadId: searchParams.get("thread") || undefined }
    : null;

  const chatsQuery = useQuery({
    queryKey: ["social-agent-chats", api.baseUrl, ownerUserId],
    queryFn: () => api.getAgentChats(ownerUserId ?? undefined),
    enabled: Boolean(ownerUserId),
  });
  const chats = chatsQuery.data?.items ?? [];
  const selectedChat = directMode ? null :
    chats.find((chat) => chat.chat_id === selectedChatId) ?? (selectedChatId ? null : chats[0] ?? null);
  const directChats = useGullDirectChats(api, ownerUserId, ownedProfiles, new Set(chats.flatMap((chat) => chat.hub_thread_id ? [chat.hub_thread_id] : [])));

  useEffect(() => {
    if (picking || directMode || chats.length === 0) {
      return;
    }
    // Only auto-select when no chat is addressed. A chatId that is missing from
    // the cached list may be a freshly created chat whose refetch is still in
    // flight — redirecting away from it would open the wrong thread.
    if (!selectedChatId) {
      navigate(`/chat/${chats[0].chat_id}`, { replace: true });
    }
  }, [chats, navigate, picking, selectedChatId, directMode]);

  function scrollThread() {
    const element = threadRef.current;
    if (element) {
      element.scrollTop = element.scrollHeight;
    }
  }

  const createChatMutation = useMutation({
    mutationFn: async (agentHandle: string) => {
      if (!ownerUserId) {
        throw new Error("Sign in before starting a chat.");
      }
      const existing = chats.find((chat) => chat.agent_handle === agentHandle);
      if (existing) {
        return existing;
      }
      const result = await api.createAgentChat({ owner_user_id: ownerUserId, agent_handle: agentHandle });
      return result.chat;
    },
    onSuccess: (chat) => {
      setPicking(false);
      void queryClient.invalidateQueries({ queryKey: ["social-agent-chats"] });
      navigate(`/chat/${chat.chat_id}`);
    },
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  const sendMutation = useMutation({
    mutationKey: ["social-agent-chat-send", api.baseUrl, ownerUserId],
    mutationFn: async ({ chatId, content, owner }: SendChatMessage) => {
      return api.createAgentChatMessage(chatId, { owner_user_id: owner, content });
    },
    onMutate: async ({ chatId, content, owner }) => {
      const queryKey = ["social-agent-chat-messages", api.baseUrl, owner, chatId];
      await queryClient.cancelQueries({ queryKey, exact: true });
      const now = new Date().toISOString();
      const optimisticMessage: AgentChatMessage = {
        chat_message_id: `pending_${crypto.randomUUID()}`,
        chat_id: chatId,
        owner_user_id: owner,
        sender_type: "human",
        content,
        hub_message_id: null,
        hub_thread_id: null,
        delivery_status: "sending",
        delivery_error: null,
        ai_run_id: null,
        ai_run_state: null,
        ai_error: null,
        created_at: now,
        updated_at: now,
      };
      queryClient.setQueryData<AgentChatMessagesResponse>(queryKey, (current) => ({
        ...current,
        items: [...(current?.items ?? []), optimisticMessage],
      }));
      return { queryKey, optimisticMessage };
    },
    onSuccess: ({ message, reply }, _variables, context) => {
      const confirmed = reply ? [message, reply] : [message];
      queryClient.setQueryData<AgentChatMessagesResponse>(context.queryKey, (current) => ({
        ...current,
        items: [
          ...(current?.items ?? []).filter(
            (item) => item.chat_message_id !== context.optimisticMessage.chat_message_id &&
              !confirmed.some((result) => result.chat_message_id === item.chat_message_id),
          ),
          ...confirmed,
        ],
      }));
      void queryClient.invalidateQueries({ queryKey: ["social-agent-chats"] });
      if (!reply && (message.delivery_status === "delivery_failed" || message.ai_error)) {
        onNotice({
          tone: "warn",
          message: message.ai_error
            ? "Your message was saved, but a reply is unavailable."
            : "Your message was saved, but delivery could not be confirmed.",
        });
      }
    },
    onError: (error: AppMutationError, _variables, context) => {
      if (context) {
        queryClient.setQueryData<AgentChatMessagesResponse>(context.queryKey, (current) => ({
          ...current,
          items: (current?.items ?? []).filter(
            (item) => item.chat_message_id !== context.optimisticMessage.chat_message_id,
          ),
        }));
        setUnconfirmedMessages((current) => [
          ...current,
          { ...context.optimisticMessage, delivery_status: "send_unconfirmed", delivery_error: error.message },
        ]);
      }
      onNotice({ tone: "error", message: "Could not confirm delivery. Your message is kept in the conversation." });
    },
    onSettled: (_data, _error, { owner }) => {
      void queryClient.invalidateQueries({ queryKey: ["social-ai-usage", api.baseUrl, owner] });
    },
  });

  const pendingSends = useMutationState({
    filters: { mutationKey: ["social-agent-chat-send", api.baseUrl, ownerUserId], status: "pending" },
    select: (mutation) => mutation.state.variables as SendChatMessage,
  });
  const sendingToSelectedChat = pendingSends.some(
    (send) => send.chatId === selectedChat?.chat_id && send.owner === ownerUserId,
  );
  const messagesQuery = useQuery({
    queryKey: ["social-agent-chat-messages", api.baseUrl, ownerUserId, selectedChat?.chat_id],
    queryFn: () => api.getAgentChatMessages(selectedChat!.chat_id, ownerUserId ?? undefined),
    enabled: Boolean(ownerUserId && selectedChat) && !sendingToSelectedChat,
    staleTime: 5000,
    refetchInterval: selectedChat && !sendingToSelectedChat ? 5000 : false,
  });
  const messages = messagesQuery.data?.items ?? [];
  const runtimeMode: RuntimeMode =
    messagesQuery.data?.runtime_mode ??
    [...messages].reverse().find((message) => message.runtime_mode)?.runtime_mode ??
    "cloud";
  const recoveryMessages = unconfirmedMessages.filter(
    (message) => message.chat_id === selectedChat?.chat_id && message.owner_user_id === ownerUserId,
  );

  useEffect(() => {
    setDraft("");
    setFlying(false);
    scrollThread();
  }, [ownerUserId, selectedChat?.chat_id]);

  useEffect(() => {
    scrollThread();
  }, [messages.length, recoveryMessages.length, sendingToSelectedChat]);

  function submitDraft(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const text = draft.trim();
    if (text && !sendingToSelectedChat && !messagesQuery.isPending && selectedChat && ownerUserId) {
      setDraft("");
      setFlying(true);
      window.setTimeout(() => setFlying(false), 950);
      sendMutation.mutate({ chatId: selectedChat.chat_id, content: text, owner: ownerUserId });
    }
  }

  function restoreDraft(message: AgentChatMessage) {
    setDraft((current) => current ? `${current}\n${message.content}` : message.content);
    setUnconfirmedMessages((current) => current.filter((item) => item.chat_message_id !== message.chat_message_id));
    composerRef.current?.focus();
  }

  function onDraftKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submitDraft();
    }
  }

  function chatSnippet(chatId: string, fallback: string): string {
    const cached = queryClient.getQueryData<AgentChatMessagesResponse>([
      "social-agent-chat-messages",
      api.baseUrl,
      ownerUserId,
      chatId,
    ]);
    const last = cached?.items[cached.items.length - 1];
    return last?.content ?? fallback;
  }

  const chatAgent = selectedChat
    ? profiles.find((profile) => profile.handle === selectedChat.agent_handle) ?? null
    : null;
  const showPicker = picking || (!selectedChat && !directSelection && !chatsQuery.isFetching);
  const fullAddress = /^@[a-z0-9_.-]+:[a-z0-9.-]+$/i.test(recipientAddress);
  const recipientQuery = useQuery({
    queryKey: ["message-gull", hub.baseUrl, recipientAddress],
    queryFn: () => hub.getAgent(recipientAddress),
    enabled: showPicker && fullAddress,
    retry: false,
    staleTime: 30000,
  });
  const lookupMissing = recipientQuery.error instanceof MessageHubError && recipientQuery.error.status === 404;
  const lookupMessage = recipientAddress !== recipientInput.trim().toLowerCase() || recipientQuery.isFetching
    ? "Looking up…" : !fullAddress ? "Use a full handle." : lookupMissing ? "Gull not found." : "Could not look up this Gull.";
  useEffect(() => {
    const timer = window.setTimeout(() => setRecipientAddress(recipientInput.trim().toLowerCase()), 250);
    return () => window.clearTimeout(timer);
  }, [recipientInput]);

  function selectDirect(selection: DirectChatSelection, replace = false) {
    setPicking(false);
    const query = new URLSearchParams({ sender: selection.senderHandle, recipient: selection.recipientHandle });
    if (selection.threadId) query.set("thread", selection.threadId);
    navigate(`/chat/direct?${query}`, { replace });
  }

  function selectRecipient() {
    const recipient = recipientQuery.data?.agent;
    if (!recipient || recipientAddress !== recipientInput.trim().toLowerCase()) return;
    if (ownedProfiles.some((profile) => profile.handle === recipient.handle)) {
      createChatMutation.mutate(recipient.handle);
      return;
    }
    const sender = ownedProfiles.find((profile) => profile.handle === state.activeProfile?.handle) ?? ownedProfiles[0];
    if (!sender) return;
    const existing = directChats.conversations.find((conversation) => conversation.senderHandle === sender.handle && conversation.recipientHandle === recipient.handle);
    selectDirect({ senderHandle: sender.handle, recipientHandle: recipient.handle, threadId: existing?.threadId });
  }

  const conversationRows = [
    ...chats.map((chat) => ({ kind: "assistant" as const, key: chat.chat_id, updatedAt: chat.updated_at, chat })),
    ...directChats.conversations.map((chat) => ({ kind: "direct" as const, key: `${chat.senderHandle}:${chat.threadId}`, updatedAt: chat.updatedAt, chat })),
  ].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));

  return (
    <div className="mx-auto max-w-[1020px]">
      <header className="mb-[18px] flex flex-wrap items-baseline gap-3">
        <h1 className="m-0 text-[1.4rem] font-extrabold tracking-[-0.02em]">
          Chat<span className="text-accent">.</span>
        </h1>
        <span className="text-[0.84rem] font-bold text-faint">direct line to any gull</span>
        <span className="flex-1" />
        <button
          type="button"
          onClick={() => { setPicking(true); setRecipientInput(""); setRecipientAddress(""); }}
          className="min-h-9 rounded-lg border-0 bg-accent px-3.5 text-[0.84rem] font-extrabold text-white hover:bg-accent-strong"
        >
          New chat
        </button>
      </header>

      <div className="grid h-[calc(100vh-190px)] min-h-[460px] grid-cols-[264px_minmax(0,1fr)] overflow-hidden rounded-xl border border-line bg-card max-[860px]:grid-cols-1 max-[860px]:h-auto">
        <div className="overflow-y-auto border-r border-line max-[860px]:max-h-52 max-[860px]:border-r-0 max-[860px]:border-b">
          {conversationRows.length === 0 ? (
            <EmptyState title="No chats yet" detail="Start one — your gulls are listening." />
          ) : (
            conversationRows.map((row) => {
              const assistant = row.kind === "assistant" ? row.chat : null;
              const direct = row.kind === "direct" ? row.chat : null;
              const handle = assistant?.agent_handle ?? direct!.recipientHandle;
              const active = !picking && (assistant ? selectedChat?.chat_id === assistant.chat_id
                : directSelection?.senderHandle === direct!.senderHandle && directSelection.threadId === direct!.threadId);
              return (
                <button
                  key={row.key}
                  type="button"
                  onClick={() => {
                    setPicking(false);
                    if (direct) selectDirect(direct);
                    else navigate(`/chat/${assistant!.chat_id}`);
                  }}
                  className={`flex w-full items-start gap-2.5 border-0 border-b border-line px-4 py-3.5 text-left text-ink hover:bg-accent-soft ${
                    active ? "bg-accent-soft" : "bg-transparent"
                  }`}
                >
                  <GullAvatar handle={handle} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline gap-2">
                      <strong className="overflow-hidden text-[0.9rem] text-ellipsis whitespace-nowrap">
                        {assistant?.title ?? shortHandle(handle)}
                      </strong>
                      <span className="ml-auto flex-none text-[0.7rem] font-extrabold text-faint">
                        {formatRelativeTime(row.updatedAt)}
                      </span>
                    </span>
                    <span className="mt-0.5 block overflow-hidden text-[0.8rem] text-ellipsis whitespace-nowrap text-muted">
                      {assistant ? chatSnippet(assistant.chat_id, shortHandle(handle)) : direct!.snippet || handle}
                    </span>
                  </span>
                </button>
              );
            })
          )}
          {directChats.isError ? <div className="px-4 py-3 text-[0.74rem] text-muted">Gull chats unavailable. <button type="button" onClick={directChats.refetch} className="border-0 bg-transparent p-0 font-extrabold text-accent">Retry</button></div> : null}
        </div>

        {showPicker ? (
          <div className="grid place-content-center justify-items-center gap-[22px] bg-bg p-[30px]">
            <div className="flex w-full max-w-[340px] items-center gap-3">
              <label htmlFor="chat-recipient" className="text-[0.8rem] font-extrabold text-muted">To</label>
              <input id="chat-recipient" value={recipientInput} onChange={(event) => setRecipientInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); selectRecipient(); } }} placeholder="@name:gulls.ai" autoComplete="off" spellCheck={false} />
            </div>
            {recipientInput.trim() ? <div className="w-full max-w-[340px]" aria-live="polite">
              {recipientInput.trim().toLowerCase() === recipientAddress && recipientQuery.data?.agent ? <button type="button" onClick={selectRecipient} disabled={!ownedProfiles.length || createChatMutation.isPending} className="flex w-full items-center gap-3 rounded-xl border border-line bg-card px-[18px] py-4 text-left hover:border-accent disabled:opacity-40">
                <GullAvatar handle={recipientQuery.data.agent.handle} size={34} />
                <span className="min-w-0"><strong className="block text-[0.85rem]">{recipientQuery.data.agent.display_name || shortHandle(recipientQuery.data.agent.handle)}</strong><span className="block text-[0.74rem] font-bold text-faint [overflow-wrap:anywhere]">{recipientQuery.data.agent.handle}</span></span>
              </button> : <span role={recipientQuery.isError ? "alert" : undefined} className="text-[0.8rem] text-muted">{lookupMessage}{recipientQuery.isError && !lookupMissing ? <> <button type="button" onClick={() => void recipientQuery.refetch()} className="border-0 bg-transparent p-0 font-extrabold text-accent">Retry</button></> : null}</span>}
            </div> : ownedProfiles.length === 0 ? (
              <EmptyState title="No gulls yet" detail="Register a gull in the Flock first." />
            ) : (
              <div className="flex flex-wrap justify-center gap-3.5">
                {ownedProfiles.map((profile) => (
                  <button
                    key={profile.agent_id}
                    type="button"
                    onClick={() => createChatMutation.mutate(profile.handle)}
                    disabled={createChatMutation.isPending}
                    className="grid min-w-[116px] justify-items-center gap-2 rounded-xl border border-line bg-card p-[18px] px-5 text-accent hover:border-accent disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <Wing path={wingFor(profile.handle)} size={34} strokeWidth={2.6} />
                    <strong className="text-[0.85rem] text-ink">{shortHandle(profile.handle)}</strong>
                    <span className="flex items-center gap-1.5 text-[0.72rem] font-extrabold text-faint">
                      <span
                        className="h-[5px] w-[5px] rounded-full"
                        style={{ background: statusDotColor(profile.status) }}
                      />
                      {profile.status}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : directSelection && ownerUserId ? (
          <DirectChatThread key={`${api.baseUrl}:${ownerUserId}`} api={api} ownerUserId={ownerUserId} profiles={ownedProfiles} {...directSelection} deliveries={directChats.deliveries} onSelect={(selection) => selectDirect(selection, true)} onNotice={onNotice} />
        ) : selectedChat ? (
          <div className="grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)_auto]">
            <div className="flex items-center gap-3 border-b border-line px-5 py-3">
              <GullAvatar
                handle={selectedChat.agent_handle}
                size={34}
                animation={sendingToSelectedChat ? "gull-flap 0.4s ease-in-out infinite" : undefined}
              />
              <span className="min-w-0">
                <strong className="block text-[0.95rem]">{selectedChat.title}</strong>
                <span className="flex items-center gap-1.5 text-[0.74rem] font-extrabold text-faint">
                  <span
                    className="h-[5px] w-[5px] rounded-full"
                    style={{ background: statusDotColor(chatAgent?.status) }}
                  />
                  {shortHandle(selectedChat.agent_handle)}
                  {chatAgent ? ` · ${chatAgent.status}` : ""}
                  {` · ${runtimeModeLabel(runtimeMode)}`}
                </span>
              </span>
              <span className="ml-auto flex flex-wrap justify-end gap-1.5">
                {(chatAgent?.capabilities ?? []).slice(0, 3).map((capability) => (
                  <Chip key={capability}>{capability}</Chip>
                ))}
              </span>
            </div>

            <div ref={threadRef} aria-live="polite" className="grid content-start gap-2.5 overflow-y-auto bg-bg px-[22px] py-5">
              {messagesQuery.isFetching && messages.length === 0 && recoveryMessages.length === 0 ? (
                <EmptyState title="Opening the thread" detail="Fetching stored messages." />
              ) : messages.length === 0 && recoveryMessages.length === 0 ? (
                <EmptyState title="Say hello" detail="Messages travel with prompt and skill snapshots." />
              ) : (
                messages.map((message, index) => (
                  <ChatBubble
                    key={message.chat_message_id}
                    message={message}
                    agentHandle={selectedChat.agent_handle}
                    isLast={index === messages.length - 1}
                  />
                ))
              )}
              {recoveryMessages.map((message) => (
                <aside key={message.chat_message_id} role="alert" className="grid gap-2 rounded-lg border border-amber bg-amber-soft p-3 text-[0.8rem]">
                  <strong>Could not confirm delivery.</strong>
                  <span className="text-muted">This copy is kept for recovery. Check the conversation before sending again.</span>
                  <blockquote className="m-0 border-l-2 border-amber pl-3 whitespace-pre-wrap [overflow-wrap:anywhere]">{message.content}</blockquote>
                  <div className="flex gap-3 font-extrabold">
                    <button type="button" onClick={() => restoreDraft(message)} className="border-0 bg-transparent p-0 text-accent-strong">Restore draft</button>
                    <button type="button" onClick={() => setUnconfirmedMessages((current) => current.filter((item) => item.chat_message_id !== message.chat_message_id))} className="border-0 bg-transparent p-0 text-muted">Dismiss</button>
                  </div>
                </aside>
              ))}
              {sendingToSelectedChat ? (
                <div role="status" className="flex items-center gap-2.5 py-2 text-[0.8rem] font-bold text-muted">
                  <GullAvatar handle={selectedChat.agent_handle} size={26} />
                  <span className="motion-safe:animate-pulse">{waitingForRuntimeLabel(runtimeMode)}</span>
                </div>
              ) : null}
            </div>

            <form
              onSubmit={submitDraft}
              className="relative mx-[18px] mt-3.5 mb-4 box-border rounded-[10px] border-2 bg-bg px-2 py-1 transition-colors"
              style={{ borderColor: draft ? "var(--accent)" : "var(--line)" }}
            >
              <span
                aria-hidden="true"
                className="pointer-events-none absolute top-0 right-6 flex -translate-y-[58%] items-end gap-1.5"
              >
                <Wing
                  path={YOUR_WING}
                  size={24}
                  className="text-ink"
                  style={draft ? { animation: "gull-flap 0.6s ease-in-out infinite" } : undefined}
                />
                <span className="text-[0.66rem] font-extrabold text-faint">@you</span>
              </span>
              {flying ? (
                <span
                  aria-hidden="true"
                  className="pointer-events-none absolute -top-1 right-[60px] text-accent"
                  style={{ animation: "fly-off 0.9s ease-in forwards" }}
                >
                  <Wing
                    path={wingFor(selectedChat.agent_handle)}
                    size={26}
                    style={{ animation: "gull-flap 0.3s ease-in-out infinite" }}
                  />
                </span>
              ) : null}
              <div className="flex items-end gap-2 px-1.5 py-0.5">
                <textarea
                  ref={composerRef}
                  rows={1}
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={onDraftKey}
                  placeholder={`Message ${shortHandle(selectedChat.agent_handle)}…`}
                  aria-label="Message"
                  className="box-border max-h-[140px] min-h-[44px] flex-1 resize-none border-0 bg-transparent px-1 py-[11px] text-base leading-[1.45]"
                />
                <button
                  type="submit"
                  disabled={!draft.trim() || sendingToSelectedChat || messagesQuery.isPending}
                  className="mb-1 min-h-9 rounded-lg border-0 bg-accent px-3.5 text-[0.8rem] font-extrabold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Send
                </button>
              </div>
              <div className="flex items-center gap-1.5 px-1.5 pb-1.5">
                {selectedChat.prompt_asset_id ? <Chip tone="accent">Prompt {shortId(selectedChat.prompt_asset_id)}</Chip> : null}
                {selectedChat.skill_asset_id ? <Chip tone="accent">Skill {shortId(selectedChat.skill_asset_id)}</Chip> : null}
                <span className="flex-1" />
                <span className="text-[0.72rem] font-bold text-faint">Enter to send · Shift+Enter for a new line</span>
              </div>
            </form>
          </div>
        ) : (
          <EmptyState
            title={chatsQuery.isFetching ? "Loading chats" : "No chat selected"}
            detail="Pick a thread on the left or start a new one."
          />
        )}
      </div>
    </div>
  );
}

function runtimeModeLabel(mode: RuntimeMode): string {
  return mode === "local" ? "Local" : mode === "manual" ? "Manual" : "Cloud";
}

function waitingForRuntimeLabel(mode: RuntimeMode): string {
  return mode === "local"
    ? "Waiting for local connection or reply…"
    : mode === "manual"
      ? "Waiting for your reply…"
      : "Generating a cloud reply — waiting for reply…";
}

function ChatBubble({
  message,
  agentHandle,
  isLast,
}: {
  message: AgentChatMessage;
  agentHandle: string;
  isLast: boolean;
}) {
  const isHuman = message.sender_type === "human";
  const delivered = message.delivery_status === "delivered";
  const deliveryFailed = message.delivery_status === "delivery_failed";
  const failed = deliveryFailed || Boolean(message.ai_error);
  const status = message.delivery_status === "sending" ? "Sending…"
    : deliveryFailed ? "Delivery not confirmed"
    : delivered ? "Delivered" : "Saved";
  return (
    <div className={`flex items-end gap-2 ${isHuman ? "flex-row-reverse" : "flex-row"}`}>
      <span
        aria-hidden="true"
        className="grid h-[26px] w-[26px] flex-none place-items-center rounded-full"
        style={{
          background: isHuman ? "var(--ink)" : "var(--accent)",
          color: isHuman ? "var(--bg)" : "#ffffff",
        }}
      >
        <Wing path={isHuman ? YOUR_WING : wingFor(agentHandle)} size={14} strokeWidth={3.4} flip={isHuman} />
      </span>
      <article
        className="box-border grid max-w-[78%] gap-1 rounded-md px-3.5 py-[11px]"
        style={{
          background: isHuman ? "var(--accent-soft)" : "var(--card)",
          boxShadow: isHuman ? "none" : "var(--shadow)",
          animation: isLast ? "msg-in 0.3s ease-out" : "none",
        }}
      >
        <span className="leading-[1.45] whitespace-pre-wrap text-body [overflow-wrap:anywhere]">{message.content}</span>
        <span className="flex flex-wrap items-center justify-end gap-1.5 text-[0.68rem] font-bold text-faint">
          <span className={failed ? "text-danger" : undefined}>{status}</span>
          {message.ai_error ? <span className="text-danger">Reply unavailable</span> : null}
          <span>{formatRelativeTime(message.created_at)}</span>
          {isHuman && delivered ? (
            <span className="font-black tracking-[-0.12em] text-accent" aria-label="delivered">
              ✓✓
            </span>
          ) : null}
        </span>
        {failed && (message.ai_error || message.delivery_error || message.ai_run_id) ? (
          <details className="text-[0.68rem] text-muted [overflow-wrap:anywhere]">
            <summary className="cursor-pointer">Details</summary>
            {message.ai_error || message.delivery_error ? <p className="my-1">{message.ai_error ?? message.delivery_error}</p> : null}
            {message.ai_run_id ? <p className="my-1">AI run {message.ai_run_id} ({message.ai_run_state})</p> : null}
          </details>
        ) : null}
      </article>
    </div>
  );
}

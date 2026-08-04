import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { SocialApiClient, SocialApiError } from "../lib/api";
import type { AgentChatMessage, AgentProfile, LoopState } from "../lib/social";
import { formatRelativeTime } from "../lib/state";
import { GullAvatar, Wing, YOUR_WING, statusDotColor, wingFor } from "@seagulls/ui";
import { Chip, EmptyState, shortHandle, shortId, type Notice } from "./shared";

type AppMutationError = Error | SocialApiError;

export function ChatPage({
  api,
  state,
  profiles,
  onNotice,
}: {
  api: SocialApiClient;
  state: LoopState;
  profiles: AgentProfile[];
  onNotice: (notice: Notice) => void;
}) {
  const navigate = useNavigate();
  const params = useParams();
  const queryClient = useQueryClient();
  const threadRef = useRef<HTMLDivElement | null>(null);
  const [picking, setPicking] = useState(false);
  const [draft, setDraft] = useState("");
  const [flying, setFlying] = useState(false);

  const ownerUserId = state.activeUser?.user_id ?? null;
  const selectedChatId = params.chatId ?? null;

  const chatsQuery = useQuery({
    queryKey: ["social-agent-chats", api.baseUrl, ownerUserId],
    queryFn: () => api.getAgentChats(ownerUserId ?? undefined),
    enabled: Boolean(ownerUserId),
  });
  const chats = chatsQuery.data?.items ?? [];
  const selectedChat =
    chats.find((chat) => chat.chat_id === selectedChatId) ?? (selectedChatId ? null : chats[0] ?? null);

  useEffect(() => {
    if (picking || chats.length === 0) {
      return;
    }
    // Only auto-select when no chat is addressed. A chatId that is missing from
    // the cached list may be a freshly created chat whose refetch is still in
    // flight — redirecting away from it would open the wrong thread.
    if (!selectedChatId) {
      navigate(`/chat/${chats[0].chat_id}`, { replace: true });
    }
  }, [chats, navigate, picking, selectedChatId]);

  const messagesQuery = useQuery({
    queryKey: ["social-agent-chat-messages", api.baseUrl, ownerUserId, selectedChat?.chat_id],
    queryFn: () => api.getAgentChatMessages(selectedChat!.chat_id, ownerUserId ?? undefined),
    enabled: Boolean(ownerUserId && selectedChat),
  });
  const messages = messagesQuery.data?.items ?? [];

  function scrollThread() {
    const element = threadRef.current;
    if (element) {
      element.scrollTop = element.scrollHeight;
    }
  }

  useEffect(() => {
    setDraft("");
    scrollThread();
  }, [selectedChat?.chat_id]);

  useEffect(() => {
    scrollThread();
  }, [messages.length]);

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
    mutationFn: async ({ chatId, content }: { chatId: string; content: string }) => {
      if (!ownerUserId) {
        throw new Error("Select a chat before sending.");
      }
      return api.createAgentChatMessage(chatId, { owner_user_id: ownerUserId, content });
    },
    onSuccess: ({ message, reply }, variables) => {
      if (selectedChat?.chat_id === variables.chatId) {
        setDraft("");
        setFlying(true);
        window.setTimeout(() => setFlying(false), 950);
        window.setTimeout(scrollThread, 0);
      }
      void queryClient.invalidateQueries({ queryKey: ["social-agent-chats"] });
      void queryClient.invalidateQueries({ queryKey: ["social-agent-chat-messages"] });
      const failed = message.delivery_status === "delivery_failed" || Boolean(message.ai_error);
      if (failed) {
        onNotice({
          tone: "warn",
          message: message.ai_error ? "Message stored; AI reply failed." : "Message stored; delivery failed.",
        });
      }
      void reply;
    },
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  function submitDraft(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const text = draft.trim();
    if (text && !sendMutation.isPending && selectedChat) {
      sendMutation.mutate({ chatId: selectedChat.chat_id, content: text });
    }
  }

  function onDraftKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submitDraft();
    }
  }

  function chatSnippet(chatId: string, fallback: string): string {
    const cached = queryClient.getQueryData<{ items: AgentChatMessage[] }>([
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
  const showPicker = picking || (!selectedChat && !chatsQuery.isFetching);

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
          onClick={() => setPicking(true)}
          className="min-h-9 rounded-lg border-0 bg-accent px-3.5 text-[0.84rem] font-extrabold text-white hover:bg-accent-strong"
        >
          New chat
        </button>
      </header>

      <div className="grid h-[calc(100vh-190px)] min-h-[460px] grid-cols-[264px_minmax(0,1fr)] overflow-hidden rounded-xl border border-line bg-card max-[860px]:grid-cols-1 max-[860px]:h-auto">
        <div className="overflow-y-auto border-r border-line max-[860px]:max-h-52 max-[860px]:border-r-0 max-[860px]:border-b">
          {chats.length === 0 ? (
            <EmptyState title="No chats yet" detail="Start one — your gulls are listening." />
          ) : (
            chats.map((chat) => {
              const active = selectedChat?.chat_id === chat.chat_id && !picking;
              return (
                <button
                  key={chat.chat_id}
                  type="button"
                  onClick={() => {
                    setPicking(false);
                    navigate(`/chat/${chat.chat_id}`);
                  }}
                  className={`flex w-full items-start gap-2.5 border-0 border-b border-line px-4 py-3.5 text-left text-ink hover:bg-accent-soft ${
                    active ? "bg-accent-soft" : "bg-transparent"
                  }`}
                >
                  <GullAvatar handle={chat.agent_handle} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline gap-2">
                      <strong className="overflow-hidden text-[0.9rem] text-ellipsis whitespace-nowrap">
                        {chat.title}
                      </strong>
                      <span className="ml-auto flex-none text-[0.7rem] font-extrabold text-faint">
                        {formatRelativeTime(chat.updated_at)}
                      </span>
                    </span>
                    <span className="mt-0.5 block overflow-hidden text-[0.8rem] text-ellipsis whitespace-nowrap text-muted">
                      {chatSnippet(chat.chat_id, shortHandle(chat.agent_handle))}
                    </span>
                  </span>
                </button>
              );
            })
          )}
        </div>

        {showPicker ? (
          <div className="grid place-content-center justify-items-center gap-[22px] bg-bg p-[30px]">
            <p className="m-0 font-extrabold text-muted">Who do you want to talk to?</p>
            {profiles.length === 0 ? (
              <EmptyState title="No gulls yet" detail="Register a gull in the Flock first." />
            ) : (
              <div className="flex flex-wrap justify-center gap-3.5">
                {profiles.map((profile) => (
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
        ) : selectedChat ? (
          <div className="grid grid-rows-[auto_minmax(0,1fr)_auto]">
            <div className="flex items-center gap-3 border-b border-line px-5 py-3">
              <GullAvatar
                handle={selectedChat.agent_handle}
                size={34}
                animation={sendMutation.isPending ? "gull-flap 0.4s ease-in-out infinite" : undefined}
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
                </span>
              </span>
              <span className="ml-auto flex flex-wrap justify-end gap-1.5">
                {(chatAgent?.capabilities ?? []).slice(0, 3).map((capability) => (
                  <Chip key={capability}>{capability}</Chip>
                ))}
              </span>
            </div>

            <div ref={threadRef} aria-live="polite" className="grid content-start gap-2.5 overflow-y-auto bg-bg px-[22px] py-5">
              {messagesQuery.isFetching && messages.length === 0 ? (
                <EmptyState title="Opening the thread" detail="Fetching stored messages." />
              ) : messages.length === 0 ? (
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
                  rows={1}
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={onDraftKey}
                  placeholder={`Message ${shortHandle(selectedChat.agent_handle)}…`}
                  aria-label="Message"
                  className="box-border max-h-[140px] min-h-[44px] flex-1 resize-none border-0 bg-transparent px-1 py-[11px] text-base leading-[1.45]"
                />
                {draft.trim() ? (
                  <span
                    aria-hidden="true"
                    className="inline-flex pr-1 pb-[13px] text-[0.76rem] font-extrabold whitespace-nowrap text-accent"
                  >
                    ⏎ Enter
                  </span>
                ) : null}
              </div>
              <div className="flex items-center gap-1.5 px-1.5 pb-1.5">
                <Chip tone={selectedChat.prompt_asset_id ? "accent" : "faint"}>
                  Prompt {shortId(selectedChat.prompt_asset_id)}
                </Chip>
                <Chip tone={selectedChat.skill_asset_id ? "accent" : "faint"}>
                  Skill {shortId(selectedChat.skill_asset_id)}
                </Chip>
                {selectedChat.hub_thread_id ? <Chip>Thread {shortId(selectedChat.hub_thread_id)}</Chip> : null}
                <span className="flex-1" />
                <span className="text-[0.72rem] font-extrabold text-faint">snapshots travel with the message</span>
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
  const failed = message.delivery_status === "delivery_failed" || Boolean(message.ai_error);
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
        <span className="leading-[1.45] text-body [overflow-wrap:anywhere]">{message.content}</span>
        <span className="flex flex-wrap items-center justify-end gap-1.5 text-[0.68rem] font-bold text-faint">
          {message.ai_run_id ? (
            <span>
              AI run {message.ai_run_id}
              {message.ai_run_state ? ` (${message.ai_run_state})` : ""}
            </span>
          ) : null}
          {failed ? (
            <span className="font-extrabold text-danger">{message.ai_error ?? message.delivery_error ?? "failed"}</span>
          ) : null}
          <span>{message.delivery_status}</span>
          <span>{formatRelativeTime(message.created_at)}</span>
          {isHuman && delivered ? (
            <span className="font-black tracking-[-0.12em] text-accent" aria-label="delivered">
              ✓✓
            </span>
          ) : null}
        </span>
      </article>
    </div>
  );
}

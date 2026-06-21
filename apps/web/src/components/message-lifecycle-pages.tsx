import {
  ExternalLink,
  GitBranch,
  Inbox,
  Play,
  Plus,
  Reply,
  Route,
  ShieldQuestion,
  X,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { AgentProfile } from "../lib/social";
import {
  MessageHubClient,
  MessageHubError,
  type HubDelivery,
  type InboxItem,
  type MessageRef,
  type RoutingRule,
  type SendMessageResult,
  type WorkflowTraceEntry,
} from "../lib/message-hub";
import { formatTimestamp, parseCommaList } from "../lib/state";
import { EmptyRoute, EmptyState, type Notice } from "./shared";

type LifecycleError = Error | MessageHubError;

export function AgentLifecycleInboxPage({
  messageApi,
  profiles,
  activeProfile,
  onNotice,
}: {
  messageApi: MessageHubClient;
  profiles: AgentProfile[];
  activeProfile: AgentProfile | null;
  onNotice: (notice: Notice) => void;
}) {
  const queryClient = useQueryClient();
  const defaultHandle = activeProfile?.handle ?? profiles[0]?.handle ?? "";
  const [handle, setHandle] = useState(defaultHandle);
  const [recipientHandle, setRecipientHandle] = useState(
    profiles.find((profile) => profile.handle !== defaultHandle)?.handle ?? "",
  );
  const [messageText, setMessageText] = useState("");
  const [refUrl, setRefUrl] = useState("");
  const [find, setFind] = useState("");

  useEffect(() => {
    if (!handle && defaultHandle) {
      setHandle(defaultHandle);
    }
  }, [defaultHandle, handle]);

  const selectedProfile = profiles.find((profile) => profile.handle === handle) ?? null;
  const capabilities = selectedProfile?.capabilities ?? [];

  const inboxQuery = useQuery({
    queryKey: ["message-inbox", messageApi.baseUrl, handle],
    queryFn: () => messageApi.getInbox(handle, 20),
    enabled: Boolean(handle),
    retry: false,
  });

  const registerMutation = useMutation({
    mutationFn: () =>
      messageApi.registerAgent({
        handle,
        display_name: selectedProfile?.display_name ?? undefined,
        capabilities,
      }),
    onSuccess: () => {
      onNotice({ tone: "ok", message: "Agent registered with message hub." });
      void inboxQuery.refetch();
    },
    onError: (error: LifecycleError) => onNotice({ tone: "error", message: error.message }),
  });

  const sendMutation = useMutation({
    mutationFn: async () => {
      const normalizedSender = handle.trim();
      const normalizedRecipient = recipientHandle.trim();
      await ensureHubAgent(messageApi, normalizedSender, profiles);
      await ensureHubAgent(messageApi, normalizedRecipient, profiles);
      return messageApi.createMessage({
        sender_handle: normalizedSender,
        recipient_handles: [normalizedRecipient],
        content: messageText.trim(),
        refs: refUrl.trim()
          ? [
              {
                type: "url",
                url: refUrl.trim(),
                find: find.trim() || undefined,
              },
            ]
          : [],
      });
    },
    onSuccess: (result: SendMessageResult) => {
      setMessageText("");
      setRefUrl("");
      setFind("");
      onNotice({ tone: "ok", message: `${result.deliveries.length} delivery created.` });
      void queryClient.invalidateQueries({ queryKey: ["message-inbox"] });
    },
    onError: (error: LifecycleError) => onNotice({ tone: "error", message: error.message }),
  });

  if (!handle && profiles.length === 0) {
    return <EmptyRoute title="No agent handle" detail="Create a social agent first." />;
  }

  const items = inboxQuery.data?.items ?? [];
  const notRegistered = inboxQuery.error instanceof MessageHubError && inboxQuery.error.status === 404;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_360px] items-start gap-4 max-[1100px]:grid-cols-1">
      <section className="min-w-0 rounded-lg border border-line bg-surface shadow-panel">
        <div className="flex items-start justify-between gap-3.5 border-b border-line p-[18px] max-[620px]:grid">
          <div>
            <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">Agent inbox</p>
            <h2 className="m-0 text-xl tracking-normal">Lifecycle deliveries</h2>
          </div>
          <div className="flex min-w-[min(100%,420px)] gap-2 max-[620px]:min-w-0 max-[620px]:grid">
            <select
              className="min-h-10 flex-1"
              value={handle}
              onChange={(event) => setHandle(event.target.value)}
              aria-label="Agent handle"
            >
              {profiles.map((profile) => (
                <option key={profile.agent_id} value={profile.handle}>
                  {profile.display_name ?? profile.handle}
                </option>
              ))}
              {handle && !profiles.some((profile) => profile.handle === handle) ? (
                <option value={handle}>{handle}</option>
              ) : null}
            </select>
            <button
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3.5 font-extrabold text-ink disabled:cursor-not-allowed disabled:opacity-[0.58]"
              type="button"
              onClick={() => registerMutation.mutate()}
              disabled={!handle.trim() || registerMutation.isPending}
            >
              <Plus size={16} />
              Register
            </button>
          </div>
        </div>

        {notRegistered ? (
          <EmptyState title="Agent not registered" detail="Register this handle with the message hub." />
        ) : inboxQuery.isFetching ? (
          <EmptyState title="Loading inbox" detail="Checking message hub deliveries." />
        ) : items.length === 0 ? (
          <EmptyState title="No deliveries" detail="New lifecycle messages will appear here." />
        ) : (
          <div className="grid">
            {items.map((item) => (
              <DeliveryCard
                item={item}
                agentHandle={handle}
                messageApi={messageApi}
                onNotice={onNotice}
                onChanged={() => {
                  void inboxQuery.refetch();
                }}
                key={item.delivery.delivery_id}
              />
            ))}
          </div>
        )}
      </section>

      <aside className="grid gap-4">
        <section className="min-w-0 rounded-lg border border-line bg-surface shadow-panel">
          <div className="border-b border-line p-[18px]">
            <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">Composer</p>
            <h2 className="m-0 text-xl tracking-normal">Lifecycle message</h2>
          </div>
          <form
            className="grid gap-3 p-[18px]"
            onSubmit={(event) => {
              event.preventDefault();
              if (handle.trim() && recipientHandle.trim() && (messageText.trim() || refUrl.trim())) {
                sendMutation.mutate();
              }
            }}
          >
            <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
              Sender
              <input value={handle} onChange={(event) => setHandle(event.target.value)} spellCheck={false} />
            </label>
            <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
              Recipient
              <input
                value={recipientHandle}
                onChange={(event) => setRecipientHandle(event.target.value)}
                list="message-recipient-handles"
                spellCheck={false}
              />
            </label>
            <datalist id="message-recipient-handles">
              {profiles.map((profile) => (
                <option value={profile.handle} key={profile.agent_id} />
              ))}
            </datalist>
            <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
              Text
              <textarea value={messageText} onChange={(event) => setMessageText(event.target.value)} rows={4} />
            </label>
            <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
              URL ref
              <input value={refUrl} onChange={(event) => setRefUrl(event.target.value)} spellCheck={false} />
            </label>
            <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
              Find
              <input value={find} onChange={(event) => setFind(event.target.value)} spellCheck={false} />
            </label>
            <button
              className="inline-flex min-h-10 w-fit items-center justify-center gap-2 rounded-lg border-0 bg-accent px-3.5 font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58]"
              type="submit"
              disabled={!handle.trim() || !recipientHandle.trim() || (!messageText.trim() && !refUrl.trim()) || sendMutation.isPending}
            >
              <Play size={16} />
              Send
            </button>
          </form>
        </section>
      </aside>
    </div>
  );
}

function DeliveryCard({
  item,
  agentHandle,
  messageApi,
  onNotice,
  onChanged,
}: {
  item: InboxItem;
  agentHandle: string;
  messageApi: MessageHubClient;
  onNotice: (notice: Notice) => void;
  onChanged: () => void;
}) {
  const [preparedText, setPreparedText] = useState(item.current_message?.content_inline ?? item.message.content_inline ?? "");
  const [replyText, setReplyText] = useState("");
  const [actionTarget, setActionTarget] = useState(item.current_message?.refs?.[0]?.url ?? item.message.refs?.[0]?.url ?? "");
  const refs = item.current_message?.refs?.length ? item.current_message.refs : item.message.refs ?? [];

  const hookMutation = useMutation({
    mutationFn: () =>
      messageApi.submitHookResult(item.delivery.delivery_id, {
        hook: "receive.before",
        runtime: "cloud_node",
        actor: agentHandle,
        content: preparedText,
      }),
    onSuccess: () => {
      onNotice({ tone: "ok", message: "Hook result saved." });
      onChanged();
    },
    onError: (error: LifecycleError) => onNotice({ tone: "error", message: error.message }),
  });

  const decisionMutation = useMutation({
    mutationFn: (decision: "reply" | "action" | "ignore" | "ask_human") => {
      if (decision === "reply") {
        return messageApi.submitDecision(item.delivery.delivery_id, {
          agent_handle: agentHandle,
          decision,
          content: replyText,
        });
      }
      if (decision === "action") {
        return messageApi.submitDecision(item.delivery.delivery_id, {
          agent_handle: agentHandle,
          decision,
          action_type: "open_url",
          action_target: actionTarget,
          action_runtime: "cloud_node",
        });
      }
      return messageApi.submitDecision(item.delivery.delivery_id, {
        agent_handle: agentHandle,
        decision,
      });
    },
    onSuccess: (_, decision) => {
      if (decision === "reply") {
        setReplyText("");
      }
      onNotice({ tone: "ok", message: `Delivery marked ${decision}.` });
      onChanged();
    },
    onError: (error: LifecycleError) => onNotice({ tone: "error", message: error.message }),
  });

  return (
    <article className="grid gap-3 border-b border-line bg-white p-[18px] last:border-b-0">
      <div className="flex items-start justify-between gap-3 max-[620px]:grid">
        <div className="min-w-0">
          <strong className="block overflow-hidden text-ellipsis whitespace-nowrap">
            {item.delivery.sender_handle ?? item.message.sender_agent_id}
          </strong>
          <span className="block overflow-hidden text-ellipsis whitespace-nowrap text-[0.8rem] text-muted">
            {item.delivery.status} / {item.delivery.current_stage ?? "agent.wait"} / {formatTimestamp(item.delivery.created_at)}
          </span>
        </div>
        <span className="rounded-full bg-surface-soft px-2 py-1 text-xs font-extrabold text-muted">
          {item.message.intent}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 max-[760px]:grid-cols-1">
        <MessagePanel title="Original" text={item.message.content_inline} refs={item.message.refs ?? []} />
        <MessagePanel title="Current" text={item.current_message?.content_inline} refs={refs} />
      </div>

      <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
        Prepared text
        <textarea value={preparedText} onChange={(event) => setPreparedText(event.target.value)} rows={3} />
      </label>

      <div className="flex flex-wrap gap-2">
        <button
          className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 font-extrabold text-ink disabled:cursor-not-allowed disabled:opacity-[0.58]"
          type="button"
          onClick={() => hookMutation.mutate()}
          disabled={!preparedText.trim() || hookMutation.isPending}
        >
          <GitBranch size={15} />
          Apply hook
        </button>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-3 max-[760px]:grid-cols-1">
        <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
          Reply
          <textarea value={replyText} onChange={(event) => setReplyText(event.target.value)} rows={3} />
        </label>
        <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
          Action target
          <input value={actionTarget} onChange={(event) => setActionTarget(event.target.value)} spellCheck={false} />
        </label>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border-0 bg-accent px-3 font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58]"
          type="button"
          onClick={() => decisionMutation.mutate("reply")}
          disabled={!replyText.trim() || decisionMutation.isPending}
        >
          <Reply size={15} />
          Reply
        </button>
        <button
          className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 font-extrabold text-ink disabled:cursor-not-allowed disabled:opacity-[0.58]"
          type="button"
          onClick={() => decisionMutation.mutate("action")}
          disabled={!actionTarget.trim() || decisionMutation.isPending}
        >
          <ExternalLink size={15} />
          Action
        </button>
        <button
          className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 font-extrabold text-ink disabled:cursor-not-allowed disabled:opacity-[0.58]"
          type="button"
          onClick={() => decisionMutation.mutate("ask_human")}
          disabled={decisionMutation.isPending}
        >
          <ShieldQuestion size={15} />
          Ask human
        </button>
        <button
          className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3 font-extrabold text-ink disabled:cursor-not-allowed disabled:opacity-[0.58]"
          type="button"
          onClick={() => decisionMutation.mutate("ignore")}
          disabled={decisionMutation.isPending}
        >
          <X size={15} />
          Ignore
        </button>
      </div>

      <TraceList trace={item.delivery.workflow_trace ?? []} />
    </article>
  );
}

function MessagePanel({ title, text, refs }: { title: string; text?: string; refs: MessageRef[] }) {
  return (
    <div className="grid gap-2 rounded-lg border border-line bg-[#fbfcfb] p-3">
      <span className="text-xs font-extrabold uppercase tracking-normal text-muted">{title}</span>
      <p className="m-0 min-h-10 text-sm leading-normal text-ink [overflow-wrap:anywhere]">{text || "No text"}</p>
      {refs.length > 0 ? (
        <div className="grid gap-1">
          {refs.map((ref, index) => (
            <div className="rounded-lg bg-white px-2.5 py-2 text-xs text-muted [overflow-wrap:anywhere]" key={`${ref.url ?? ref.type}-${index}`}>
              <strong className="text-ink">{ref.type}</strong>
              {ref.url ? <span> {ref.url}</span> : null}
              {ref.find ? <span> / {ref.find}</span> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function TraceList({ trace }: { trace: WorkflowTraceEntry[] }) {
  if (trace.length === 0) {
    return null;
  }
  return (
    <div className="grid gap-1.5 rounded-lg border border-line bg-[#fbfcfb] p-3">
      <span className="text-xs font-extrabold uppercase tracking-normal text-muted">Trace</span>
      {trace.map((entry, index) => (
        <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 text-xs" key={`${entry.hook}-${entry.created_at}-${index}`}>
          <span className="overflow-hidden text-ellipsis whitespace-nowrap">
            <strong>{entry.hook}</strong> / {entry.runtime} / {entry.action}
          </span>
          <span className="text-muted">{formatTimestamp(entry.created_at)}</span>
        </div>
      ))}
    </div>
  );
}

export function RoutingRulesPage({
  messageApi,
  profiles,
  onNotice,
}: {
  messageApi: MessageHubClient;
  profiles: AgentProfile[];
  onNotice: (notice: Notice) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("Map links");
  const [mode, setMode] = useState("copy");
  const [routeToHandle, setRouteToHandle] = useState(profiles[0]?.handle ?? "");
  const [urlContains, setUrlContains] = useState("maps.google.com");

  useEffect(() => {
    if (!routeToHandle && profiles[0]?.handle) {
      setRouteToHandle(profiles[0].handle);
    }
  }, [profiles, routeToHandle]);

  const rulesQuery = useQuery({
    queryKey: ["message-routing-rules", messageApi.baseUrl],
    queryFn: () => messageApi.listRoutingRules(),
  });

  const createMutation = useMutation({
    mutationFn: async () => {
      const handles = mode === "block" ? [] : [routeToHandle.trim()].filter(Boolean);
      for (const handle of handles) {
        await ensureHubAgent(messageApi, handle, profiles);
      }
      return messageApi.createRoutingRule({
        name: name.trim(),
        mode,
        route_to_handles: handles,
        url_contains: parseCommaList(urlContains.toLowerCase()),
      });
    },
    onSuccess: () => {
      onNotice({ tone: "ok", message: "Routing rule created." });
      void queryClient.invalidateQueries({ queryKey: ["message-routing-rules"] });
    },
    onError: (error: LifecycleError) => onNotice({ tone: "error", message: error.message }),
  });

  const rules = rulesQuery.data?.items ?? [];

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_360px] items-start gap-4 max-[980px]:grid-cols-1">
      <section className="min-w-0 rounded-lg border border-line bg-surface shadow-panel">
        <div className="flex items-start justify-between gap-3.5 border-b border-line p-[18px]">
          <div>
            <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">Routing</p>
            <h2 className="m-0 text-xl tracking-normal">Message rules</h2>
          </div>
          <Route size={20} className="text-accent-strong" />
        </div>
        {rulesQuery.isFetching ? (
          <EmptyState title="Loading rules" detail="Checking message hub routing." />
        ) : rules.length === 0 ? (
          <EmptyState title="No routing rules" detail="Rules route matching refs to selected agents." />
        ) : (
          <div className="grid">
            {rules.map((rule) => (
              <RoutingRuleRow rule={rule} key={rule.rule_id} />
            ))}
          </div>
        )}
      </section>

      <aside className="min-w-0 rounded-lg border border-line bg-surface shadow-panel">
        <div className="border-b border-line p-[18px]">
          <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">New rule</p>
          <h2 className="m-0 text-xl tracking-normal">URL routing</h2>
        </div>
        <form className="grid gap-3 p-[18px]" onSubmit={(event: FormEvent<HTMLFormElement>) => {
          event.preventDefault();
          if (name.trim() && urlContains.trim() && (mode === "block" || routeToHandle.trim())) {
            createMutation.mutate();
          }
        }}>
          <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
            Name
            <input value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
            Mode
            <select value={mode} onChange={(event) => setMode(event.target.value)}>
              <option value="copy">copy</option>
              <option value="handoff">handoff</option>
              <option value="review">review</option>
              <option value="direct">direct</option>
              <option value="block">block</option>
            </select>
          </label>
          <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
            Route to
            <input
              value={routeToHandle}
              onChange={(event) => setRouteToHandle(event.target.value)}
              list="routing-agent-handles"
              disabled={mode === "block"}
              spellCheck={false}
            />
          </label>
          <datalist id="routing-agent-handles">
            {profiles.map((profile) => (
              <option value={profile.handle} key={profile.agent_id} />
            ))}
          </datalist>
          <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
            URL contains
            <input value={urlContains} onChange={(event) => setUrlContains(event.target.value)} spellCheck={false} />
          </label>
          <button
            className="inline-flex min-h-10 w-fit items-center justify-center gap-2 rounded-lg border-0 bg-accent px-3.5 font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58]"
            type="submit"
            disabled={!name.trim() || !urlContains.trim() || (mode !== "block" && !routeToHandle.trim()) || createMutation.isPending}
          >
            <Plus size={16} />
            Create
          </button>
        </form>
      </aside>
    </div>
  );
}

function RoutingRuleRow({ rule }: { rule: RoutingRule }) {
  return (
    <article className="grid grid-cols-[auto_minmax(0,1fr)_auto] gap-3 border-b border-line bg-white p-[18px] last:border-b-0 max-[620px]:grid-cols-[auto_minmax(0,1fr)]">
      <span className="grid h-9 w-9 place-items-center rounded-lg bg-surface-soft text-accent-strong">
        <Route size={16} />
      </span>
      <div className="min-w-0">
        <strong className="block overflow-hidden text-ellipsis whitespace-nowrap">{rule.name}</strong>
        <span className="block overflow-hidden text-ellipsis whitespace-nowrap text-[0.8rem] text-muted">
          {rule.url_contains.join(", ")} / {rule.route_to_handles.join(", ") || "none"}
        </span>
      </div>
      <span className="rounded-full bg-surface-soft px-2 py-1 text-xs font-extrabold text-muted max-[620px]:col-start-2">
        {rule.mode}
      </span>
    </article>
  );
}

async function ensureHubAgent(messageApi: MessageHubClient, handle: string, profiles: AgentProfile[]) {
  if (!handle) {
    return;
  }
  const profile = profiles.find((item) => item.handle === handle);
  await messageApi.registerAgent({
    handle,
    display_name: profile?.display_name ?? undefined,
    capabilities: profile?.capabilities ?? [],
  });
}

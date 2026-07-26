import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { MessageHubClient, type HubTask, type TaskRole } from "../lib/message-hub";
import type { AgentProfile } from "../lib/social";
import { Chip, displayLabel, shortHandle, type Notice } from "./shared";

/**
 * Work: the Agent Request surface.
 *
 * Agent Request is a sibling product layer over gulls, not a second transport.
 * Requests, their state, and their results are durable gulls records; this page
 * reads them through the hub's per-agent task route and presents them as a
 * queue.
 */

const ROLE_TABS: Array<[TaskRole, string, string]> = [
  ["all", "All", "Every request this agent is part of"],
  ["requester", "Asked for", "Work this agent asked someone else to do"],
  ["worker", "Asked of", "Work someone else asked this agent to do"],
];

/** Terminal states, mirroring TASK_INACTIVE_STATES in the protocol. */
const FINISHED = new Set(["released", "completed", "canceled", "refused", "failed"]);
const NEEDS_ATTENTION = new Set(["needs_approval", "quoted", "result_ready", "disputed"]);

function stateTone(state: string): "neutral" | "accent" | "indigo" | "amber" | "faint" {
  if (NEEDS_ATTENTION.has(state)) return "amber";
  if (state === "failed" || state === "disputed") return "amber";
  if (FINISHED.has(state)) return "faint";
  if (state === "running" || state === "accepted") return "accent";
  return "indigo";
}

function stateLabel(state: string): string {
  return state.replace(/_/g, " ");
}

function formatWhen(value: string | null): string {
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "" : parsed.toLocaleString();
}

export function WorkPage({
  messageApi,
  profiles,
  onNotice,
}: {
  messageApi: MessageHubClient;
  profiles: AgentProfile[];
  onNotice: (notice: Notice) => void;
}) {
  const [selectedHandle, setSelectedHandle] = useState<string | null>(null);
  const [role, setRole] = useState<TaskRole>("all");

  // Default to the first agent the human owns, without stranding the selection
  // if that agent later disappears.
  const activeHandle = useMemo(() => {
    if (selectedHandle && profiles.some((profile) => profile.handle === selectedHandle)) {
      return selectedHandle;
    }
    return profiles[0]?.handle ?? null;
  }, [profiles, selectedHandle]);

  const tasksQuery = useQuery({
    queryKey: ["hub-agent-tasks", messageApi.baseUrl, activeHandle, role],
    queryFn: () => messageApi.getAgentTasks(activeHandle as string, role),
    enabled: Boolean(activeHandle),
    staleTime: 10_000,
    retry: false,
  });

  const tasks: HubTask[] = tasksQuery.data?.tasks ?? [];
  const open = tasks.filter((task) => !FINISHED.has(task.state));
  const finished = tasks.filter((task) => FINISHED.has(task.state));

  if (profiles.length === 0) {
    return (
      <section>
        <h2 className="text-xl font-black">Work</h2>
        <p className="mt-2 text-sm text-muted">
          Requests and delegated work appear here. Create an agent in Flock first.
        </p>
      </section>
    );
  }

  return (
    <section>
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h2 className="text-xl font-black">Work</h2>
          <p className="mt-1 text-sm text-muted">
            Requests carried over the shared network. Task state, results, and audit stay
            durable records.
          </p>
        </div>
      </header>

      <div className="mt-4 flex flex-wrap gap-2">
        {profiles.map((profile) => (
          <button
            key={profile.agent_id}
            type="button"
            onClick={() => setSelectedHandle(profile.handle)}
            className={`rounded-lg px-3 py-1.5 text-sm font-bold ${
              profile.handle === activeHandle
                ? "bg-accent-soft text-accent-strong"
                : "bg-surface-muted text-muted"
            }`}
            aria-pressed={profile.handle === activeHandle}
          >
            {displayLabel(profile)}
          </button>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {ROLE_TABS.map(([value, label, description]) => (
          <button
            key={value}
            type="button"
            title={description}
            onClick={() => setRole(value)}
            className={`rounded-lg px-3 py-1.5 text-sm font-bold ${
              value === role ? "bg-accent-soft text-accent-strong" : "bg-surface-muted text-muted"
            }`}
            aria-pressed={value === role}
          >
            {label}
          </button>
        ))}
      </div>

      {tasksQuery.isLoading ? (
        <p className="mt-6 text-sm text-muted">Loading requests…</p>
      ) : tasksQuery.isError ? (
        <ErrorNotice error={tasksQuery.error} onNotice={onNotice} />
      ) : tasks.length === 0 ? (
        <p className="mt-6 text-sm text-muted">
          No requests yet for {activeHandle ? shortHandle(activeHandle) : "this agent"}.
        </p>
      ) : (
        <>
          <TaskList title={`Open (${open.length})`} tasks={open} emptyLabel="Nothing open." />
          {finished.length > 0 ? (
            <TaskList title={`Finished (${finished.length})`} tasks={finished} emptyLabel="" />
          ) : null}
        </>
      )}
    </section>
  );
}

function TaskList({
  title,
  tasks,
  emptyLabel,
}: {
  title: string;
  tasks: HubTask[];
  emptyLabel: string;
}) {
  return (
    <div className="mt-6">
      <h3 className="text-sm font-black uppercase tracking-wide text-muted">{title}</h3>
      {tasks.length === 0 ? (
        emptyLabel ? <p className="mt-2 text-sm text-muted">{emptyLabel}</p> : null
      ) : (
        <ul className="mt-2 flex flex-col gap-2">
          {tasks.map((task) => (
            <li
              key={task.task_id}
              className="rounded-lg bg-surface-muted px-3.5 py-3"
              data-testid="work-task"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-bold [overflow-wrap:anywhere]">{task.objective}</span>
                <Chip tone={stateTone(task.state)}>{stateLabel(task.state)}</Chip>
              </div>
              <p className="mt-1 text-xs text-muted">
                {formatWhen(task.updated_at ?? task.created_at)}
                {task.result_ref || task.artifact_refs.length > 0 ? " · has results" : ""}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ErrorNotice({
  error,
  onNotice,
}: {
  error: unknown;
  onNotice: (notice: Notice) => void;
}) {
  const message = error instanceof Error ? error.message : "Could not load requests.";
  return (
    <div className="mt-6">
      <p className="text-sm text-muted">{message}</p>
      <button
        type="button"
        className="mt-2 text-sm font-bold text-accent-strong"
        onClick={() => onNotice({ tone: "warn", message })}
      >
        Report this
      </button>
    </div>
  );
}

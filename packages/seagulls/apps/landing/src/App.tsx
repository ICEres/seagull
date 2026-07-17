import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import { landingDemoProviderResponse } from "./lib/demo";
import { AGENTS, AMBIENT_GULLS, gullPath } from "./lib/gulls";

const THEME_KEY = "seagulls-theme";

const PAUSED_RESPONSE =
  "Provider delivery is paused for this run, so the message stays available for manual or connector handling with its asset snapshot attached.";

type Role = "user" | "agent" | "system";

type ChatMessage = {
  id: number;
  role: Role;
  text: string;
  time: string;
  delivered: boolean;
  pending: boolean;
};

function GullIcon({ size, strokeWidth }: { size: number; strokeWidth: number }) {
  return (
    <svg width={size} viewBox="0 0 32 14" fill="none">
      <path
        d={gullPath}
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function initialDark(): boolean {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved) {
      return saved === "dark";
    }
    return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return document.documentElement.classList.contains("dark");
  }
}

function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function now(): string {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function App() {
  const [dark, setDark] = useState(initialDark);
  const [recipient, setRecipient] = useState(AGENTS[0].handle);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [carryingHandle, setCarryingHandle] = useState<string | null>(null);
  const [promptOn, setPromptOn] = useState(true);
  const [skillOn, setSkillOn] = useState(true);
  const [providerOn, setProviderOn] = useState(true);
  const [continueVisible, setContinueVisible] = useState(false);

  const skyRef = useRef<HTMLDivElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLFormElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const sendingRef = useRef(false);
  const idRef = useRef(0);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  useEffect(() => {
    document.body.classList.toggle("sending", sending);
    return () => {
      document.body.classList.remove("sending");
    };
  }, [sending]);

  useEffect(() => {
    const thread = threadRef.current;
    if (thread) {
      thread.scrollTop = thread.scrollHeight;
    }
  }, [messages]);

  useLayoutEffect(() => {
    const input = inputRef.current;
    if (input) {
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 180) + "px";
    }
  }, [draft]);

  function nextId(): number {
    idRef.current += 1;
    return idRef.current;
  }

  function toggleTheme() {
    const next = !dark;
    setDark(next);
    try {
      localStorage.setItem(THEME_KEY, next ? "dark" : "light");
    } catch {
      /* theme still applies for this visit */
    }
  }

  function pickRecipient(handle: string) {
    setRecipient(handle);
    inputRef.current?.focus();
  }

  // The dot's start position depends on the post-send layout (hero hidden,
  // thread visible), so the flight launches from a layout effect after the
  // send commit rather than from the submit handler.
  useLayoutEffect(() => {
    if (carryingHandle) {
      launchFlight(carryingHandle);
    }
  }, [carryingHandle]);

  function launchFlight(handle: string) {
    if (prefersReducedMotion()) {
      return;
    }
    const sky = skyRef.current;
    const composer = composerRef.current;
    const target = sky?.querySelector('.gull[data-handle="' + handle + '"]');
    if (!sky || !composer || !target) {
      return;
    }
    const from = composer.getBoundingClientRect();
    const to = target.getBoundingClientRect();
    const dot = document.createElement("span");
    dot.className = "flight";
    dot.style.transform = "translate(" + (from.right - 44) + "px, " + (from.top - 8) + "px)";
    dot.style.opacity = "1";
    sky.appendChild(dot);
    window.setTimeout(() => {
      dot.style.transition = "transform 0.95s cubic-bezier(0.35, 0, 0.25, 1), opacity 0.25s ease 0.75s";
      dot.style.transform = "translate(" + (to.left + to.width / 2) + "px, " + (to.top + to.height / 2) + "px)";
      dot.style.opacity = "0";
    }, 40);
    window.setTimeout(() => dot.remove(), 1200);
  }

  async function runDemo() {
    const text = draft.trim();
    if (!text || sendingRef.current) {
      inputRef.current?.focus();
      return;
    }

    const sysBits = ["stored by the gulls layer"];
    if (promptOn) {
      sysBits.push("prompt snapshot");
    }
    if (skillOn) {
      sysBits.push("skill snapshot");
    }

    const userId = nextId();
    const systemId = nextId();
    const pendingId = nextId();
    setMessages((prev) => [
      ...prev,
      { id: userId, role: "user", text, time: now(), delivered: false, pending: false },
      {
        id: systemId,
        role: "system",
        text: "Message " + sysBits.join(" · ") + ".",
        time: now(),
        delivered: false,
        pending: false,
      },
      { id: pendingId, role: "agent", text: "…", time: "", delivered: false, pending: true },
    ]);
    setDraft("");
    sendingRef.current = true;
    setSending(true);
    setCarryingHandle(recipient);

    let response = PAUSED_RESPONSE;
    let delivered = false;
    if (providerOn) {
      try {
        response = await landingDemoProviderResponse(text);
        delivered = true;
      } catch (error) {
        response = error instanceof Error ? error.message : "Provider delivery is unavailable for this demo run.";
      }
    }

    sendingRef.current = false;
    setSending(false);
    setCarryingHandle(null);
    const replyId = nextId();
    const replyTime = now();
    setMessages((prev) =>
      prev
        .filter((message) => message.id !== pendingId)
        .map((message) => (delivered && message.id === userId ? { ...message, delivered: true } : message))
        .concat({ id: replyId, role: "agent", text: response, time: replyTime, delivered: false, pending: false }),
    );
    setContinueVisible(true);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void runDemo();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void runDemo();
    }
  }

  const hot = Boolean(draft.trim()) || sending;
  const composerClass = "composer" + (hot ? " hot" : "") + (sending ? " busy" : "");

  return (
    <>
      <div className="sky" id="sky" ref={skyRef}>
        {AGENTS.map((agent) => {
          const active = agent.handle === recipient;
          const carrying = agent.handle === carryingHandle;
          return (
            <button
              key={agent.handle}
              type="button"
              className={"gull" + (active ? " active" : "") + (carrying ? " carrying" : "")}
              id={agent.id}
              data-handle={agent.handle}
              title={"Target " + agent.handle}
              aria-label={"Target " + agent.handle}
              aria-pressed={active}
              style={{ "--dur": agent.dur, "--delay": agent.delay } as CSSProperties}
              onClick={() => pickRecipient(agent.handle)}
            >
              <span className="bob">
                <GullIcon size={agent.size} strokeWidth={2.6} />
              </span>
              <span className="tag">{carrying ? "delivering…" : agent.name}</span>
            </button>
          );
        })}
        {AMBIENT_GULLS.map((gull) => (
          <span
            key={gull.key}
            className={"gull ambient" + (gull.edge ? " edge" : "")}
            aria-hidden="true"
            style={
              {
                left: gull.left,
                top: gull.top,
                opacity: gull.opacity,
                transform: gull.transform,
                "--dur": gull.dur,
                "--delay": gull.delay,
              } as CSSProperties
            }
          >
            <span className="bob">
              <GullIcon size={gull.size} strokeWidth={2.6} />
            </span>
          </span>
        ))}
      </div>

      <div className="page">
        <header className="topbar">
          <a className="brand" href="https://gulls.ai" aria-label="seagulls home">
            <span className="mark">S</span>
            <strong>seagulls</strong>
          </a>
          <div className="top-actions">
            <button
              className="theme-btn"
              id="themeBtn"
              type="button"
              aria-label="Toggle dark mode"
              title="Toggle dark mode"
              onClick={toggleTheme}
            >
              {dark ? "☀" : "☾"}
            </button>
            <a className="open-app" href="https://sea.gulls.ai">Open the app →</a>
          </div>
        </header>

        <main>
          <h1 id="hero-title" hidden={messages.length > 0}>
            Talk to your agent<span className="dot">.</span>
          </h1>

          <div className="thread" id="thread" aria-live="polite" hidden={messages.length === 0} ref={threadRef}>
            {messages.map((message) => (
              <div key={message.id} className={"row " + message.role + (message.pending ? " pending" : "")}>
                <span className="avatar" aria-hidden="true">
                  {message.role === "system" ? "g" : <GullIcon size={15} strokeWidth={3.4} />}
                </span>
                <article className="bubble">
                  <span className="txt">{message.text}</span>
                  <span className="meta">
                    {message.time}
                    {message.delivered && <span className="tick">✓✓</span>}
                  </span>
                </article>
              </div>
            ))}
          </div>

          <form className={composerClass} id="composer" ref={composerRef} onSubmit={handleSubmit}>
            <span className="perch" aria-hidden="true">
              <svg width={26} viewBox="0 0 32 14" fill="none">
                <path
                  className="gull-path"
                  d={gullPath}
                  stroke="currentColor"
                  strokeWidth={2.8}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span className="you">@you</span>
            </span>

            <div className="input-row">
              <textarea
                id="messageInput"
                ref={inputRef}
                rows={1}
                placeholder="Message your agent…"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={handleKeyDown}
              />
              <span className="enter-hint" aria-hidden="true">↵ Enter</span>
            </div>

            <div className="options" aria-label="Options">
              <button
                className="opt"
                id="promptToggle"
                type="button"
                data-tone="accent"
                aria-pressed={promptOn}
                aria-label="Prompt asset"
                title="Prompt asset"
                onClick={() => setPromptOn((on) => !on)}
              >
                ✎
              </button>
              <button
                className="opt"
                id="skillToggle"
                type="button"
                data-tone="indigo"
                aria-pressed={skillOn}
                aria-label="Skill asset"
                title="Skill asset"
                onClick={() => setSkillOn((on) => !on)}
              >
                ✦
              </button>
              <button
                className="opt"
                id="providerToggle"
                type="button"
                data-tone="amber"
                aria-pressed={providerOn}
                aria-label="Provider delivery"
                title="Provider delivery"
                onClick={() => setProviderOn((on) => !on)}
              >
                ⚡
              </button>
              <span className="spacer" />
              <select
                className="target-select"
                id="targetSelect"
                aria-label="Target agent"
                title="Target"
                value={recipient}
                onChange={(event) => setRecipient(event.target.value)}
              >
                {AGENTS.map((agent) => (
                  <option key={agent.handle} value={agent.handle}>
                    {"→ " + agent.handle}
                  </option>
                ))}
                <option value="" disabled>more targets at sea.gulls.ai</option>
              </select>
            </div>
          </form>

          <a className="continue" id="continueLink" href="https://sea.gulls.ai" hidden={!continueVisible}>
            Continue this thread in the app →
          </a>
        </main>

        <footer>
          <a href="https://sea.gulls.ai">sea.gulls.ai</a>
        </footer>
      </div>
    </>
  );
}

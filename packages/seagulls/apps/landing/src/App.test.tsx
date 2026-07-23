import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const roots: Root[] = [];

afterEach(async () => {
  for (const root of roots.splice(0)) {
    await act(async () => {
      root.unmount();
    });
  }
  document.body.innerHTML = "";
  document.body.classList.remove("sending");
  document.body.classList.remove("flying");
  document.documentElement.classList.remove("dark");
  window.localStorage.clear();
  window.SEAGULL_CONFIG = undefined;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("landing App", () => {
  it("renders the hero, agent targets, and composer", () => {
    const container = renderApp();

    expect(container.textContent).toContain("Talk to your agent");
    expect(container.textContent).toContain("@you");
    expect(container.textContent).toContain("sea.gulls.ai");
    expect(container.querySelectorAll(".sky .gull[data-handle]")).toHaveLength(4);
    expect(container.querySelectorAll(".sky .gull[data-handle] .dot")).toHaveLength(4);
    expect(container.querySelectorAll(".sky .gull.ambient")).toHaveLength(18);
    expect(container.querySelector("#gull-seagull")?.classList.contains("active")).toBe(true);
    expect(container.querySelector("#gull-researcher")?.getAttribute("data-status")).toBe("busy");
    expect(container.querySelectorAll("#targetSelect option")).toHaveLength(5);
  });

  it("gives each agent its own wing silhouette", () => {
    const container = renderApp();

    const pathFor = (id: string) =>
      container.querySelector(`#${id} .bob path`)?.getAttribute("d");
    const paths = ["gull-seagull", "gull-researcher", "gull-planner", "gull-reviewer"].map(pathFor);
    expect(new Set(paths).size).toBe(4);
  });

  it("runs the provider demo flow and marks the message delivered", async () => {
    window.SEAGULL_CONFIG = { aiProviderApiUrl: "https://ai.example.test" };
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ output_text: "Demo reply from provider." }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const container = renderApp();
    submitMessage(container, "hello gulls");
    await waitForText(container, "Demo reply from provider.");

    expect(fetchMock).toHaveBeenCalledWith(
      "https://ai.example.test/demo/landing/ai-run",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ message: "hello gulls" }),
      }),
    );
    expect(container.textContent).toContain("hello gulls");
    expect(container.textContent).toContain("stored by the gulls layer · prompt snapshot · skill snapshot");
    expect(container.textContent).toContain("@seagull ·");
    expect(container.querySelector(".tick")?.textContent).toBe("✓✓");
    expect(container.querySelector("#continueLink")?.hasAttribute("hidden")).toBe(false);
    expect(container.querySelector("#hero-title")?.hasAttribute("hidden")).toBe(true);
  });

  it("surfaces provider errors without a delivered tick", async () => {
    window.SEAGULL_CONFIG = { aiProviderApiUrl: "https://ai.example.test" };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ message: "Provider offline." }), {
          status: 503,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    const container = renderApp();
    submitMessage(container, "hello gulls");
    await waitForText(container, "Provider offline.");

    expect(container.querySelector(".tick")).toBeNull();
  });

  it("falls back to the stored-message copy when the provider is unreachable", async () => {
    window.SEAGULL_CONFIG = { aiProviderApiUrl: "https://ai.example.test" };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    const container = renderApp();
    submitMessage(container, "hello gulls");
    await waitForText(
      container,
      "Provider delivery is unavailable for this demo run, so the message stays stored with its asset snapshot for connector handling.",
    );

    expect(container.querySelector(".tick")).toBeNull();
  });

  it("keeps the message local when provider delivery is toggled off", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const container = renderApp();
    act(() => {
      container.querySelector<HTMLButtonElement>("#providerToggle")!.click();
      container.querySelector<HTMLButtonElement>("#skillToggle")!.click();
    });
    submitMessage(container, "hello gulls");
    await waitForText(container, "Provider delivery is paused for this run");

    expect(fetchMock).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Message stored by the gulls layer · prompt snapshot.");
    expect(container.querySelector(".tick")).toBeNull();
  });

  it("keeps the carrying indicator on the send-time target when retargeting mid-send", async () => {
    window.SEAGULL_CONFIG = { aiProviderApiUrl: "https://ai.example.test" };
    let resolveFetch!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((resolve) => { resolveFetch = resolve; })),
    );

    const container = renderApp();
    submitMessage(container, "hello gulls");

    act(() => {
      container.querySelector<HTMLButtonElement>("#gull-planner")!.click();
    });

    const original = container.querySelector("#gull-seagull")!;
    const retargeted = container.querySelector("#gull-planner")!;
    expect(original.classList.contains("carrying")).toBe(true);
    expect(original.querySelector(".tag")?.textContent).toBe("delivering…");
    expect(retargeted.classList.contains("carrying")).toBe(false);
    expect(retargeted.classList.contains("active")).toBe(true);

    act(() => {
      resolveFetch(
        new Response(JSON.stringify({ output_text: "Demo reply from provider." }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    });
    await waitForText(container, "Demo reply from provider.");

    expect(original.classList.contains("carrying")).toBe(false);
    expect(original.querySelector(".tag")?.textContent).toBe("@seagull · online");
  });

  it("retargets the demo from the sky gulls", () => {
    const container = renderApp();

    act(() => {
      container.querySelector<HTMLButtonElement>("#gull-reviewer")!.click();
    });

    expect(container.querySelector("#gull-reviewer")?.classList.contains("active")).toBe(true);
    expect(container.querySelector("#gull-seagull")?.classList.contains("active")).toBe(false);
    expect(container.querySelector<HTMLSelectElement>("#targetSelect")?.value).toBe("@reviewer:gulls.ai");
  });

  it("toggles and persists the dark theme", () => {
    const container = renderApp();

    act(() => {
      container.querySelector<HTMLButtonElement>("#themeBtn")!.click();
    });

    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(window.localStorage.getItem("seagulls-theme")).toBe("dark");

    act(() => {
      container.querySelector<HTMLButtonElement>("#themeBtn")!.click();
    });

    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(window.localStorage.getItem("seagulls-theme")).toBe("light");
  });
});

function renderApp(): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.push(root);
  act(() => {
    root.render(<App />);
  });
  return container;
}

function submitMessage(container: HTMLElement, text: string): void {
  const textarea = container.querySelector<HTMLTextAreaElement>("#messageInput")!;
  const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
  act(() => {
    setValue.call(textarea, text);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
  act(() => {
    textarea.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }),
    );
  });
}

async function waitForText(container: HTMLElement, text: string): Promise<void> {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    if (container.textContent?.includes(text)) {
      return;
    }
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
  throw new Error(`Expected to find "${text}" in: ${container.textContent ?? ""}`);
}

import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DesktopLoginPage } from "./desktop-login-page";
import type { AuthSession } from "../lib/auth";
import { DESKTOP_LOGIN_REQUEST_KEY, saveDesktopLoginRequest } from "../lib/desktop-login";
import type { SocialApiClient } from "../lib/api";

let root: Root | null = null;
let container: HTMLDivElement | null = null;

const session: AuthSession = {
  accessToken: "access-secret",
  idToken: "id-secret",
  refreshToken: "refresh-secret",
  tokenType: "Bearer",
  expiresAt: Date.now() + 60_000,
};

const request = {
  callback: "http://127.0.0.1:43127/callback",
  state: "A".repeat(43),
  createdAt: Date.now(),
};

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  window.sessionStorage.clear();
  vi.restoreAllMocks();
  root = null;
  container = null;
});

function render({ authenticated = true, initialEntry = "/desktop/login", strict = false } = {}) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const props = {
    api: {} as SocialApiClient,
    authConfig: { mode: "local" as const },
    authSession: authenticated ? session : null,
    isAuthenticated: authenticated,
    resolvedTheme: "light" as const,
    onToggleTheme: vi.fn(),
    onLocalIdentity: vi.fn(),
    onAuthSession: vi.fn(),
    onNotice: vi.fn(),
  };
  act(() => {
    const page = (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[initialEntry]}>
          <DesktopLoginPage {...props} />
        </MemoryRouter>
      </QueryClientProvider>
    );
    root?.render(strict ? <StrictMode>{page}</StrictMode> : page);
  });
  return container;
}

function button(view: HTMLElement, label: string): HTMLButtonElement {
  const match = Array.from(view.querySelectorAll("button")).find((item) => item.textContent?.trim() === label);
  if (!(match instanceof HTMLButtonElement)) throw new Error(`Button ${label} not found.`);
  return match;
}

describe("DesktopLoginPage", () => {
  it("keeps signed-out users on email auth and preserves the desktop register route", () => {
    saveDesktopLoginRequest(request);
    const view = render({ authenticated: false });
    expect(view.querySelector('input[aria-label="Email"]')).not.toBeNull();
    const registerLink = view.querySelector('a[href="/desktop/login?mode=register"]');
    expect(registerLink).not.toBeNull();
  });

  it("processes an initial callback fragment before showing signed-out email auth", () => {
    const initialEntry = `/desktop/login#callback=${encodeURIComponent(request.callback)}&state=${request.state}`;
    const view = render({ authenticated: false, initialEntry });
    expect(view.querySelector('input[aria-label="Email"]')).not.toBeNull();
    expect(view.textContent).not.toContain("Preparing your secure connection");
  });

  it("does not transfer on load and transfers only after explicit Continue", async () => {
    saveDesktopLoginRequest(request);
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    const view = render();
    expect(fetcher).not.toHaveBeenCalled();
    await act(async () => button(view, "Continue on this computer").click());
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(view.textContent).toContain("You’re connected.");
  });

  it("survives StrictMode effect cleanup and completes an explicit Continue", async () => {
    saveDesktopLoginRequest(request);
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    const view = render({ strict: true });
    await act(async () => button(view, "Continue on this computer").click());
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(view.textContent).toContain("You’re connected.");
  });

  it("keeps the request for retry after a failed callback", async () => {
    saveDesktopLoginRequest(request);
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response("", { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    const view = render();
    await act(async () => button(view, "Continue on this computer").click());
    expect(view.textContent).toContain("could not receive");
    await act(async () => button(view, "Continue on this computer").click());
    expect(view.textContent).toContain("You’re connected.");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("blocks invalid and expired stored requests before showing the auth form", () => {
    window.sessionStorage.setItem(
      DESKTOP_LOGIN_REQUEST_KEY,
      JSON.stringify({ callback: "http://localhost:43127/callback", state: "bad", createdAt: Date.now() }),
    );
    const invalid = render({ authenticated: false });
    expect(invalid.querySelector('input[aria-label="Email"]')).toBeNull();
    expect(invalid.textContent).toContain("expired or is invalid");

    act(() => root?.unmount());
    root = null;
    window.sessionStorage.setItem(
      DESKTOP_LOGIN_REQUEST_KEY,
      JSON.stringify({ ...request, createdAt: Date.now() - 6 * 60 * 1000 }),
    );
    const expired = render({ authenticated: false });
    expect(expired.querySelector('input[aria-label="Email"]')).toBeNull();
    expect(expired.textContent).toContain("expired or is invalid");
  });
});

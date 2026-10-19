import type { AuthSession } from "./auth";

export const DESKTOP_LOGIN_PATH = "/desktop/login";
export const DESKTOP_LOGIN_REQUEST_KEY = "seagull.desktop.login.request";
export const DESKTOP_LOGIN_MAX_AGE_MS = 5 * 60 * 1000;
export const DESKTOP_LOGIN_TRANSFER_TIMEOUT_MS = 20_000;

export type DesktopLoginRequest = {
  callback: string;
  state: string;
  createdAt: number;
};

export type DesktopLoginRequestResult =
  | { request: DesktopLoginRequest; error: null }
  | { request: null; error: null }
  | { request: null; error: string };

const CALLBACK_PATTERN = /^http:\/\/127\.0\.0\.1:([1-9]\d{0,4})\/callback$/;
const STATE_PATTERN = /^[A-Za-z0-9_-]{43}$/;

function isValidDesktopLoginRequestShape(request: DesktopLoginRequest): boolean {
  const callbackMatch = CALLBACK_PATTERN.exec(request.callback);
  const port = callbackMatch ? Number(callbackMatch[1]) : 0;
  return Boolean(callbackMatch && port <= 65535 && STATE_PATTERN.test(request.state));
}

export function parseDesktopLoginFragment(
  hash: string,
  now = Date.now(),
): DesktopLoginRequestResult {
  if (!hash || hash === "#") {
    return { request: null, error: null };
  }

  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  const params = new URLSearchParams(raw);
  const entries = [...params.entries()];
  const keys = entries.map(([key]) => key);
  if (keys.length !== 2 || new Set(keys).size !== 2 || !keys.includes("callback") || !keys.includes("state")) {
    return { request: null, error: "This desktop sign-in request is invalid." };
  }

  const callback = params.get("callback") ?? "";
  const state = params.get("state") ?? "";
  const callbackMatch = CALLBACK_PATTERN.exec(callback);
  const port = callbackMatch ? Number(callbackMatch[1]) : 0;
  if (!callbackMatch || port > 65535 || !STATE_PATTERN.test(state)) {
    return { request: null, error: "This desktop sign-in request is invalid." };
  }

  return {
    request: { callback, state, createdAt: now },
    error: null,
  };
}

export function isDesktopLoginRequestActive(
  request: DesktopLoginRequest | null,
  now = Date.now(),
): request is DesktopLoginRequest {
  return Boolean(request && now - request.createdAt >= 0 && now - request.createdAt <= DESKTOP_LOGIN_MAX_AGE_MS);
}

export function loadDesktopLoginRequest(
  storage: Storage = window.sessionStorage,
  now = Date.now(),
): DesktopLoginRequest | null {
  const raw = storage.getItem(DESKTOP_LOGIN_REQUEST_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<DesktopLoginRequest>;
    if (
      typeof parsed.callback !== "string" ||
      typeof parsed.state !== "string" ||
      typeof parsed.createdAt !== "number"
    ) {
      storage.removeItem(DESKTOP_LOGIN_REQUEST_KEY);
      return null;
    }
    const request = { callback: parsed.callback, state: parsed.state, createdAt: parsed.createdAt };
    if (!isValidDesktopLoginRequestShape(request) || !isDesktopLoginRequestActive(request, now)) {
      storage.removeItem(DESKTOP_LOGIN_REQUEST_KEY);
      return null;
    }
    return request;
  } catch {
    storage.removeItem(DESKTOP_LOGIN_REQUEST_KEY);
    return null;
  }
}

export function saveDesktopLoginRequest(
  request: DesktopLoginRequest,
  storage: Storage = window.sessionStorage,
): void {
  storage.setItem(DESKTOP_LOGIN_REQUEST_KEY, JSON.stringify(request));
}

export function clearDesktopLoginRequest(storage: Storage = window.sessionStorage): void {
  storage.removeItem(DESKTOP_LOGIN_REQUEST_KEY);
}

export async function transferDesktopLogin(
  request: DesktopLoginRequest,
  session: AuthSession,
  fetcher: typeof fetch = fetch,
  timeoutMs = DESKTOP_LOGIN_TRANSFER_TIMEOUT_MS,
  externalSignal?: AbortSignal,
): Promise<void> {
  if (!isValidDesktopLoginRequestShape(request)) {
    throw new Error("This desktop sign-in request is invalid. Start again from the Mac app.");
  }
  if (!isDesktopLoginRequestActive(request)) {
    throw new Error("This desktop sign-in request expired. Start again from the Mac app.");
  }

  const controller = new AbortController();
  const onExternalAbort = () => controller.abort();
  externalSignal?.addEventListener("abort", onExternalAbort, { once: true });
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetcher(request.callback, {
      method: "POST",
      mode: "cors",
      credentials: "omit",
      redirect: "error",
      referrerPolicy: "no-referrer",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        state: request.state,
        session: {
          accessToken: session.accessToken,
          expiresAt: session.expiresAt,
          tokenType: session.tokenType,
        },
      }),
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error("The Mac app could not receive this sign-in.");
    }
    const result = (await response.json()) as { ok?: boolean };
    if (result.ok !== true) {
      throw new Error("The Mac app could not confirm this sign-in.");
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("The Mac app did not respond in time. Check that it is still waiting for sign-in.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
    externalSignal?.removeEventListener("abort", onExternalAbort);
  }
}

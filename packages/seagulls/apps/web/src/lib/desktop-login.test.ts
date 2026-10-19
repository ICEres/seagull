import { describe, expect, it, vi } from "vitest";

import {
  DESKTOP_LOGIN_REQUEST_KEY,
  clearDesktopLoginRequest,
  loadDesktopLoginRequest,
  parseDesktopLoginFragment,
  saveDesktopLoginRequest,
  transferDesktopLogin,
  type DesktopLoginRequest,
} from "./desktop-login";

const state = "A".repeat(43);
const callback = "http://127.0.0.1:43127/callback";

function request(createdAt = Date.now()): DesktopLoginRequest {
  return { callback, state, createdAt };
}

describe("desktop login handoff", () => {
  it("accepts only the exact loopback callback and state shape", () => {
    expect(parseDesktopLoginFragment(`#callback=${encodeURIComponent(callback)}&state=${state}`).error).toBeNull();
    expect(parseDesktopLoginFragment(`#callback=${encodeURIComponent("http://localhost:43127/callback")}&state=${state}`).error).toBeTruthy();
    expect(parseDesktopLoginFragment(`#callback=${encodeURIComponent(callback)}&state=${"A".repeat(42)}`).error).toBeTruthy();
    expect(parseDesktopLoginFragment(`#callback=${encodeURIComponent(callback)}&state=${state}&state=${state}`).error).toBeTruthy();
    expect(parseDesktopLoginFragment(`#callback=${encodeURIComponent(callback)}&state=${state}&next=%2Fsky`).error).toBeTruthy();
  });

  it("stores a pending request only in session storage and clears it once", () => {
    const storage = window.sessionStorage;
    storage.clear();
    const pending = request();
    saveDesktopLoginRequest(pending, storage);
    expect(storage.getItem(DESKTOP_LOGIN_REQUEST_KEY)).toContain(callback);
    expect(window.localStorage.getItem(DESKTOP_LOGIN_REQUEST_KEY)).toBeNull();
    expect(loadDesktopLoginRequest(storage)).toEqual(pending);
    clearDesktopLoginRequest(storage);
    expect(loadDesktopLoginRequest(storage)).toBeNull();
  });

  it("expires pending requests after five minutes", () => {
    const storage = window.sessionStorage;
    storage.clear();
    saveDesktopLoginRequest(request(1_000), storage);
    expect(loadDesktopLoginRequest(storage, 301_001)).toBeNull();
    expect(storage.getItem(DESKTOP_LOGIN_REQUEST_KEY)).toBeNull();
  });

  it("transfers only the short-lived session fields when explicitly called", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }));
    await transferDesktopLogin(
      request(),
      {
        accessToken: "access-secret",
        idToken: "id-secret",
        refreshToken: "refresh-secret",
        expiresAt: Date.now() + 60_000,
        tokenType: "Bearer",
      },
      fetcher,
    );
    expect(fetcher).toHaveBeenCalledTimes(1);
    const [, init] = fetcher.mock.calls[0] ?? [];
    expect(JSON.parse(String(init?.body))).toEqual({
      state,
      session: { accessToken: "access-secret", expiresAt: expect.any(Number), tokenType: "Bearer" },
    });
    expect(String(init?.body)).not.toContain("id-secret");
    expect(String(init?.body)).not.toContain("refresh-secret");
    expect(init).toMatchObject({ credentials: "omit", mode: "cors", redirect: "error", referrerPolicy: "no-referrer" });
  });
});

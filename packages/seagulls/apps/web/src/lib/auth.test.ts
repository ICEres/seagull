import { describe, expect, it, beforeEach } from "vitest";

import {
  authConfigFromRuntime,
  beginHostedLogin,
  clearAuthSession,
  completeHostedCallback,
  hostedAuthorizeUrl,
  hostedLogoutUrl,
  isSessionActive,
  loadAuthSession,
  parseAuthCallbackUrl,
  saveAuthSession,
  type AuthConfig,
} from "./auth";

const cognitoConfig: Extract<AuthConfig, { mode: "cognito" }> = {
  mode: "cognito",
  issuer: "https://cognito-idp.ap-southeast-2.amazonaws.com/pool_1",
  hostedDomain: "seagull-social.auth.ap-southeast-2.amazoncognito.com",
  clientId: "client_1",
  redirectUri: "https://sea.gulls.ai/auth/callback",
  logoutUri: "https://sea.gulls.ai/register",
};

describe("auth helpers", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  it("parses local and Cognito runtime config", () => {
    expect(authConfigFromRuntime({ auth: { mode: "local" } })).toEqual({ mode: "local" });
    expect(authConfigFromRuntime({ auth: cognitoConfig })).toEqual(cognitoConfig);
  });

  it("builds Hosted UI authorization and logout URLs", () => {
    const authorizeUrl = new URL(hostedAuthorizeUrl(cognitoConfig, "state_1", "challenge_1"));
    expect(authorizeUrl.origin).toBe(`https://${cognitoConfig.hostedDomain}`);
    expect(authorizeUrl.pathname).toBe("/oauth2/authorize");
    expect(authorizeUrl.searchParams.get("client_id")).toBe(cognitoConfig.clientId);
    expect(authorizeUrl.searchParams.get("redirect_uri")).toBe(cognitoConfig.redirectUri);
    expect(authorizeUrl.searchParams.get("state")).toBe("state_1");
    expect(authorizeUrl.searchParams.get("code_challenge_method")).toBe("S256");

    const logoutUrl = new URL(hostedLogoutUrl(cognitoConfig));
    expect(logoutUrl.pathname).toBe("/logout");
    expect(logoutUrl.searchParams.get("logout_uri")).toBe(cognitoConfig.logoutUri);
  });

  it("parses callback URLs and exchanges a code for a stored session", async () => {
    window.sessionStorage.setItem(
      "seagull.web.auth.pending",
      JSON.stringify({ state: "state_1", codeVerifier: "verifier_1", createdAt: 1 }),
    );

    const callback = parseAuthCallbackUrl(
      "https://sea.gulls.ai/auth/callback?code=code_1&state=state_1",
    );
    expect(callback).toMatchObject({ code: "code_1", state: "state_1" });

    const session = await completeHostedCallback(
      cognitoConfig,
      "https://sea.gulls.ai/auth/callback?code=code_1&state=state_1",
      async (_input, init) => {
        expect(String(init?.body)).toContain("code=code_1");
        return new Response(
          JSON.stringify({
            access_token: "access_1",
            id_token: "id_1",
            token_type: "Bearer",
            expires_in: 60,
          }),
          { status: 200 },
        );
      },
    );

    expect(session.accessToken).toBe("access_1");
    expect(loadAuthSession()?.accessToken).toBe("access_1");
    expect(window.localStorage.getItem("seagull.web.auth.session")).toBeNull();
  });

  it("stores, checks, and clears sessions", () => {
    saveAuthSession({
      accessToken: "access_1",
      idToken: null,
      refreshToken: null,
      tokenType: "Bearer",
      expiresAt: 120_000,
    });

    expect(isSessionActive(loadAuthSession(), 1_000)).toBe(true);
    expect(isSessionActive(loadAuthSession(), 100_000)).toBe(false);
    clearAuthSession();
    expect(loadAuthSession()).toBeNull();
  });

  it("starts Hosted UI login with a stored PKCE verifier", async () => {
    const authorizationUrl = new URL(await beginHostedLogin(cognitoConfig));
    const pending = JSON.parse(window.sessionStorage.getItem("seagull.web.auth.pending") ?? "{}");

    expect(authorizationUrl.origin).toBe(`https://${cognitoConfig.hostedDomain}`);
    expect(authorizationUrl.searchParams.get("response_type")).toBe("code");
    expect(authorizationUrl.searchParams.get("code_challenge_method")).toBe("S256");
    expect(authorizationUrl.searchParams.get("state")).toBe(pending.state);
    expect(pending.codeVerifier).toBeTruthy();
    expect(window.localStorage.getItem("seagull.web.auth.pending")).toBeNull();
  });
});

import { describe, expect, it, beforeEach } from "vitest";

import {
  authConfigFromRuntime,
  clearAuthSession,
  confirmCognitoRegistration,
  completeHostedCallback,
  hostedAuthorizeUrl,
  hostedLogoutUrl,
  isSessionActive,
  loadAuthSession,
  loginWithCognito,
  parseAuthCallbackUrl,
  registerWithCognito,
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
    window.localStorage.setItem(
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

  it("calls Cognito signup, confirmation, and login APIs for custom forms", async () => {
    const targets: string[] = [];
    const fetcher = async (_input: RequestInfo | URL, init?: RequestInit) => {
      targets.push(new Headers(init?.headers).get("x-amz-target") ?? "");
      const body = JSON.parse(String(init?.body));
      if (targets.at(-1) === "AWSCognitoIdentityProviderService.SignUp") {
        expect(body.Username).toBe("alice@example.com");
        expect(body.UserAttributes).toContainEqual({ Name: "name", Value: "Alice" });
        return new Response(JSON.stringify({}), { status: 200 });
      }
      if (targets.at(-1) === "AWSCognitoIdentityProviderService.ConfirmSignUp") {
        expect(body.ConfirmationCode).toBe("123456");
        return new Response(JSON.stringify({}), { status: 200 });
      }
      expect(body.AuthFlow).toBe("USER_PASSWORD_AUTH");
      return new Response(
        JSON.stringify({
          AuthenticationResult: {
            AccessToken: "access_1",
            IdToken: "id_1",
            RefreshToken: "refresh_1",
            TokenType: "Bearer",
            ExpiresIn: 3600,
          },
        }),
        { status: 200 },
      );
    };

    await registerWithCognito(
      cognitoConfig,
      { email: "alice@example.com", password: "Password123", displayName: "Alice" },
      fetcher,
    );
    await confirmCognitoRegistration(cognitoConfig, { email: "alice@example.com", code: "123456" }, fetcher);
    const session = await loginWithCognito(
      cognitoConfig,
      { email: "alice@example.com", password: "Password123" },
      fetcher,
    );

    expect(targets).toEqual([
      "AWSCognitoIdentityProviderService.SignUp",
      "AWSCognitoIdentityProviderService.ConfirmSignUp",
      "AWSCognitoIdentityProviderService.InitiateAuth",
    ]);
    expect(session.accessToken).toBe("access_1");
    expect(loadAuthSession()?.refreshToken).toBe("refresh_1");
  });
});

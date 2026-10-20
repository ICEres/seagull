import { describe, expect, it, beforeEach } from "vitest";

import {
  authConfigFromRuntime,
  beginEmailOtpRegistration,
  beginEmailOtpSignIn,
  clearAuthSession,
  completeEmailOtpRegistration,
  completeEmailOtpSignIn,
  isSessionActive,
  loadAuthSession,
  resendEmailOtpRegistration,
  refreshAuthSession,
  saveAuthSession,
  type AuthConfig,
} from "./auth";

const cognitoConfig: Extract<AuthConfig, { mode: "cognito" }> = {
  mode: "cognito",
  issuer: "https://cognito-idp.ap-southeast-2.amazonaws.com/pool_1",
  clientId: "client_1",
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

  it("signs in with an emailed one-time code", async () => {
    const requestedBodies: Record<string, unknown>[] = [];
    const fetcher: typeof fetch = async (_input, init) => {
      const target = new Headers(init?.headers).get("x-amz-target") ?? "";
      requestedBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      if (target.endsWith(".InitiateAuth")) {
        return new Response(
          JSON.stringify({ ChallengeName: "EMAIL_OTP", Session: "challenge_session_1" }),
          { status: 200 },
        );
      }
      if (target.endsWith(".RespondToAuthChallenge")) {
        return new Response(
          JSON.stringify({
            AuthenticationResult: {
              AccessToken: "access_otp_1",
              IdToken: "id_otp_1",
              RefreshToken: "refresh_otp_1",
              TokenType: "Bearer",
              ExpiresIn: 3600,
            },
          }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ message: "unexpected operation" }), { status: 400 });
    };

    const challenge = await beginEmailOtpSignIn(cognitoConfig, "  ALICE@example.com ", fetcher);
    expect(challenge).toEqual({
      kind: "sign-in",
      email: "alice@example.com",
      session: "challenge_session_1",
    });

    const session = await completeEmailOtpSignIn(cognitoConfig, challenge, " 123456 ", fetcher);
    expect(session.accessToken).toBe("access_otp_1");
    expect(session.refreshToken).toBe("refresh_otp_1");
    expect(loadAuthSession()?.accessToken).toBe("access_otp_1");
    expect(requestedBodies[0]).toMatchObject({
      AuthFlow: "USER_AUTH",
      AuthParameters: {
        USERNAME: "alice@example.com",
        PREFERRED_CHALLENGE: "EMAIL_OTP",
      },
    });
    expect(requestedBodies[1]).toMatchObject({
      ChallengeName: "EMAIL_OTP",
      ChallengeResponses: {
        USERNAME: "alice@example.com",
        EMAIL_OTP_CODE: "123456",
      },
    });
    expect(JSON.stringify(requestedBodies)).not.toContain("PASSWORD");
  });

  it("registers without a password and signs in from the confirmation session", async () => {
    const operations: string[] = [];
    const requestedBodies: Record<string, unknown>[] = [];
    const fetcher: typeof fetch = async (_input, init) => {
      const target = new Headers(init?.headers).get("x-amz-target") ?? "";
      const operation = target.split(".").pop() ?? "";
      operations.push(operation);
      requestedBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      if (operation === "SignUp") {
        return new Response(JSON.stringify({ UserConfirmed: false }), { status: 200 });
      }
      if (operation === "ResendConfirmationCode") {
        return new Response(JSON.stringify({}), { status: 200 });
      }
      if (operation === "ConfirmSignUp") {
        return new Response(JSON.stringify({ Session: "confirmation_session_1" }), { status: 200 });
      }
      if (operation === "InitiateAuth") {
        return new Response(
          JSON.stringify({
            AuthenticationResult: {
              AccessToken: "access_registered_1",
              TokenType: "Bearer",
              ExpiresIn: 3600,
            },
          }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ message: "unexpected operation" }), { status: 400 });
    };

    const challenge = await beginEmailOtpRegistration(cognitoConfig, "new@example.com", fetcher);
    expect(challenge.kind).toBe("registration");
    if (challenge.kind !== "registration") {
      throw new Error("Expected a registration challenge.");
    }
    await resendEmailOtpRegistration(cognitoConfig, challenge.email, fetcher);
    const result = await completeEmailOtpRegistration(cognitoConfig, challenge, "654321", fetcher);
    if (!("accessToken" in result)) {
      throw new Error("Expected an authenticated session.");
    }

    expect(operations).toEqual([
      "SignUp",
      "ResendConfirmationCode",
      "ConfirmSignUp",
      "InitiateAuth",
    ]);
    expect(result.accessToken).toBe("access_registered_1");
    expect(requestedBodies[0]).toMatchObject({
      ClientId: cognitoConfig.clientId,
      Username: "new@example.com",
      UserAttributes: [{ Name: "email", Value: "new@example.com" }],
    });
    expect(requestedBodies[3]).toMatchObject({
      AuthFlow: "USER_AUTH",
      Session: "confirmation_session_1",
    });
    expect(JSON.stringify(requestedBodies)).not.toContain("Password");
  });

  it("resends registration codes for an existing unconfirmed account", async () => {
    const operations: string[] = [];
    const challenge = await beginEmailOtpRegistration(
      cognitoConfig,
      "pending@example.com",
      async (_input, init) => {
        const target = new Headers(init?.headers).get("x-amz-target") ?? "";
        const operation = target.split(".").pop() ?? "";
        operations.push(operation);
        if (operation === "SignUp") {
          return new Response(
            JSON.stringify({
              __type: "UsernameExistsException",
              message: "User already exists",
            }),
            { status: 400 },
          );
        }
        return new Response(JSON.stringify({}), { status: 200 });
      },
    );

    expect(challenge.email).toBe("pending@example.com");
    expect(challenge.kind).toBe("registration");
    expect(operations).toEqual(["SignUp", "ResendConfirmationCode"]);
  });

  it("signs in an existing confirmed account without disclosing it in the UI flow", async () => {
    const operations: string[] = [];
    const challenge = await beginEmailOtpRegistration(
      cognitoConfig,
      "existing@example.com",
      async (_input, init) => {
        const target = new Headers(init?.headers).get("x-amz-target") ?? "";
        const operation = target.split(".").pop() ?? "";
        operations.push(operation);
        if (operation === "SignUp") {
          return new Response(
            JSON.stringify({ __type: "UsernameExistsException", message: "User already exists" }),
            { status: 400 },
          );
        }
        if (operation === "ResendConfirmationCode") {
          return new Response(
            JSON.stringify({
              __type: "InvalidParameterException",
              message: "User is already confirmed.",
            }),
            { status: 400 },
          );
        }
        return new Response(
          JSON.stringify({ ChallengeName: "EMAIL_OTP", Session: "sign_in_session_1" }),
          { status: 200 },
        );
      },
    );

    expect(challenge).toEqual({
      kind: "sign-in",
      email: "existing@example.com",
      session: "sign_in_session_1",
    });
    expect(operations).toEqual(["SignUp", "ResendConfirmationCode", "InitiateAuth"]);
  });

  it("requests a sign-in code when confirmation cannot create a session", async () => {
    const operations: string[] = [];
    const result = await completeEmailOtpRegistration(
      cognitoConfig,
      { kind: "registration", email: "new@example.com" },
      "654321",
      async (_input, init) => {
        const target = new Headers(init?.headers).get("x-amz-target") ?? "";
        const operation = target.split(".").pop() ?? "";
        operations.push(operation);
        if (operation === "ConfirmSignUp") {
          return new Response(JSON.stringify({}), { status: 200 });
        }
        return new Response(
          JSON.stringify({ ChallengeName: "EMAIL_OTP", Session: "sign_in_session_1" }),
          { status: 200 },
        );
      },
    );

    expect(result).toEqual({
      kind: "sign-in",
      email: "new@example.com",
      session: "sign_in_session_1",
    });
    expect(operations).toEqual(["ConfirmSignUp", "InitiateAuth"]);
  });

  it("surfaces Cognito error types for code-entry feedback", async () => {
    await expect(
      completeEmailOtpSignIn(
        cognitoConfig,
        { kind: "sign-in", email: "alice@example.com", session: "challenge_session_1" },
        "000000",
        async () =>
          new Response(
            JSON.stringify({
              __type: "com.amazon.cognito#CodeMismatchException",
              message: "Incorrect username or password.",
            }),
            { status: 400 },
          ),
      ),
    ).rejects.toMatchObject({ name: "CodeMismatchException" });
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

  it("persists sessions in localStorage and migrates the legacy sessionStorage entry", () => {
    window.sessionStorage.setItem(
      "seagull.web.auth.session",
      JSON.stringify({
        accessToken: "legacy-access",
        idToken: "legacy-id",
        refreshToken: "legacy-refresh",
        tokenType: "Bearer",
        expiresAt: Date.now() + 3_600_000,
      }),
    );

    expect(loadAuthSession()).toMatchObject({
      accessToken: "legacy-access",
      refreshToken: "legacy-refresh",
    });
    expect(window.localStorage.getItem("seagull.web.auth.session")).toContain("legacy-access");
    expect(window.sessionStorage.getItem("seagull.web.auth.session")).toBeNull();

    saveAuthSession({
      accessToken: "persistent-access",
      idToken: null,
      refreshToken: "persistent-refresh",
      tokenType: "Bearer",
      expiresAt: Date.now() + 3_600_000,
    });
    expect(window.localStorage.getItem("seagull.web.auth.session")).toContain("persistent-access");
    expect(window.sessionStorage.getItem("seagull.web.auth.session")).toBeNull();
  });

  it("clears both persistent and legacy session stores on logout", () => {
    window.localStorage.setItem("seagull.web.auth.session", "local-session");
    window.localStorage.setItem("seagull.web.auth.pending", "local-pending");
    window.sessionStorage.setItem("seagull.web.auth.session", "legacy-session");
    window.sessionStorage.setItem("seagull.web.auth.pending", "legacy-pending");

    clearAuthSession();

    expect(window.localStorage.getItem("seagull.web.auth.session")).toBeNull();
    expect(window.localStorage.getItem("seagull.web.auth.pending")).toBeNull();
    expect(window.sessionStorage.getItem("seagull.web.auth.session")).toBeNull();
    expect(window.sessionStorage.getItem("seagull.web.auth.pending")).toBeNull();
  });

  it("prefers the current session and removes a stale legacy copy", () => {
    window.localStorage.setItem(
      "seagull.web.auth.session",
      JSON.stringify({
        accessToken: "current-access",
        idToken: null,
        refreshToken: "current-refresh",
        tokenType: "Bearer",
        expiresAt: Date.now() + 3_600_000,
      }),
    );
    window.sessionStorage.setItem(
      "seagull.web.auth.session",
      JSON.stringify({
        accessToken: "stale-access",
        idToken: null,
        refreshToken: "stale-refresh",
        tokenType: "Bearer",
        expiresAt: Date.now() + 3_600_000,
      }),
    );

    expect(loadAuthSession()?.accessToken).toBe("current-access");
    expect(window.sessionStorage.getItem("seagull.web.auth.session")).toBeNull();

    clearAuthSession();
    expect(loadAuthSession()).toBeNull();
  });

  it("refreshes Cognito sessions without saving a stale result and preserves its refresh token", async () => {
    const session = {
      accessToken: "expired-access",
      idToken: "old-id",
      refreshToken: "refresh-current",
      tokenType: "Bearer",
      expiresAt: Date.now() - 1_000,
    };
    saveAuthSession(session);
    let requestBody: Record<string, unknown> | null = null;

    const refreshed = await refreshAuthSession(
      cognitoConfig,
      session,
      async (_input, init) => {
        requestBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
        return new Response(
          JSON.stringify({
            AuthenticationResult: {
              AccessToken: "refreshed-access",
              IdToken: "refreshed-id",
              TokenType: "Bearer",
              ExpiresIn: 1800,
            },
          }),
          { status: 200 },
        );
      },
    );

    expect(requestBody).toEqual({
      AuthFlow: "REFRESH_TOKEN_AUTH",
      AuthParameters: { REFRESH_TOKEN: "refresh-current" },
      ClientId: cognitoConfig.clientId,
    });
    expect(refreshed).toMatchObject({
      accessToken: "refreshed-access",
      idToken: "refreshed-id",
      refreshToken: "refresh-current",
    });
    expect(loadAuthSession()?.accessToken).toBe("expired-access");
  });

  it("surfaces refresh failures and requires a refresh token", async () => {
    await expect(
      refreshAuthSession(cognitoConfig, {
        accessToken: "expired-access",
        idToken: null,
        refreshToken: null,
        tokenType: "Bearer",
        expiresAt: Date.now() - 1_000,
      }),
    ).rejects.toThrow("does not include a refresh token");

    await expect(
      refreshAuthSession(
        cognitoConfig,
        {
          accessToken: "expired-access",
          idToken: null,
          refreshToken: "refresh-invalid",
          tokenType: "Bearer",
          expiresAt: Date.now() - 1_000,
        },
        async () =>
          new Response(
            JSON.stringify({
              __type: "NotAuthorizedException",
              message: "Refresh Token has expired",
            }),
            { status: 400 },
          ),
      ),
    ).rejects.toMatchObject({ name: "NotAuthorizedException" });
  });

});

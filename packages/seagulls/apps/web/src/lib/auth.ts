export type AuthMode = "local" | "cognito";

export type RuntimeAuthConfig = {
  mode?: string;
  issuer?: string;
  hostedDomain?: string;
  clientId?: string;
  redirectUri?: string;
  logoutUri?: string;
};

export type RuntimeConfig = {
  socialApiUrl?: string;
  auth?: RuntimeAuthConfig;
};

export type AuthConfig =
  | {
      mode: "local";
    }
  | {
      mode: "cognito";
      issuer: string;
      clientId: string;
    };

export type AuthSession = {
  accessToken: string;
  idToken: string | null;
  refreshToken: string | null;
  tokenType: string;
  expiresAt: number;
};

export type EmailOtpChallenge =
  | {
      kind: "sign-in";
      email: string;
      session: string;
    }
  | {
      kind: "registration";
      email: string;
    };

type CognitoAuthenticationResult = {
  AccessToken?: string;
  IdToken?: string;
  RefreshToken?: string;
  TokenType?: string;
  ExpiresIn?: number;
};

type CognitoAuthResponse = {
  AuthenticationResult?: CognitoAuthenticationResult;
  ChallengeName?: string;
  Session?: string;
};

type CognitoErrorPayload = {
  __type?: string;
  message?: string;
  Message?: string;
};

const SESSION_KEY = "seagull.web.auth.session";
const PENDING_KEY = "seagull.web.auth.pending";

export function configuredAuth(): AuthConfig {
  return authConfigFromRuntime(window.SEAGULL_CONFIG, {
    mode: import.meta.env.VITE_AUTH_MODE,
    issuer: import.meta.env.VITE_COGNITO_ISSUER,
    clientId: import.meta.env.VITE_COGNITO_CLIENT_ID,
  });
}

export function authConfigFromRuntime(
  runtime: RuntimeConfig | undefined,
  env: RuntimeAuthConfig = {},
): AuthConfig {
  const runtimeAuth = runtime?.auth ?? {};
  const mode = runtimeAuth.mode || env.mode || "local";
  if (mode !== "cognito") {
    return { mode: "local" };
  }

  return {
    mode: "cognito",
    issuer: requiredAuthValue(runtimeAuth.issuer || env.issuer, "issuer"),
    clientId: requiredAuthValue(runtimeAuth.clientId || env.clientId, "clientId"),
  };
}

export function loadAuthSession(storage: Storage = window.localStorage): AuthSession | null {
  let stored = storage.getItem(SESSION_KEY);
  if (!stored && storage === window.localStorage) {
    // Keep users signed in after the storage change from sessionStorage to localStorage.
    const legacyStored = window.sessionStorage.getItem(SESSION_KEY);
    const migrated = parseAuthSession(legacyStored);
    if (migrated) {
      window.localStorage.setItem(SESSION_KEY, JSON.stringify(migrated));
      window.sessionStorage.removeItem(SESSION_KEY);
      return migrated;
    }
  } else if (storage === window.localStorage) {
    // A current session wins over and invalidates any stale legacy copy.
    window.sessionStorage.removeItem(SESSION_KEY);
  }
  return parseAuthSession(stored);
}

export function saveAuthSession(session: AuthSession, storage: Storage = window.localStorage): void {
  storage.setItem(SESSION_KEY, JSON.stringify(session));
  if (storage === window.localStorage) {
    window.sessionStorage.removeItem(SESSION_KEY);
  }
}

export function clearAuthSession(storage: Storage = window.localStorage): void {
  storage.removeItem(SESSION_KEY);
  storage.removeItem(PENDING_KEY);
  window.localStorage.removeItem(SESSION_KEY);
  window.localStorage.removeItem(PENDING_KEY);
  window.sessionStorage.removeItem(SESSION_KEY);
  window.sessionStorage.removeItem(PENDING_KEY);
}

export function isSessionActive(session: AuthSession | null, now = Date.now()): boolean {
  return Boolean(session && session.expiresAt - 30_000 > now);
}

export async function refreshAuthSession(
  config: Extract<AuthConfig, { mode: "cognito" }>,
  session: AuthSession,
  fetcher: typeof fetch = fetch,
): Promise<AuthSession> {
  if (!session.refreshToken) {
    throw new Error("Cognito session does not include a refresh token.");
  }
  const response = await cognitoRequest<CognitoAuthResponse>(
    config,
    "InitiateAuth",
    {
      AuthFlow: "REFRESH_TOKEN_AUTH",
      AuthParameters: { REFRESH_TOKEN: session.refreshToken },
      ClientId: config.clientId,
    },
    fetcher,
  );
  return buildCognitoSession(response.AuthenticationResult, session.refreshToken, session);
}

export async function beginEmailOtpSignIn(
  config: Extract<AuthConfig, { mode: "cognito" }>,
  email: string,
  fetcher: typeof fetch = fetch,
): Promise<Extract<EmailOtpChallenge, { kind: "sign-in" }>> {
  const normalizedEmail = normalizeEmail(email);
  const response = await cognitoRequest<CognitoAuthResponse>(
    config,
    "InitiateAuth",
    {
      AuthFlow: "USER_AUTH",
      AuthParameters: {
        USERNAME: normalizedEmail,
        PREFERRED_CHALLENGE: "EMAIL_OTP",
      },
      ClientId: config.clientId,
    },
    fetcher,
  );
  if (response.ChallengeName !== "EMAIL_OTP" || !response.Session) {
    throw new Error("Cognito did not start an email-code challenge.");
  }
  return { kind: "sign-in", email: normalizedEmail, session: response.Session };
}

export async function completeEmailOtpSignIn(
  config: Extract<AuthConfig, { mode: "cognito" }>,
  challenge: Extract<EmailOtpChallenge, { kind: "sign-in" }>,
  code: string,
  fetcher: typeof fetch = fetch,
): Promise<AuthSession> {
  const response = await cognitoRequest<CognitoAuthResponse>(
    config,
    "RespondToAuthChallenge",
    {
      ChallengeName: "EMAIL_OTP",
      ChallengeResponses: {
        USERNAME: challenge.email,
        EMAIL_OTP_CODE: code.trim(),
      },
      ClientId: config.clientId,
      Session: challenge.session,
    },
    fetcher,
  );
  return saveCognitoAuthentication(response.AuthenticationResult);
}

export async function beginEmailOtpRegistration(
  config: Extract<AuthConfig, { mode: "cognito" }>,
  email: string,
  fetcher: typeof fetch = fetch,
): Promise<EmailOtpChallenge> {
  const normalizedEmail = normalizeEmail(email);
  try {
    await cognitoRequest(
      config,
      "SignUp",
      {
        ClientId: config.clientId,
        Username: normalizedEmail,
        UserAttributes: [{ Name: "email", Value: normalizedEmail }],
      },
      fetcher,
    );
  } catch (error) {
    if (!(error instanceof Error) || error.name !== "UsernameExistsException") {
      throw error;
    }
    try {
      await resendEmailOtpRegistration(config, normalizedEmail, fetcher);
    } catch (resendError) {
      if (
        resendError instanceof Error &&
        resendError.name === "InvalidParameterException" &&
        /confirmed/i.test(resendError.message)
      ) {
        return beginEmailOtpSignIn(config, normalizedEmail, fetcher);
      }
      throw resendError;
    }
  }
  return { kind: "registration", email: normalizedEmail };
}

export async function completeEmailOtpRegistration(
  config: Extract<AuthConfig, { mode: "cognito" }>,
  challenge: Extract<EmailOtpChallenge, { kind: "registration" }>,
  code: string,
  fetcher: typeof fetch = fetch,
): Promise<AuthSession | EmailOtpChallenge> {
  const confirmation = await cognitoRequest<{ Session?: string }>(
    config,
    "ConfirmSignUp",
    {
      ClientId: config.clientId,
      Username: challenge.email,
      ConfirmationCode: code.trim(),
    },
    fetcher,
  );
  if (!confirmation.Session) {
    return beginEmailOtpSignIn(config, challenge.email, fetcher);
  }
  const response = await cognitoRequest<CognitoAuthResponse>(
    config,
    "InitiateAuth",
    {
      AuthFlow: "USER_AUTH",
      AuthParameters: {
        USERNAME: challenge.email,
        PREFERRED_CHALLENGE: "EMAIL_OTP",
      },
      ClientId: config.clientId,
      Session: confirmation.Session,
    },
    fetcher,
  );
  return saveCognitoAuthentication(response.AuthenticationResult);
}

export async function resendEmailOtpRegistration(
  config: Extract<AuthConfig, { mode: "cognito" }>,
  email: string,
  fetcher: typeof fetch = fetch,
): Promise<void> {
  await cognitoRequest(
    config,
    "ResendConfirmationCode",
    {
      ClientId: config.clientId,
      Username: normalizeEmail(email),
    },
    fetcher,
  );
}

function requiredAuthValue(value: string | undefined, fieldName: string): string {
  const stripped = value?.trim();
  if (!stripped) {
    throw new Error(`Cognito auth config is missing ${fieldName}.`);
  }
  return stripped;
}

async function cognitoRequest<T>(
  config: Extract<AuthConfig, { mode: "cognito" }>,
  operation: string,
  body: unknown,
  fetcher: typeof fetch,
): Promise<T> {
  const issuer = new URL(config.issuer);
  const response = await fetcher(`${issuer.origin}/`, {
    method: "POST",
    headers: {
      "content-type": "application/x-amz-json-1.1",
      "x-amz-target": `AWSCognitoIdentityProviderService.${operation}`,
    },
    body: JSON.stringify(body),
  });
  const payload = (await response.json()) as T & CognitoErrorPayload;
  if (!response.ok) {
    const errorType = payload.__type?.split("#").pop() || "CognitoError";
    const error = new Error(payload.message || payload.Message || "Cognito authentication failed.");
    error.name = errorType;
    throw error;
  }
  return payload;
}

function saveCognitoAuthentication(result: CognitoAuthenticationResult | undefined): AuthSession {
  const session = buildCognitoSession(result);
  saveAuthSession(session);
  return session;
}

function buildCognitoSession(
  result: CognitoAuthenticationResult | undefined,
  fallbackRefreshToken: string | null = null,
  previousSession: AuthSession | null = null,
): AuthSession {
  if (!result?.AccessToken) {
    throw new Error("Cognito did not return an authenticated session.");
  }
  return {
    accessToken: result.AccessToken,
    idToken: result.IdToken ?? previousSession?.idToken ?? null,
    refreshToken: result.RefreshToken ?? fallbackRefreshToken,
    tokenType: result.TokenType ?? "Bearer",
    expiresAt: Date.now() + (result.ExpiresIn ?? 3600) * 1000,
  };
}

function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

function parseAuthSession(stored: string | null): AuthSession | null {
  if (!stored) {
    return null;
  }
  try {
    const parsed = JSON.parse(stored) as Partial<AuthSession>;
    if (!parsed.accessToken || !parsed.expiresAt || !parsed.tokenType) {
      return null;
    }
    return {
      accessToken: parsed.accessToken,
      idToken: parsed.idToken ?? null,
      refreshToken: parsed.refreshToken ?? null,
      tokenType: parsed.tokenType,
      expiresAt: parsed.expiresAt,
    };
  } catch {
    return null;
  }
}

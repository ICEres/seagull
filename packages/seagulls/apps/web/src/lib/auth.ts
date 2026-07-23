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

export function loadAuthSession(storage: Storage = window.sessionStorage): AuthSession | null {
  if (storage === window.sessionStorage) {
    window.localStorage.removeItem(SESSION_KEY);
  }
  const stored = storage.getItem(SESSION_KEY);
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
      refreshToken: null,
      tokenType: parsed.tokenType,
      expiresAt: parsed.expiresAt,
    };
  } catch {
    return null;
  }
}

export function saveAuthSession(session: AuthSession, storage: Storage = window.sessionStorage): void {
  window.localStorage.removeItem(SESSION_KEY);
  storage.setItem(SESSION_KEY, JSON.stringify({ ...session, refreshToken: null }));
}

export function clearAuthSession(storage: Storage = window.sessionStorage): void {
  storage.removeItem(SESSION_KEY);
  storage.removeItem(PENDING_KEY);
  window.localStorage.removeItem(SESSION_KEY);
  window.localStorage.removeItem(PENDING_KEY);
}

export function isSessionActive(session: AuthSession | null, now = Date.now()): boolean {
  return Boolean(session && session.expiresAt - 30_000 > now);
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
  if (!result?.AccessToken) {
    throw new Error("Cognito did not return an authenticated session.");
  }
  const session: AuthSession = {
    accessToken: result.AccessToken,
    idToken: result.IdToken ?? null,
    refreshToken: null,
    tokenType: result.TokenType ?? "Bearer",
    expiresAt: Date.now() + (result.ExpiresIn ?? 3600) * 1000,
  };
  saveAuthSession(session);
  return session;
}

function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

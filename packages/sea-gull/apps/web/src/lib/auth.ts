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
      hostedDomain: string;
      clientId: string;
      redirectUri: string;
      logoutUri: string;
    };

export type AuthSession = {
  accessToken: string;
  idToken: string | null;
  refreshToken: string | null;
  tokenType: string;
  expiresAt: number;
};

type PendingLogin = {
  state: string;
  codeVerifier: string;
  createdAt: number;
};

type TokenPayload = {
  access_token?: string;
  id_token?: string;
  refresh_token?: string;
  token_type?: string;
  expires_in?: number;
  error?: string;
  error_description?: string;
};

const SESSION_KEY = "seagull.web.auth.session";
const PENDING_KEY = "seagull.web.auth.pending";
const OAUTH_SCOPE = "openid email profile";

export function configuredAuth(): AuthConfig {
  return authConfigFromRuntime(window.SEAGULL_CONFIG, {
    mode: import.meta.env.VITE_AUTH_MODE,
    issuer: import.meta.env.VITE_COGNITO_ISSUER,
    hostedDomain: import.meta.env.VITE_COGNITO_HOSTED_DOMAIN,
    clientId: import.meta.env.VITE_COGNITO_CLIENT_ID,
    redirectUri: import.meta.env.VITE_COGNITO_REDIRECT_URI,
    logoutUri: import.meta.env.VITE_COGNITO_LOGOUT_URI,
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
    hostedDomain: requiredAuthValue(runtimeAuth.hostedDomain || env.hostedDomain, "hostedDomain"),
    clientId: requiredAuthValue(runtimeAuth.clientId || env.clientId, "clientId"),
    redirectUri: requiredAuthValue(runtimeAuth.redirectUri || env.redirectUri, "redirectUri"),
    logoutUri: requiredAuthValue(runtimeAuth.logoutUri || env.logoutUri, "logoutUri"),
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

export async function beginHostedLogin(config: Extract<AuthConfig, { mode: "cognito" }>): Promise<string> {
  const state = randomBase64Url(24);
  const codeVerifier = randomBase64Url(48);
  const codeChallenge = await sha256Base64Url(codeVerifier);
  savePendingLogin({ state, codeVerifier, createdAt: Date.now() });
  return hostedAuthorizeUrl(config, state, codeChallenge);
}

export async function completeHostedCallback(
  config: Extract<AuthConfig, { mode: "cognito" }>,
  callbackUrl: string,
  fetcher: typeof fetch = fetch,
): Promise<AuthSession> {
  const callback = parseAuthCallbackUrl(callbackUrl);
  if (callback.error) {
    throw new Error(callback.errorDescription || callback.error);
  }
  if (!callback.code || !callback.state) {
    throw new Error("OAuth callback is missing code or state.");
  }

  const pending = loadPendingLogin();
  if (!pending || pending.state !== callback.state) {
    throw new Error("OAuth callback state does not match the pending login.");
  }

  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: config.clientId,
    code: callback.code,
    redirect_uri: config.redirectUri,
    code_verifier: pending.codeVerifier,
  });

  const response = await fetcher(`https://${config.hostedDomain}/oauth2/token`, {
    method: "POST",
    headers: {
      "content-type": "application/x-www-form-urlencoded",
    },
    body,
  });
  const payload = (await response.json()) as TokenPayload;
  if (!response.ok || !payload.access_token) {
    throw new Error(payload.error_description || payload.error || "Token exchange failed.");
  }

  const session: AuthSession = {
    accessToken: payload.access_token,
    idToken: payload.id_token ?? null,
    refreshToken: null,
    tokenType: payload.token_type ?? "Bearer",
    expiresAt: Date.now() + (payload.expires_in ?? 3600) * 1000,
  };
  saveAuthSession(session);
  clearPendingLogin();
  return session;
}

export function hostedAuthorizeUrl(
  config: Extract<AuthConfig, { mode: "cognito" }>,
  state: string,
  codeChallenge: string,
): string {
  const url = new URL(`https://${config.hostedDomain}/oauth2/authorize`);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("redirect_uri", config.redirectUri);
  url.searchParams.set("scope", OAUTH_SCOPE);
  url.searchParams.set("state", state);
  url.searchParams.set("code_challenge", codeChallenge);
  url.searchParams.set("code_challenge_method", "S256");
  return url.toString();
}

export function hostedLogoutUrl(config: Extract<AuthConfig, { mode: "cognito" }>): string {
  const url = new URL(`https://${config.hostedDomain}/logout`);
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("logout_uri", config.logoutUri);
  return url.toString();
}

export function parseAuthCallbackUrl(url: string): {
  code: string | null;
  state: string | null;
  error: string | null;
  errorDescription: string | null;
} {
  const parsed = new URL(url);
  return {
    code: parsed.searchParams.get("code"),
    state: parsed.searchParams.get("state"),
    error: parsed.searchParams.get("error"),
    errorDescription: parsed.searchParams.get("error_description"),
  };
}

function savePendingLogin(pending: PendingLogin, storage: Storage = window.sessionStorage): void {
  window.localStorage.removeItem(PENDING_KEY);
  storage.setItem(PENDING_KEY, JSON.stringify(pending));
}

function loadPendingLogin(storage: Storage = window.sessionStorage): PendingLogin | null {
  const stored = storage.getItem(PENDING_KEY);
  if (!stored) {
    return null;
  }
  try {
    const parsed = JSON.parse(stored) as Partial<PendingLogin>;
    if (!parsed.state || !parsed.codeVerifier || !parsed.createdAt) {
      return null;
    }
    return {
      state: parsed.state,
      codeVerifier: parsed.codeVerifier,
      createdAt: parsed.createdAt,
    };
  } catch {
    return null;
  }
}

function clearPendingLogin(storage: Storage = window.sessionStorage): void {
  storage.removeItem(PENDING_KEY);
  window.localStorage.removeItem(PENDING_KEY);
}

function randomBase64Url(byteLength: number): string {
  const bytes = new Uint8Array(byteLength);
  window.crypto.getRandomValues(bytes);
  return bytesToBase64Url(bytes);
}

async function sha256Base64Url(value: string): Promise<string> {
  const digest = await window.crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return bytesToBase64Url(new Uint8Array(digest));
}

function bytesToBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return window
    .btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function requiredAuthValue(value: string | undefined, fieldName: string): string {
  const stripped = value?.trim();
  if (!stripped) {
    throw new Error(`Cognito auth config is missing ${fieldName}.`);
  }
  return stripped;
}

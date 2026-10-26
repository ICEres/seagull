import { LogOut, Moon, Settings, Sun } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Wing,
  YOUR_WING,
  applyTheme,
  loadThemePreference,
  resolveTheme,
  saveThemePreference,
  type ThemePreference,
} from "@seagulls/ui";

import { LoginPage } from "./components/auth-pages";
import { DesktopLoginPage } from "./components/desktop-login-page";
import { AiUsagePage } from "./components/ai-usage-page";
import { ChatPage } from "./components/chat-page";
import { FlockPage } from "./components/flock-page";
import { ServerPage } from "./components/server-page";
import { SkyPage } from "./components/sky-page";
import { WorkPage } from "./components/work-page";
import { NoticeBanner, ProtectedRoute, identityName, type Notice } from "./components/shared";
import { SocialApiClient, SocialApiError } from "./lib/api";
import { configuredAiProviderApiUrl } from "./lib/ai-provider";
import {
  clearAuthSession,
  configuredAuth,
  isSessionActive,
  loadAuthSession,
  refreshAuthSession,
  saveAuthSession,
  type AuthSession,
} from "./lib/auth";
import { createFirstLoop } from "./lib/demo";
import { configuredMessageApiUrl, MessageHubClient } from "./lib/message-hub";
import type { AgentProfile, HumanIdentity, LoopState, ModerationRecord, Post } from "./lib/social";
import {
  clearLoopState,
  loadLoopState,
  mergePosts,
  saveLoopState,
  touchLoopState,
} from "./lib/state";

type AppMutationError = Error | SocialApiError;

const NAV_ITEMS: Array<{ to: string; label: string }> = [
  { to: "/sky", label: "Sky" },
  { to: "/chat", label: "Chat" },
  // Work is the Agent Request surface: requests, delegation, and results.
  { to: "/work", label: "Work" },
  { to: "/flock", label: "Flock" },
  { to: "/server", label: "Server" },
];

export default function App() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const authConfig = useMemo(() => configuredAuth(), []);
  const [authSession, setAuthSession] = useState<AuthSession | null>(() => loadAuthSession());
  const [authRefreshError, setAuthRefreshError] = useState<Error | null>(null);
  const [authRefreshRetry, setAuthRefreshRetry] = useState(0);
  const rejectedRefreshToken = useRef<string | null>(null);
  const [state, setState] = useState<LoopState>(() => loadLoopState());
  const [notice, setNotice] = useState<Notice | null>(null);
  const [themePreference, setThemePreference] = useState<ThemePreference>(() => loadThemePreference());
  const messageApiUrl = useMemo(() => configuredMessageApiUrl(), []);
  const aiProviderApiUrl = useMemo(() => configuredAiProviderApiUrl(), []);
  const adminDomainName = window.SEAGULL_CONFIG?.adminDomainName?.trim() ?? "";
  const defaultAuthenticatedPath =
    adminDomainName && window.location.hostname === adminDomainName ? "/server" : "/sky";
  const activeAuthSession =
    authConfig.mode === "cognito" && isSessionActive(authSession) ? authSession : null;
  const isAuthenticated =
    authConfig.mode === "local" ? Boolean(state.activeUser) : Boolean(activeAuthSession);
  const resolvedTheme = resolveTheme(themePreference);
  const resetAuthenticatedState = useCallback(() => {
    clearAuthSession();
    queryClient.clear();
    setAuthSession(null);
    setAuthRefreshError(null);
    rejectedRefreshToken.current = null;
    setState(clearLoopState());
  }, [queryClient]);

  useEffect(() => {
    applyTheme(themePreference);
    if (themePreference !== "system" || !window.matchMedia) {
      return;
    }
    // Follow OS theme changes while the preference is "system".
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    media.addEventListener?.("change", onChange);
    return () => media.removeEventListener?.("change", onChange);
  }, [themePreference]);

  useEffect(() => {
    saveLoopState(state);
  }, [state]);

  useEffect(() => {
    if (authConfig.mode !== "cognito" || !authSession) {
      return;
    }
    const config = authConfig;
    const session = authSession;
    let cancelled = false;
    let refreshing = false;
    let timer: ReturnType<typeof setTimeout>;
    const isCurrentSession = () => {
      const saved = loadAuthSession();
      return saved?.accessToken === session.accessToken && saved.refreshToken === session.refreshToken;
    };
    const schedule = (delay: number) => {
      clearTimeout(timer);
      timer = setTimeout(() => void refresh(), delay);
    };
    async function refresh() {
      if (cancelled || refreshing || !isCurrentSession()) {
        return;
      }
      const remaining = session.expiresAt - Date.now();
      const refreshBefore = session.refreshToken ? 60_000 : 30_000;
      if (remaining > refreshBefore) {
        schedule(remaining - refreshBefore);
        return;
      }
      if (!session.refreshToken) {
        resetAuthenticatedState();
        setNotice({ tone: "warn", message: "Session expired. Please sign in again." });
        return;
      }
      refreshing = true;
      try {
        const renewed = await refreshAuthSession(config, session);
        if (cancelled || !isCurrentSession()) {
          return;
        }
        saveAuthSession(renewed);
        setAuthSession(renewed);
        setAuthRefreshError(null);
      } catch (error) {
        if (cancelled || !isCurrentSession()) {
          return;
        }
        if (error instanceof Error && ["NotAuthorizedException", "UserNotFoundException"].includes(error.name)) {
          resetAuthenticatedState();
          setNotice({ tone: "warn", message: "Session expired. Please sign in again." });
        } else {
          setAuthRefreshError(new Error("We couldn’t reconnect. We’ll try again when your connection is back."));
          schedule(30_000);
        }
      } finally {
        refreshing = false;
      }
    }
    const onResume = () => {
      if (document.visibilityState !== "hidden") {
        void refresh();
      }
    };
    void refresh();
    window.addEventListener("focus", onResume);
    window.addEventListener("online", onResume);
    document.addEventListener("visibilitychange", onResume);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      window.removeEventListener("focus", onResume);
      window.removeEventListener("online", onResume);
      document.removeEventListener("visibilitychange", onResume);
    };
  }, [authConfig, authSession, authRefreshRetry, resetAuthenticatedState]);

  useEffect(() => {
    if (authConfig.mode !== "cognito") {
      return;
    }
    const onStorage = (event: StorageEvent) => {
      if (event.storageArea !== window.localStorage || (event.key !== null && event.key !== "seagull.web.auth.session")) {
        return;
      }
      const saved = loadAuthSession();
      if (!saved || !saved.refreshToken || saved.refreshToken !== authSession?.refreshToken) {
        queryClient.clear();
        setState(clearLoopState());
      }
      setAuthSession(saved);
      setAuthRefreshError(null);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [authConfig.mode, authSession?.refreshToken, queryClient]);

  const api = useMemo(
    () => new SocialApiClient(state.apiUrl, activeAuthSession?.accessToken ?? null),
    [state.apiUrl, activeAuthSession?.accessToken],
  );
  const messageApi = useMemo(
    () => new MessageHubClient(messageApiUrl, activeAuthSession?.accessToken ?? null),
    [messageApiUrl, activeAuthSession?.accessToken],
  );

  const healthQuery = useQuery({
    queryKey: ["social-health", state.apiUrl],
    queryFn: () => api.health(),
  });

  const messageHealthQuery = useQuery({
    queryKey: ["message-health", messageApiUrl],
    queryFn: () => messageApi.health(),
  });

  const dashboardQuery = useQuery({
    queryKey: ["social-dashboard", state.apiUrl, activeAuthSession?.accessToken],
    queryFn: () => api.getDashboard(),
    enabled: Boolean(authConfig.mode === "cognito" && activeAuthSession),
  });

  const feedQuery = useQuery({
    queryKey: ["social-feed", state.apiUrl, state.activeUser?.user_id],
    queryFn: () => api.getFeed(state.activeUser!.user_id, 50),
    enabled: Boolean(isAuthenticated && state.activeUser),
  });

  const profilesQuery = useQuery({
    queryKey: ["social-profiles", state.apiUrl, state.activeUser?.user_id],
    queryFn: () =>
      api.getProfiles(authConfig.mode === "local" ? state.activeUser!.user_id : undefined),
    enabled: Boolean(isAuthenticated && state.activeUser),
  });

  const activeNotificationsQuery = useQuery({
    queryKey: [
      "social-notifications",
      state.apiUrl,
      state.activeProfile?.handle,
      state.activeUser?.user_id,
    ],
    queryFn: () => api.getNotifications(state.activeProfile!.handle, state.activeUser!.user_id, 50),
    enabled: Boolean(isAuthenticated && state.activeProfile && state.activeUser),
  });

  const reviewNotificationsQuery = useQuery({
    queryKey: [
      "social-notifications",
      state.apiUrl,
      state.reviewProfile?.handle,
      state.reviewUser?.user_id,
    ],
    queryFn: () => api.getNotifications(state.reviewProfile!.handle, state.reviewUser!.user_id, 50),
    enabled: Boolean(isAuthenticated && state.reviewProfile && state.reviewUser),
  });

  const moderationQuery = useQuery({
    queryKey: ["social-moderation", state.apiUrl],
    queryFn: () => api.listModerationRecords(50),
    enabled: isAuthenticated,
  });

  const posts = useMemo(
    () => mergePosts(feedQuery.data?.items, state.posts),
    [feedQuery.data?.items, state.posts],
  );
  const loadedProfiles = profilesQuery.data?.items;
  const loadedProfileIds = loadedProfiles?.map((profile) => profile.agent_id).join("|") ?? "";
  const dashboardProfileIds =
    dashboardQuery.data?.profiles.items.map((profile) => profile.agent_id).join("|") ?? "";

  useEffect(() => {
    if (!loadedProfiles) {
      return;
    }
    setState((current) => {
      const activeProfile =
        current.activeProfile && loadedProfiles.some((profile) => profile.agent_id === current.activeProfile?.agent_id)
          ? current.activeProfile
          : loadedProfiles[0] ?? null;
      return touchLoopState({
        ...current,
        ownedProfiles: loadedProfiles,
        activeProfile,
      });
    });
  }, [loadedProfileIds]);

  const seedMutation = useMutation({
    mutationFn: () => createFirstLoop(api),
    onSuccess: (nextState) => {
      setState(nextState);
      setNotice({ tone: "ok", message: "First social loop created." });
      void queryClient.invalidateQueries({ queryKey: ["social-feed"] });
      void queryClient.invalidateQueries({ queryKey: ["social-notifications"] });
      void queryClient.invalidateQueries({ queryKey: ["social-moderation"] });
      navigate("/sky");
    },
    onError: (error: AppMutationError) => {
      setNotice({ tone: "error", message: error.message });
    },
  });

  function applyApiUrl(nextUrl: string) {
    setState((current) => touchLoopState({ ...current, apiUrl: nextUrl }));
    setNotice({ tone: "ok", message: "API endpoint updated." });
    void queryClient.invalidateQueries();
  }

  function clearSession() {
    const nextState = clearLoopState();
    setState(nextState);
    setNotice({ tone: "warn", message: "Local browser state cleared." });
    navigate("/");
  }

  function rememberUser(identity: HumanIdentity, ownedProfiles: AgentProfile[] = []) {
    setState((current) =>
      touchLoopState({
        ...current,
        activeUser: identity,
        reviewUser: null,
        activeProfile: ownedProfiles[0] ?? null,
        reviewProfile: null,
        ownedProfiles,
        room: null,
        membership: null,
        follow: null,
        posts: [],
        selectedPostId: null,
        moderation: null,
      }),
    );
    void queryClient.invalidateQueries({ queryKey: ["social-profiles"] });
    void queryClient.invalidateQueries({ queryKey: ["social-feed"] });
    void queryClient.invalidateQueries({ queryKey: ["social-notifications"] });
    void queryClient.invalidateQueries({ queryKey: ["social-moderation"] });
  }

  useEffect(() => {
    if (authConfig.mode !== "cognito" || !activeAuthSession || !dashboardQuery.data) {
      return;
    }
    rejectedRefreshToken.current = null;
    const identity = dashboardQuery.data.identity;
    const ownedProfiles = dashboardQuery.data.profiles.items;
    const currentProfileIds = state.ownedProfiles.map((profile) => profile.agent_id).join("|");
    if (state.activeUser?.user_id === identity.user_id && currentProfileIds === dashboardProfileIds) {
      return;
    }
    rememberUser(identity, ownedProfiles);
  }, [
    authConfig.mode,
    activeAuthSession?.accessToken,
    dashboardQuery.data?.identity.user_id,
    dashboardProfileIds,
    state.activeUser?.user_id,
  ]);

  useEffect(() => {
    if (authConfig.mode !== "cognito" || !activeAuthSession || !dashboardQuery.error) {
      return;
    }
    const error = dashboardQuery.error;
    const isAuthError = error instanceof SocialApiError && (error.status === 401 || error.status === 403);
    if (isAuthError) {
      if (activeAuthSession.refreshToken && rejectedRefreshToken.current !== activeAuthSession.refreshToken) {
        rejectedRefreshToken.current = activeAuthSession.refreshToken;
        setAuthSession({ ...activeAuthSession, expiresAt: Date.now() });
        return;
      }
      resetAuthenticatedState();
      setNotice({ tone: "error", message: "Your session expired. Please sign in again." });
      return;
    }
    setNotice({
      tone: "error",
      message: error instanceof Error ? error.message : "Could not load your sky.",
    });
  }, [authConfig.mode, activeAuthSession?.accessToken, dashboardQuery.error, resetAuthenticatedState]);

  function signOut() {
    resetAuthenticatedState();
    setNotice({ tone: "warn", message: "Signed out." });
    navigate("/login");
  }

  function rememberPost(post: Post, selectedPostId = post.post_id) {
    setState((current) =>
      touchLoopState({
        ...current,
        posts: mergePosts([post], current.posts),
        selectedPostId,
      }),
    );
  }

  function toggleTheme() {
    const next: ThemePreference = resolvedTheme === "dark" ? "light" : "dark";
    setThemePreference(next);
    saveThemePreference(next);
  }

  const notifications = [
    ...(activeNotificationsQuery.data?.items ?? []),
    ...(reviewNotificationsQuery.data?.items ?? []),
  ];
  const dashboardSummary = dashboardQuery.data;
  const dashboardProfiles = dashboardSummary?.profiles.items ?? loadedProfiles ?? state.ownedProfiles;
  const dashboardPosts = dashboardSummary
    ? mergePosts(dashboardSummary.feed.items, state.posts)
    : posts;
  const dashboardNotifications = dashboardSummary?.notifications.items ?? notifications;
  const moderationRecords: ModerationRecord[] =
    dashboardSummary?.moderation.items ?? moderationQuery.data?.items ?? [];
  const unreadMentions =
    dashboardSummary?.notifications.unread_count ??
    notifications.filter((notification) => !notification.read_at).length;

  if (authConfig.mode === "cognito" && authSession?.refreshToken && !activeAuthSession) {
    return (
      <main className="grid min-h-screen place-content-center justify-items-center gap-4 px-6 text-center">
        <Wing path={YOUR_WING} size={32} strokeWidth={2.5} className="text-accent" />
        <h1 className="m-0 text-xl font-extrabold">Restoring your session<span className="text-accent">.</span></h1>
        <p role="status" className="m-0 max-w-sm text-sm text-muted">
          {authRefreshError?.message ?? "Signing you in automatically…"}
        </p>
        {authRefreshError ? (
          <button
            type="button"
            className="rounded-lg border-0 bg-accent px-4 py-2 font-bold text-white"
            onClick={() => {
              setAuthRefreshError(null);
              setAuthRefreshRetry((attempt) => attempt + 1);
            }}
          >
            Try again
          </button>
        ) : null}
        <button type="button" className="border-0 bg-transparent text-sm text-muted hover:text-accent" onClick={resetAuthenticatedState}>
          Sign in with another account
        </button>
      </main>
    );
  }

  if (location.pathname === "/desktop/login") {
    return (
      <main className="min-h-screen">
        <DesktopLoginPage
          api={api}
          authConfig={authConfig}
          authSession={activeAuthSession}
          isAuthenticated={isAuthenticated}
          resolvedTheme={resolvedTheme}
          onToggleTheme={toggleTheme}
          onLocalIdentity={(identity) => rememberUser(identity)}
          onAuthSession={setAuthSession}
          onNotice={setNotice}
        />
      </main>
    );
  }

  if (!isAuthenticated) {
    return (
      <main className="min-h-screen">
        {notice ? (
          <div className="fixed top-4 left-1/2 z-20 w-[min(480px,90vw)] -translate-x-1/2">
            <NoticeBanner notice={notice} onClose={() => setNotice(null)} />
          </div>
        ) : null}
        <Routes>
          <Route index element={<Navigate to="/login" replace />} />
          <Route
            path="/login"
            element={
              <LoginPage
                api={api}
                authConfig={authConfig}
                isAuthenticated={isAuthenticated}
                postAuthPath={defaultAuthenticatedPath}
                resolvedTheme={resolvedTheme}
                onToggleTheme={toggleTheme}
                onLocalIdentity={(identity) => rememberUser(identity)}
                onAuthSession={setAuthSession}
                onNotice={setNotice}
              />
            }
          />
          <Route path="/register" element={<Navigate to="/login" replace />} />
          <Route path="/auth/callback" element={<Navigate to="/login" replace />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </main>
    );
  }

  const skyCount = unreadMentions;
  const settingsCurrent = location.pathname === "/settings";

  return (
    <div className="grid min-h-screen grid-cols-[208px_minmax(0,1fr)] max-[860px]:grid-cols-1">
      <aside className="sticky top-0 box-border flex h-screen flex-col gap-8 border-r border-line px-3.5 pt-6 pb-5 max-[860px]:static max-[860px]:h-auto max-[860px]:flex-row max-[860px]:flex-wrap max-[860px]:items-center max-[860px]:gap-4 max-[860px]:border-r-0 max-[860px]:border-b max-[860px]:py-3">
        <div className="flex items-center gap-2.5 px-2.5">
          <span className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-accent text-[0.85rem] font-black text-white">
            S
          </span>
          <strong className="font-extrabold tracking-[-0.01em] max-[860px]:hidden">seagulls</strong>
        </div>

        <nav aria-label="Primary" className="grid gap-0.5 max-[860px]:order-last max-[860px]:w-full max-[860px]:min-w-0 max-[860px]:grid-cols-3 max-[860px]:gap-1">
          {NAV_ITEMS.map((item) => {
            const current = location.pathname === item.to || location.pathname.startsWith(`${item.to}/`);
            return (
              <button
                key={item.to}
                type="button"
                onClick={() => {
                  navigate(item.to);
                  window.scrollTo(0, 0);
                }}
                aria-current={current ? "page" : undefined}
                className={`flex min-h-10 shrink-0 items-center gap-2 rounded-lg border-0 bg-transparent px-2.5 text-left text-[0.94rem] font-extrabold whitespace-nowrap hover:text-accent-strong ${
                  current ? "text-ink" : "text-muted"
                }`}
              >
                <span aria-hidden="true" className="grid w-5 flex-none justify-items-center">
                  {current ? <Wing path={YOUR_WING} size={16} strokeWidth={3.2} className="text-ink" /> : null}
                </span>
                <span className="flex-1">{item.label}</span>
                {item.to === "/sky" && skyCount > 0 ? (
                  <span className="grid min-w-5 place-items-center rounded-full bg-accent-soft px-1.5 py-0 text-[0.7rem] font-black text-accent-strong">
                    {skyCount}
                  </span>
                ) : null}
              </button>
            );
          })}
        </nav>

        <div className="mt-auto grid gap-3.5 max-[860px]:mt-0 max-[860px]:ml-auto max-[860px]:flex max-[860px]:items-center">
          {state.activeUser ? (
            <div className="flex min-h-11 min-w-0 items-center gap-2.5 px-2.5 py-1.5 max-[860px]:px-0">
              <span className="grid h-8 w-8 flex-none place-items-center rounded-full bg-ink text-bg">
                <Wing path={YOUR_WING} size={16} strokeWidth={3.2} />
              </span>
              <span className="min-w-0 flex-1 max-[860px]:hidden">
                <strong className="block overflow-hidden text-[0.88rem] text-ellipsis whitespace-nowrap">
                  {identityName(state.activeUser, activeAuthSession?.idToken)}
                </strong>
                <span className="block text-[0.74rem] font-bold whitespace-nowrap text-faint">human · your gull</span>
              </span>
            </div>
          ) : null}
          {authConfig.mode === "local" ? (
            <div className="grid gap-1 px-1.5 max-[860px]:hidden">
              <button
                type="button"
                onClick={() => seedMutation.mutate()}
                disabled={seedMutation.isPending}
                className="min-h-8 rounded-lg border-0 bg-transparent px-1.5 text-left text-[0.78rem] font-extrabold text-faint hover:text-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
              >
                {seedMutation.isPending ? "Seeding…" : "Seed demo loop"}
              </button>
              <button
                type="button"
                onClick={clearSession}
                className="min-h-8 rounded-lg border-0 bg-transparent px-1.5 text-left text-[0.78rem] font-extrabold text-faint hover:text-accent-strong"
              >
                Clear local state
              </button>
            </div>
          ) : null}
          <div className="flex items-center gap-1.5 px-1.5">
            <button
              type="button"
              onClick={toggleTheme}
              aria-label="Toggle dark mode"
              title="Toggle dark mode"
              className="grid h-9 w-9 flex-none place-items-center rounded-lg border-0 bg-transparent text-muted hover:bg-accent-soft hover:text-accent-strong focus-visible:outline-2 focus-visible:outline-accent"
            >
              {resolvedTheme === "dark" ? <Sun size={16} strokeWidth={1.8} aria-hidden="true" /> : <Moon size={16} strokeWidth={1.8} aria-hidden="true" />}
            </button>
            {state.activeUser ? (
              <button
                type="button"
                aria-label="Settings"
                title="Settings"
                aria-current={settingsCurrent ? "page" : undefined}
                onClick={() => {
                  navigate("/settings");
                  window.scrollTo(0, 0);
                }}
                className={`grid h-9 w-9 flex-none place-items-center rounded-lg border-0 transition-colors hover:bg-accent-soft hover:text-accent-strong focus-visible:outline-2 focus-visible:outline-accent ${
                  settingsCurrent ? "bg-accent-soft text-accent-strong" : "bg-transparent text-muted"
                }`}
              >
                <Settings size={16} strokeWidth={1.8} aria-hidden="true" />
              </button>
            ) : null}
            <button
              type="button"
              onClick={signOut}
              aria-label="Sign out"
              title="Sign out"
              className="grid h-9 w-9 flex-none place-items-center rounded-lg border-0 bg-transparent text-muted hover:bg-accent-soft hover:text-accent-strong focus-visible:outline-2 focus-visible:outline-accent"
            >
              <LogOut size={16} strokeWidth={1.8} aria-hidden="true" />
            </button>
          </div>
        </div>
      </aside>

      <main className="box-border min-w-0 px-11 pt-9 pb-16 max-[860px]:px-4 max-[860px]:pt-5">
        {notice ? <NoticeBanner notice={notice} onClose={() => setNotice(null)} /> : null}

        <Routes>
          <Route index element={<Navigate to={defaultAuthenticatedPath} replace />} />
          <Route path="/login" element={<Navigate to={defaultAuthenticatedPath} replace />} />
          <Route path="/register" element={<Navigate to={defaultAuthenticatedPath} replace />} />
          <Route path="/auth/callback" element={<Navigate to={defaultAuthenticatedPath} replace />} />
          <Route
            path="/sky"
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated}>
                <SkyPage
                  api={api}
                  messageApi={messageApi}
                  state={state}
                  posts={dashboardPosts}
                  profiles={dashboardProfiles}
                  notifications={dashboardNotifications}
                  rememberPost={rememberPost}
                  onNotice={setNotice}
                />
              </ProtectedRoute>
            }
          />
          <Route
            path="/chat"
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated}>
                <ChatPage api={api} messageApi={messageApi} state={state} profiles={dashboardProfiles} onNotice={setNotice} />
              </ProtectedRoute>
            }
          />
          <Route
            path="/chat/:chatId"
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated}>
                <ChatPage api={api} messageApi={messageApi} state={state} profiles={dashboardProfiles} onNotice={setNotice} />
              </ProtectedRoute>
            }
          />
          <Route
            path="/flock"
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated}>
                <FlockPage
                  api={api}
                  state={state}
                  setState={setState}
                  profiles={dashboardProfiles}
                  onNotice={setNotice}
                />
              </ProtectedRoute>
            }
          />
          <Route
            path="/work"
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated}>
                <WorkPage
                  messageApi={messageApi}
                  profiles={dashboardProfiles}
                  onNotice={setNotice}
                />
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings"
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated}>
                <AiUsagePage api={api} state={state} profiles={dashboardProfiles} />
              </ProtectedRoute>
            }
          />
          <Route
            path="/server"
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated}>
                <ServerPage
                  aiProviderApiUrl={aiProviderApiUrl}
                  authToken={activeAuthSession?.accessToken ?? null}
                  messageApi={messageApi}
                  profiles={dashboardProfiles}
                  moderationRecords={moderationRecords}
                  socialHealth={healthQuery.data}
                  messageHealth={messageHealthQuery.data}
                  apiUrl={state.apiUrl}
                  onApplyApiUrl={applyApiUrl}
                  onNotice={setNotice}
                />
              </ProtectedRoute>
            }
          />

          {/* Legacy routes from the previous design */}
          <Route path="/ai-usage" element={<Navigate to="/settings" replace />} />
          <Route path="/dashboard" element={<Navigate to="/sky" replace />} />
          <Route path="/feed" element={<Navigate to="/sky" replace />} />
          <Route path="/inbox" element={<Navigate to="/sky" replace />} />
          <Route path="/agent-inbox" element={<Navigate to="/sky" replace />} />
          <Route path="/threads/:postId" element={<Navigate to="/sky" replace />} />
          <Route path="/rooms/:slug" element={<Navigate to="/sky" replace />} />
          <Route path="/profiles/:handle" element={<Navigate to="/flock" replace />} />
          <Route path="/routing" element={<Navigate to="/server" replace />} />
          <Route path="/admin" element={<Navigate to="/server" replace />} />
          <Route path="*" element={<Navigate to={defaultAuthenticatedPath} replace />} />
        </Routes>
      </main>
    </div>
  );
}

import {
  Activity,
  Bell,
  DoorOpen,
  Flag,
  GitBranch,
  Home,
  Inbox,
  LayoutDashboard,
  LogIn,
  LogOut,
  MessageCircle,
  MessagesSquare,
  RefreshCw,
  Route as RouteIcon,
  Settings,
  Trash2,
  UserRound,
  WandSparkles,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { LoginPage, RegisterPage } from "./components/auth-pages";
import { AdminPage } from "./components/admin-pages";
import { DashboardPage } from "./components/dashboard-page";
import { AgentLifecycleInboxPage, RoutingRulesPage } from "./components/message-lifecycle-pages";
import {
  ChatPage,
  FeedPage,
  InboxPage,
  ProfilePage,
  RoomPage,
  ThreadPage,
} from "./components/social-pages";
import {
  NavItem,
  NoticeBanner,
  ProtectedRoute,
  StatusPill,
  type Notice,
} from "./components/shared";
import { SocialApiClient, SocialApiError, trimBaseUrl } from "./lib/api";
import { configuredAiProviderApiUrl } from "./lib/ai-provider";
import {
  clearAuthSession,
  completeHostedCallback,
  configuredAuth,
  hostedLogoutUrl,
  isSessionActive,
  loadAuthSession,
  type AuthConfig,
  type AuthSession,
} from "./lib/auth";
import { createFirstLoop } from "./lib/demo";
import { configuredMessageApiUrl, MessageHubClient } from "./lib/message-hub";
import type {
  AgentProfile,
  HumanIdentity,
  LoopState,
  ModerationRecord,
  Post,
} from "./lib/social";
import {
  clearLoopState,
  loadLoopState,
  mergePosts,
  routeHandle,
  saveLoopState,
  touchLoopState,
} from "./lib/state";

type AppMutationError = Error | SocialApiError;

function AuthCallbackPage({
  authConfig,
  postAuthPath,
  onSession,
  onNotice,
}: {
  authConfig: AuthConfig;
  postAuthPath: string;
  onSession: (session: AuthSession) => void;
  onNotice: (notice: Notice) => void;
}) {
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    if (authConfig.mode !== "cognito") {
      onNotice({ tone: "error", message: "Cognito auth is not configured." });
      navigate("/login", { replace: true });
      return;
    }

    const callbackUrl = `${window.location.origin}${location.pathname}${location.search}`;
    let cancelled = false;

    void completeHostedCallback(authConfig, callbackUrl)
      .then((session) => {
        if (cancelled) {
          return;
        }
        onSession(session);
        onNotice({ tone: "ok", message: "Signed in." });
        navigate(postAuthPath, { replace: true });
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return;
        }
        clearAuthSession();
        onNotice({ tone: "error", message: error instanceof Error ? error.message : "Sign in failed." });
        navigate("/login", { replace: true });
      });

    return () => {
      cancelled = true;
    };
  }, [authConfig, location.pathname, location.search, navigate, onNotice, onSession, postAuthPath]);

  return (
    <section className="grid min-h-40 place-items-center rounded-lg border border-line bg-surface px-[22px] py-8 shadow-panel">
      <div className="inline-flex items-center gap-2 font-extrabold text-ink">
        <LogIn size={18} />
        Signing in
      </div>
    </section>
  );
}

export default function App() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const authConfig = useMemo(() => configuredAuth(), []);
  const [authSession, setAuthSession] = useState<AuthSession | null>(() => loadAuthSession());
  const [state, setState] = useState<LoopState>(() => loadLoopState());
  const [apiDraft, setApiDraft] = useState(state.apiUrl);
  const [notice, setNotice] = useState<Notice | null>(null);
  const messageApiUrl = useMemo(() => configuredMessageApiUrl(), []);
  const aiProviderApiUrl = useMemo(() => configuredAiProviderApiUrl(), []);
  const adminDomainName = window.SEAGULL_CONFIG?.adminDomainName?.trim() ?? "";
  const defaultAuthenticatedPath =
    adminDomainName && window.location.hostname === adminDomainName ? "/admin" : "/dashboard";
  const activeAuthSession =
    authConfig.mode === "cognito" && isSessionActive(authSession) ? authSession : null;
  const isAuthenticated =
    authConfig.mode === "local" ? Boolean(state.activeUser) : Boolean(activeAuthSession);

  useEffect(() => {
    saveLoopState(state);
  }, [state]);

  useEffect(() => {
    if (authConfig.mode === "cognito" && authSession && !isSessionActive(authSession)) {
      clearAuthSession();
      setAuthSession(null);
      setNotice({ tone: "warn", message: "Session expired. Please sign in again." });
    }
  }, [authConfig.mode, authSession]);

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
      setApiDraft(nextState.apiUrl);
      setNotice({ tone: "ok", message: "First social loop created." });
      void queryClient.invalidateQueries({ queryKey: ["social-feed"] });
      void queryClient.invalidateQueries({ queryKey: ["social-notifications"] });
      void queryClient.invalidateQueries({ queryKey: ["social-moderation"] });
      if (nextState.selectedPostId) {
        navigate(`/threads/${nextState.selectedPostId}`);
      }
    },
    onError: (error: AppMutationError) => {
      setNotice({ tone: "error", message: error.message });
    },
  });

  function updateApiUrl(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextUrl = trimBaseUrl(apiDraft);
    setState((current) => touchLoopState({ ...current, apiUrl: nextUrl }));
    setNotice({ tone: "ok", message: "API endpoint updated." });
    void queryClient.invalidateQueries();
  }

  function clearSession() {
    const nextState = clearLoopState();
    setState(nextState);
    setApiDraft(nextState.apiUrl);
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
    if (authConfig.mode !== "cognito" || !dashboardQuery.error) {
      return;
    }
    const error = dashboardQuery.error;
    // Only sign the user out when the session is actually invalid (401/403). A
    // transient network error or a 5xx must not destroy a valid session.
    const isAuthError = error instanceof SocialApiError && (error.status === 401 || error.status === 403);
    if (isAuthError) {
      clearAuthSession();
      setAuthSession(null);
      setNotice({ tone: "error", message: "Your session expired. Please sign in again." });
      return;
    }
    setNotice({
      tone: "error",
      message: error instanceof Error ? error.message : "Could not load your dashboard.",
    });
  }, [authConfig.mode, dashboardQuery.error]);

  function signOut() {
    clearAuthSession();
    setAuthSession(null);
    const nextState = clearLoopState();
    setState(nextState);
    setApiDraft(nextState.apiUrl);
    if (authConfig.mode === "cognito") {
      // Also end the Cognito Hosted UI session; otherwise the next sign-in
      // silently re-authenticates the same user without a real login.
      window.location.assign(hostedLogoutUrl(authConfig));
      return;
    }
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

  function rememberModeration(record: ModerationRecord) {
    setState((current) => touchLoopState({ ...current, moderation: record }));
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
  const dashboardModerationRecords = dashboardSummary?.moderation.items ?? moderationQuery.data?.items ?? [];
  const dashboardProfileCount = dashboardSummary?.profiles.count ?? dashboardProfiles.length;
  const dashboardNotificationCount = dashboardSummary?.notifications.unread_count ?? notifications.length;
  const dashboardModerationCount = dashboardSummary?.moderation.count ?? moderationQuery.data?.items.length ?? 0;

  if (!isAuthenticated) {
    return (
      <main className="grid min-h-screen content-center justify-items-center px-5 py-8 [&>div]:w-[min(100%,480px)] [&>section]:w-[min(100%,480px)]">
        {notice ? <NoticeBanner notice={notice} onClose={() => setNotice(null)} /> : null}
        <Routes>
          <Route index element={<Navigate to="/login" replace />} />
          <Route
            path="/login"
            element={
              <LoginPage
                apiUrl={state.apiUrl}
                api={api}
                authConfig={authConfig}
                isAuthenticated={isAuthenticated}
                postAuthPath={defaultAuthenticatedPath}
                onLocalIdentity={(identity) => rememberUser(identity)}
                onNotice={setNotice}
              />
            }
          />
          <Route
            path="/register"
            element={
              <RegisterPage
                apiUrl={state.apiUrl}
                api={api}
                authConfig={authConfig}
                isAuthenticated={isAuthenticated}
                postAuthPath={defaultAuthenticatedPath}
                onLocalIdentity={(identity) => rememberUser(identity)}
                onNotice={setNotice}
              />
            }
          />
          <Route
            path="/auth/callback"
            element={
              <AuthCallbackPage
                authConfig={authConfig}
                postAuthPath={defaultAuthenticatedPath}
                onSession={setAuthSession}
                onNotice={setNotice}
              />
            }
          />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </main>
    );
  }

  return (
    <div className="grid min-h-screen grid-cols-[256px_minmax(0,1fr)] max-[980px]:grid-cols-1">
      <aside className="sticky top-0 flex h-screen flex-col border-r border-line bg-[#fbfcfa] px-4 py-[22px] max-[980px]:static max-[980px]:h-auto">
        <div className="mb-7 flex min-h-11 items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-accent font-extrabold text-white" aria-hidden="true">
            S
          </div>
          <div>
            <strong className="block">seagulls</strong>
            <span className="block text-[0.82rem] text-muted">Phase 4</span>
          </div>
        </div>

        <nav className="grid gap-1.5 max-[980px]:grid-cols-10" aria-label="Primary">
          <NavItem to="/dashboard" icon={<LayoutDashboard size={18} />} label="Dashboard" />
          <NavItem to="/feed" icon={<Home size={18} />} label="Feed" />
          <NavItem
            to={
              state.activeProfile
                ? `/profiles/${routeHandle(state.activeProfile.handle)}`
                : "/profiles/none"
            }
            icon={<UserRound size={18} />}
            label="Profile"
          />
          <NavItem to="/chat" icon={<MessageCircle size={18} />} label="Chat" />
          <NavItem
            to={state.selectedPostId ? `/threads/${state.selectedPostId}` : "/threads/none"}
            icon={<MessagesSquare size={18} />}
            label="Thread"
          />
          <NavItem
            to={state.room ? `/rooms/${state.room.slug}` : "/rooms/none"}
            icon={<DoorOpen size={18} />}
            label="Room"
          />
          <NavItem to="/inbox" icon={<Inbox size={18} />} label="Inbox" />
          <NavItem to="/agent-inbox" icon={<GitBranch size={18} />} label="Agent inbox" />
          <NavItem to="/routing" icon={<RouteIcon size={18} />} label="Routing" />
          <NavItem to="/admin" icon={<Settings size={18} />} label="Admin" />
        </nav>

        <div className="mt-auto grid gap-2.5 max-[980px]:mt-[18px] max-[980px]:grid-cols-2">
          {authConfig.mode === "local" ? (
            <button
              className="inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-lg border-0 bg-accent px-3.5 font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58]"
              type="button"
              onClick={() => seedMutation.mutate()}
              disabled={seedMutation.isPending}
            >
              <WandSparkles size={16} />
              {seedMutation.isPending ? "Creating" : "Seed loop"}
            </button>
          ) : null}
          {isAuthenticated ? (
            <button className="inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-lg border border-line bg-white px-3.5 font-extrabold text-ink disabled:cursor-not-allowed disabled:opacity-[0.58]" type="button" onClick={signOut}>
              <LogOut size={16} />
              Sign out
            </button>
          ) : null}
          <button className="inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-lg border border-line bg-white px-3.5 font-extrabold text-ink disabled:cursor-not-allowed disabled:opacity-[0.58]" type="button" onClick={clearSession}>
            <Trash2 size={16} />
            Clear local
          </button>
        </div>
      </aside>

      <main className="min-w-0 p-6 max-[620px]:p-4">
        <header className="mb-[18px] flex items-end justify-between gap-[18px] max-[980px]:grid max-[980px]:items-stretch">
          <div>
            <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">Human SNS for agent loops</p>
            <h1 className="m-0 text-[clamp(1.8rem,4vw,3rem)] leading-none tracking-normal">Social workspace</h1>
          </div>

          <form className="grid min-w-[min(100%,620px)] grid-cols-[auto_minmax(220px,440px)_40px] items-center gap-2 max-[620px]:min-w-0 max-[620px]:grid-cols-1" onSubmit={updateApiUrl}>
            <label className="text-[0.83rem] font-extrabold text-muted" htmlFor="api-url">Social API</label>
            <input
              id="api-url"
              value={apiDraft}
              onChange={(event) => setApiDraft(event.target.value)}
              spellCheck={false}
            />
            <button className="inline-flex min-h-10 w-10 items-center justify-center gap-2 rounded-lg border-0 bg-accent font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58] max-[620px]:w-full" type="submit" title="Apply endpoint" aria-label="Apply endpoint">
              <RefreshCw size={18} />
            </button>
          </form>
        </header>

        <section className="mb-4 grid grid-cols-5 gap-2.5 max-[1100px]:grid-cols-3 max-[760px]:grid-cols-2 max-[620px]:grid-cols-1" aria-live="polite">
          <StatusPill
            icon={<Activity size={15} />}
            label={healthQuery.data?.ok ? healthQuery.data.app : "Social API"}
            value={healthQuery.data?.ok ? healthQuery.data.storage : healthQuery.isLoading ? "Checking" : "Offline"}
            tone={healthQuery.data?.ok ? "ok" : "warn"}
          />
          <StatusPill
            icon={<GitBranch size={15} />}
            label={messageHealthQuery.data?.ok ? messageHealthQuery.data.app : "Message hub"}
            value={messageHealthQuery.data?.ok ? messageHealthQuery.data.storage : messageHealthQuery.isLoading ? "Checking" : "Offline"}
            tone={messageHealthQuery.data?.ok ? "ok" : "warn"}
          />
          <StatusPill
            icon={<UserRound size={15} />}
            label={state.activeProfile?.display_name ?? "Active agent"}
            value={state.activeProfile?.handle ?? "Not set"}
          />
          <StatusPill
            icon={<Bell size={15} />}
            label="Notifications"
            value={String(dashboardNotificationCount)}
            tone={dashboardNotificationCount > 0 ? "warn" : "neutral"}
          />
          <StatusPill
            icon={<Flag size={15} />}
            label="Moderation"
            value={String(dashboardModerationCount)}
          />
        </section>

        {notice ? <NoticeBanner notice={notice} onClose={() => setNotice(null)} /> : null}

        <Routes>
          <Route
            index
            element={<Navigate to={isAuthenticated ? defaultAuthenticatedPath : "/login"} replace />}
          />
          <Route
            path="/login"
            element={
              <LoginPage
                apiUrl={state.apiUrl}
                api={api}
                authConfig={authConfig}
                isAuthenticated={isAuthenticated}
                postAuthPath={defaultAuthenticatedPath}
                onLocalIdentity={(identity) => rememberUser(identity)}
                onNotice={setNotice}
              />
            }
          />
          <Route
            path="/register"
            element={
              <RegisterPage
                apiUrl={state.apiUrl}
                api={api}
                authConfig={authConfig}
                isAuthenticated={isAuthenticated}
                postAuthPath={defaultAuthenticatedPath}
                onLocalIdentity={(identity) => rememberUser(identity)}
                onNotice={setNotice}
              />
            }
          />
          <Route
            path="/auth/callback"
            element={<Navigate to={defaultAuthenticatedPath} replace />}
          />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated}>
                <DashboardPage
                  api={api}
                  state={state}
                  summary={dashboardSummary}
                  profiles={dashboardProfiles}
                  posts={dashboardPosts}
                  notifications={dashboardNotifications}
                  moderationRecords={dashboardModerationRecords}
                  profileCount={dashboardProfileCount}
                  notificationCount={dashboardNotificationCount}
                  moderationCount={dashboardModerationCount}
                  apiHealth={healthQuery.data}
                  apiHealthLoading={healthQuery.isLoading}
                  profilesLoading={profilesQuery.isFetching || dashboardQuery.isFetching}
                  setState={setState}
                  onNotice={setNotice}
                />
              </ProtectedRoute>
            }
          />
          <Route
            path="/feed"
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated}>
                <FeedPage
                  api={api}
                  state={state}
                  posts={posts}
                  isLoading={feedQuery.isFetching}
                  rememberPost={rememberPost}
                  onSelectPost={(postId) => {
                    setState((current) => touchLoopState({ ...current, selectedPostId: postId }));
                    navigate(`/threads/${postId}`);
                  }}
                  onError={(message) => setNotice({ tone: "error", message })}
                />
              </ProtectedRoute>
            }
          />
          <Route
            path="/profiles/:handle"
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated}>
                <ProfilePage
                  api={api}
                  state={state}
                  setState={setState}
                  onNotice={setNotice}
                />
              </ProtectedRoute>
            }
          />
          <Route
            path="/chat"
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated}>
                <ChatPage
                  api={api}
                  state={state}
                  profiles={dashboardProfiles}
                  onNotice={setNotice}
                />
              </ProtectedRoute>
            }
          />
          <Route
            path="/chat/:chatId"
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated}>
                <ChatPage
                  api={api}
                  state={state}
                  profiles={dashboardProfiles}
                  onNotice={setNotice}
                />
              </ProtectedRoute>
            }
          />
          <Route
            path="/threads/:postId"
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated}>
                <ThreadPage
                  api={api}
                  state={state}
                  posts={posts}
                  rememberPost={rememberPost}
                  onNotice={setNotice}
                />
              </ProtectedRoute>
            }
          />
          <Route
            path="/rooms/:slug"
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated}>
                <RoomPage
                  api={api}
                  state={state}
                  setState={setState}
                  posts={posts}
                  rememberPost={rememberPost}
                  onNotice={setNotice}
                />
              </ProtectedRoute>
            }
          />
          <Route
            path="/inbox"
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated}>
                <InboxPage
                  api={api}
                  state={state}
                  posts={posts}
                  notifications={notifications}
                  moderationRecords={moderationQuery.data?.items ?? []}
                  moderationLoading={moderationQuery.isFetching}
                  rememberModeration={rememberModeration}
                  onNotice={setNotice}
                  refetchModeration={() => {
                    void moderationQuery.refetch();
                  }}
                />
              </ProtectedRoute>
            }
          />
          <Route
            path="/agent-inbox"
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated}>
                <AgentLifecycleInboxPage
                  messageApi={messageApi}
                  profiles={dashboardProfiles}
                  activeProfile={state.activeProfile}
                  onNotice={setNotice}
                />
              </ProtectedRoute>
            }
          />
          <Route
            path="/routing"
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated}>
                <RoutingRulesPage
                  messageApi={messageApi}
                  profiles={dashboardProfiles}
                  onNotice={setNotice}
                />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin"
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated}>
                <AdminPage
                  aiProviderApiUrl={aiProviderApiUrl}
                  authToken={activeAuthSession?.accessToken ?? null}
                  onNotice={setNotice}
                />
              </ProtectedRoute>
            }
          />
        </Routes>
      </main>
    </div>
  );
}

import { LogIn, UserRound } from "lucide-react";
import { ReactNode, useState } from "react";
import { Navigate, NavLink, useNavigate } from "react-router";
import { useMutation } from "@tanstack/react-query";

import { SocialApiClient, SocialApiError } from "../lib/api";
import {
  beginHostedLogin,
  type AuthConfig,
} from "../lib/auth";
import type { HumanIdentity } from "../lib/social";
import type { Notice } from "./shared";

type AppMutationError = Error | SocialApiError;

function AuthPanel({
  title,
  icon,
  children,
}: {
  title: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="min-w-0 max-w-[480px] overflow-hidden rounded-lg border border-line bg-surface shadow-panel">
      <div className="flex items-center justify-between gap-4 px-[22px] pt-6 pb-[18px]">
        <div className="flex min-w-0 items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-lg bg-accent font-extrabold text-white" aria-hidden="true">
            S
          </div>
          <div>
            <p className="m-0 mb-1.5 text-xs font-extrabold uppercase tracking-normal text-muted">seagulls</p>
            <h1 className="m-0 overflow-hidden text-ellipsis whitespace-nowrap text-[1.55rem] leading-none">{title}</h1>
          </div>
        </div>
        <div className="grid h-10 w-10 flex-none place-items-center rounded-lg border border-line bg-surface-soft text-accent-strong" aria-hidden="true">
          {icon}
        </div>
      </div>

      <nav className="mx-[22px] mb-[18px] grid grid-cols-2 gap-1 rounded-lg border border-line bg-surface-soft p-[5px]" aria-label="Account">
        <NavLink
          className={({ isActive }) =>
            `grid min-h-[34px] place-items-center rounded-md font-black text-muted no-underline ${
              isActive ? "bg-white text-accent-strong shadow-[0_5px_14px_rgba(32,44,39,0.08)]" : ""
            }`
          }
          to="/login"
        >
          Login
        </NavLink>
        <NavLink
          className={({ isActive }) =>
            `grid min-h-[34px] place-items-center rounded-md font-black text-muted no-underline ${
              isActive ? "bg-white text-accent-strong shadow-[0_5px_14px_rgba(32,44,39,0.08)]" : ""
            }`
          }
          to="/register"
        >
          Register
        </NavLink>
      </nav>

      {children}
    </section>
  );
}

export function LoginPage({
  api,
  authConfig,
  isAuthenticated,
  postAuthPath = "/dashboard",
  onLocalIdentity,
  onNotice,
}: {
  apiUrl: string;
  api: SocialApiClient;
  authConfig: AuthConfig;
  isAuthenticated: boolean;
  postAuthPath?: string;
  onLocalIdentity: (identity: HumanIdentity) => void;
  onNotice: (notice: Notice) => void;
}) {
  const navigate = useNavigate();
  const [subject, setSubject] = useState("");

  const localLoginMutation = useMutation({
    mutationFn: async () => {
      const identity = (
        await api.identifyHuman({
          provider: "local",
          subject,
        })
      ).identity;
      return identity;
    },
    onSuccess: (identity) => {
      onLocalIdentity(identity);
      onNotice({ tone: "ok", message: "Signed in." });
      navigate(postAuthPath);
    },
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  const cognitoLoginMutation = useMutation({
    mutationFn: async () => {
      if (authConfig.mode !== "cognito") {
        throw new Error("Cognito auth is not configured.");
      }
      return beginHostedLogin(authConfig);
    },
    onSuccess: (authorizationUrl) => {
      window.location.assign(authorizationUrl);
    },
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  if (isAuthenticated) {
    return <Navigate to={postAuthPath} replace />;
  }

  if (authConfig.mode === "local") {
    return (
      <AuthPanel title="Login" icon={<LogIn size={20} />}>
        <form
          className="grid grid-cols-2 gap-3.5 px-[22px] pb-[22px] max-[620px]:grid-cols-1"
          onSubmit={(event) => {
            event.preventDefault();
            if (subject.trim()) {
              localLoginMutation.mutate();
            }
          }}
        >
          <label className="col-span-2 grid gap-1.5 text-[0.82rem] font-black text-muted max-[620px]:col-span-1">
            Subject
            <input value={subject} onChange={(event) => setSubject(event.target.value)} placeholder="alice" />
          </label>
          <div className="col-span-2 flex gap-2.5 max-[620px]:col-span-1 max-[620px]:grid max-[620px]:grid-cols-1">
            <button className="inline-flex min-h-10 flex-1 items-center justify-center gap-2 rounded-lg border-0 bg-accent px-3.5 font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58]" type="submit" disabled={!subject.trim() || localLoginMutation.isPending}>
              <LogIn size={16} />
              Login
            </button>
            <button className="inline-flex min-h-10 min-w-28 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3.5 font-extrabold text-ink disabled:cursor-not-allowed disabled:opacity-[0.58] max-[620px]:min-w-0" type="button" onClick={() => navigate("/register")}>
              Register
            </button>
          </div>
        </form>
      </AuthPanel>
    );
  }

  return (
    <AuthPanel title="Login" icon={<LogIn size={20} />}>
      <form
        className="grid gap-3.5 px-[22px] pb-[22px]"
        onSubmit={(event) => {
          event.preventDefault();
          cognitoLoginMutation.mutate();
        }}
      >
        <div className="flex gap-2.5 max-[620px]:grid max-[620px]:grid-cols-1">
          <button className="inline-flex min-h-10 flex-1 items-center justify-center gap-2 rounded-lg border-0 bg-accent px-3.5 font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58]" type="submit" disabled={cognitoLoginMutation.isPending}>
            <LogIn size={16} />
            Login
          </button>
          <button className="inline-flex min-h-10 min-w-28 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3.5 font-extrabold text-ink disabled:cursor-not-allowed disabled:opacity-[0.58] max-[620px]:min-w-0" type="button" onClick={() => navigate("/register")}>
            Register
          </button>
        </div>
      </form>
    </AuthPanel>
  );
}

export function RegisterPage({
  api,
  authConfig,
  isAuthenticated,
  postAuthPath = "/dashboard",
  onLocalIdentity,
  onNotice,
}: {
  apiUrl: string;
  api: SocialApiClient;
  authConfig: AuthConfig;
  isAuthenticated: boolean;
  postAuthPath?: string;
  onLocalIdentity: (identity: HumanIdentity) => void;
  onNotice: (notice: Notice) => void;
}) {
  const navigate = useNavigate();
  const [subject, setSubject] = useState("");
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");

  const localRegisterMutation = useMutation({
    mutationFn: async () => {
      const identity = (
        await api.identifyHuman({
          provider: "local",
          subject,
          email,
          display_name: displayName,
        })
      ).identity;
      return identity;
    },
    onSuccess: (identity) => {
      onLocalIdentity(identity);
      onNotice({ tone: "ok", message: "Registered local user." });
      navigate(postAuthPath);
    },
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  const cognitoRegisterMutation = useMutation({
    mutationFn: async () => {
      if (authConfig.mode !== "cognito") {
        throw new Error("Cognito auth is not configured.");
      }
      return beginHostedLogin(authConfig);
    },
    onSuccess: (authorizationUrl) => {
      window.location.assign(authorizationUrl);
    },
    onError: (error: AppMutationError) => onNotice({ tone: "error", message: error.message }),
  });

  if (isAuthenticated) {
    return <Navigate to={postAuthPath} replace />;
  }

  return (
    <AuthPanel title="Register" icon={<UserRound size={20} />}>
      {authConfig.mode === "local" ? (
        <form
          className="grid grid-cols-2 gap-3.5 px-[22px] pb-[22px] max-[620px]:grid-cols-1"
          onSubmit={(event) => {
            event.preventDefault();
            if (subject.trim()) {
              localRegisterMutation.mutate();
            }
          }}
        >
          <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
            Subject
            <input value={subject} onChange={(event) => setSubject(event.target.value)} placeholder="alice" />
          </label>
          <label className="grid gap-1.5 text-[0.82rem] font-black text-muted">
            Display name
            <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Alice" />
          </label>
          <label className="col-span-2 grid gap-1.5 text-[0.82rem] font-black text-muted max-[620px]:col-span-1">
            Email
            <input value={email} onChange={(event) => setEmail(event.target.value)} placeholder="alice@example.com" />
          </label>
          <div className="col-span-2 flex gap-2.5 max-[620px]:col-span-1 max-[620px]:grid max-[620px]:grid-cols-1">
            <button className="inline-flex min-h-10 flex-1 items-center justify-center gap-2 rounded-lg border-0 bg-accent px-3.5 font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58]" type="submit" disabled={!subject.trim() || localRegisterMutation.isPending}>
              <UserRound size={16} />
              Register
            </button>
            <button className="inline-flex min-h-10 min-w-28 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3.5 font-extrabold text-ink disabled:cursor-not-allowed disabled:opacity-[0.58] max-[620px]:min-w-0" type="button" onClick={() => navigate("/login")}>
              Login
            </button>
          </div>
        </form>
      ) : (
        <form
          className="grid gap-3.5 px-[22px] pb-[22px]"
          onSubmit={(event) => {
            event.preventDefault();
            cognitoRegisterMutation.mutate();
          }}
        >
          <div className="flex gap-2.5 max-[620px]:grid max-[620px]:grid-cols-1">
            <button
              className="inline-flex min-h-10 flex-1 items-center justify-center gap-2 rounded-lg border-0 bg-accent px-3.5 font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-[0.58]"
              type="submit"
              disabled={cognitoRegisterMutation.isPending}
            >
              <UserRound size={16} />
              Register
            </button>
            <button className="inline-flex min-h-10 min-w-28 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3.5 font-extrabold text-ink disabled:cursor-not-allowed disabled:opacity-[0.58] max-[620px]:min-w-0" type="button" onClick={() => navigate("/login")}>
              Login
            </button>
          </div>
        </form>
      )}
    </AuthPanel>
  );
}

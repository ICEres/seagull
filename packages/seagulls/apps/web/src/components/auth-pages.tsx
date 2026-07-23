import { Moon, Sun } from "lucide-react";
import { useState } from "react";
import { Link, Navigate } from "react-router";
import { useMutation } from "@tanstack/react-query";

import { SocialApiClient, SocialApiError } from "../lib/api";
import {
  beginEmailOtpRegistration,
  beginEmailOtpSignIn,
  completeEmailOtpRegistration,
  completeEmailOtpSignIn,
  resendEmailOtpRegistration,
  type AuthConfig,
  type AuthSession,
  type EmailOtpChallenge,
} from "../lib/auth";
import type { HumanIdentity } from "../lib/social";
import { AmbientFlock, Wing, YOUR_WING } from "./gulls";
import type { Notice } from "./shared";

type AppMutationError = Error | SocialApiError;
type AuthIntent = "login" | "register";

type AuthPageProps = {
  api: SocialApiClient;
  authConfig: AuthConfig;
  isAuthenticated: boolean;
  postAuthPath?: string;
  resolvedTheme: "light" | "dark";
  onToggleTheme: () => void;
  onLocalIdentity: (identity: HumanIdentity) => void;
  onAuthSession: (session: AuthSession) => void;
  onNotice: (notice: Notice) => void;
};

export function LoginPage(props: AuthPageProps) {
  return <AuthPage {...props} intent="login" />;
}

export function RegisterPage(props: AuthPageProps) {
  return <AuthPage {...props} intent="register" />;
}

function AuthPage({
  api,
  authConfig,
  isAuthenticated,
  postAuthPath = "/sky",
  resolvedTheme,
  onToggleTheme,
  onLocalIdentity,
  onAuthSession,
  onNotice,
  intent,
}: AuthPageProps & { intent: AuthIntent }) {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<EmailOtpChallenge | null>(null);
  const [status, setStatus] = useState<{ tone: "error" | "ok"; message: string } | null>(null);

  const localLoginMutation = useMutation({
    mutationFn: async () => {
      const normalizedEmail = email.trim().toLowerCase();
      return (
        await api.identifyHuman({
          provider: "local",
          subject: normalizedEmail,
          email: normalizedEmail,
        })
      ).identity;
    },
    onSuccess: (identity) => {
      onLocalIdentity(identity);
      onNotice({ tone: "ok", message: intent === "register" ? "Welcome aboard." : "Welcome back." });
    },
    onError: (error: AppMutationError) => setAuthError(error, setStatus),
  });

  const requestCodeMutation = useMutation({
    mutationFn: async () => {
      if (authConfig.mode !== "cognito") {
        throw new Error("Email-code authentication is not configured.");
      }
      return intent === "register"
        ? beginEmailOtpRegistration(authConfig, email)
        : beginEmailOtpSignIn(authConfig, email);
    },
    onSuccess: (nextChallenge) => {
      setChallenge(nextChallenge);
      setCode("");
      setStatus({ tone: "ok", message: "Code sent · check your email" });
    },
    onError: (error: AppMutationError) => setAuthError(error, setStatus),
  });

  const verifyCodeMutation = useMutation({
    mutationFn: async () => {
      if (authConfig.mode !== "cognito" || !challenge) {
        throw new Error("Request a new email code.");
      }
      return challenge.kind === "registration"
        ? completeEmailOtpRegistration(authConfig, challenge, code)
        : completeEmailOtpSignIn(authConfig, challenge, code);
    },
    onSuccess: (result) => {
      if (!("accessToken" in result)) {
        setChallenge(result);
        setCode("");
        setStatus({ tone: "ok", message: "Account ready · a sign-in code is on its way" });
        return;
      }
      onAuthSession(result);
      onNotice({ tone: "ok", message: intent === "register" ? "Welcome aboard." : "Signed in." });
    },
    onError: (error: AppMutationError) => setAuthError(error, setStatus),
  });

  const resendCodeMutation = useMutation({
    mutationFn: async () => {
      if (authConfig.mode !== "cognito" || !challenge) {
        throw new Error("Request a new email code.");
      }
      if (challenge.kind === "registration") {
        await resendEmailOtpRegistration(authConfig, challenge.email);
        return challenge;
      }
      return beginEmailOtpSignIn(authConfig, challenge.email);
    },
    onSuccess: (nextChallenge) => {
      setChallenge(nextChallenge);
      setCode("");
      setStatus({ tone: "ok", message: "A new code is on its way." });
    },
    onError: (error: AppMutationError) => setAuthError(error, setStatus),
  });

  if (isAuthenticated) {
    return <Navigate to={postAuthPath} replace />;
  }

  const localMode = authConfig.mode === "local";
  const emailIsValid = /^\S+@\S+\.\S+$/.test(email.trim());
  const isPending =
    localLoginMutation.isPending ||
    requestCodeMutation.isPending ||
    verifyCodeMutation.isPending ||
    resendCodeMutation.isPending;
  const handle = `@${(challenge?.email || email).trim().split("@")[0] || "you"}`;
  const isCodeStep = Boolean(challenge);
  const heading = isCodeStep
    ? "Check your inbox"
    : intent === "register"
      ? "Join the flock"
      : "Your sky is waiting";
  const subheading = isCodeStep
    ? `We sent a code to ${challenge?.email}.`
    : intent === "register"
      ? "One email — and your gull takes wing."
      : "Sign in to talk to your flock.";
  const defaultNote = localMode
    ? "Local development · email delivery is skipped"
    : isCodeStep
      ? "Enter the one-time code from your email"
      : "We'll email you a one-time code";
  const pendingNote = localLoginMutation.isPending
    ? "entering…"
    : verifyCodeMutation.isPending
      ? "checking…"
      : "delivering…";
  const note = isPending ? pendingNote : status?.message || defaultNote;
  const themeAction = resolvedTheme === "dark" ? "Switch to light mode" : "Switch to dark mode";

  return (
    <div className="relative grid min-h-screen grid-rows-[auto_1fr] overflow-hidden bg-bg">
      <header className="relative z-10 flex items-center justify-between px-7 py-[22px]">
        <span className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-[0.9rem] font-black text-white">
            S
          </span>
          <strong className="font-extrabold tracking-[-0.01em]">seagulls</strong>
        </span>
        <button
          type="button"
          onClick={onToggleTheme}
          aria-label={themeAction}
          title={themeAction}
          className="grid h-[38px] w-[38px] place-items-center rounded-lg border-0 bg-transparent text-muted hover:bg-accent-soft"
        >
          {resolvedTheme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
        </button>
      </header>

      <main className="relative z-10 grid content-center justify-items-center px-[22px] pb-[90px]">
        <h1 className="m-0 mb-2.5 text-center text-[clamp(2.35rem,6vw,2.7rem)] font-extrabold leading-[1.05] tracking-[-0.03em]">
          {heading}
          <span className="text-accent">.</span>
        </h1>
        <p className="m-0 mb-10 max-w-full text-center text-[1.02rem] break-words text-muted [overflow-wrap:anywhere]">
          {subheading}
        </p>

        <form
          className="w-[min(440px,100%)]"
          onSubmit={(event) => {
            event.preventDefault();
            setStatus(null);
            if (isCodeStep) {
              if (code.trim() && !isPending) {
                verifyCodeMutation.mutate();
              }
              return;
            }
            if (!emailIsValid || isPending) {
              return;
            }
            if (localMode) {
              localLoginMutation.mutate();
              return;
            }
            requestCodeMutation.mutate();
          }}
        >
          <div
            className="relative flex items-center gap-2.5 rounded-[14px] border border-line bg-card py-2 pr-2 pl-5 focus-within:border-accent"
            style={{ boxShadow: "var(--auth-shadow)" }}
          >
            <span
              aria-hidden="true"
              className="pointer-events-none absolute top-0 right-[22px] flex -translate-y-[58%] items-end gap-1.5"
            >
              {isPending ? <FlyingGull /> : <Wing path={YOUR_WING} size={24} className="text-ink auth-perched-gull" />}
              <span className="max-w-[min(220px,55vw)] truncate text-[0.68rem] font-extrabold text-faint">
                {handle}
              </span>
            </span>

            {isCodeStep ? (
              <input
                value={code}
                onChange={(event) => {
                  setCode(event.target.value);
                  setStatus(null);
                }}
                placeholder="Email code"
                aria-label="Email code"
                autoComplete="one-time-code"
                inputMode="numeric"
                className="min-w-0 flex-1 border-0 bg-transparent px-0 text-[1.05rem] font-semibold outline-none placeholder:text-muted focus:border-0"
                autoFocus
              />
            ) : (
              <input
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value);
                  setStatus(null);
                }}
                placeholder="email"
                aria-label="Email"
                type="email"
                autoComplete="email"
                className="min-w-0 flex-1 border-0 bg-transparent px-0 text-[1.05rem] font-semibold outline-none placeholder:text-muted focus:border-0"
                autoFocus
              />
            )}

            <SubmitButton
              label={
                isCodeStep
                  ? "Verify code"
                  : localMode
                    ? intent === "register"
                      ? "Create your flock"
                      : "Sign in"
                    : intent === "register"
                      ? "Send registration code"
                      : "Send login code"
              }
              disabled={isCodeStep ? !code.trim() || isPending : !emailIsValid || isPending}
              pending={isPending}
            />
          </div>

          <p
            role={status?.tone === "error" ? "alert" : "status"}
            aria-live="polite"
            className={`m-0 mt-3 text-center text-[0.74rem] font-bold transition-colors ${
              status?.tone === "error"
                ? "text-danger"
                : status?.tone === "ok"
                  ? "text-accent-strong"
                  : "text-muted"
            }`}
          >
            {note}
          </p>
        </form>

        {isCodeStep ? (
          <div className="mt-6 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-[0.82rem] font-extrabold">
            <button
              type="button"
              onClick={() => {
                setStatus(null);
                resendCodeMutation.mutate();
              }}
              disabled={isPending}
              className="border-0 bg-transparent p-0 text-accent-strong hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              Resend code
            </button>
            <button
              type="button"
              onClick={() => {
                setChallenge(null);
                setCode("");
                setStatus(null);
              }}
              disabled={isPending}
              className="border-0 bg-transparent p-0 text-muted hover:text-accent-strong disabled:cursor-not-allowed disabled:opacity-50"
            >
              Use another email
            </button>
          </div>
        ) : (
          <Link
            to={intent === "register" ? "/login" : "/register"}
            className="mt-[26px] text-[0.86rem] font-extrabold text-accent-strong no-underline hover:text-accent"
          >
            {intent === "register" ? "Already flocked? Sign in →" : "New here? Create your flock →"}
          </Link>
        )}
      </main>

      <AmbientFlock count={9} />
    </div>
  );
}

function SubmitButton({
  label,
  disabled,
  pending,
}: {
  label: string;
  disabled: boolean;
  pending: boolean;
}) {
  return (
    <button
      type="submit"
      aria-label={label}
      disabled={disabled}
      className="grid h-[42px] w-[42px] flex-none place-items-center rounded-full border-0 bg-accent text-white transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:bg-[#d4d4d4] dark:hover:bg-accent dark:disabled:bg-[#333333]"
    >
      {pending ? (
        <svg width="16" viewBox="0 0 16 16" fill="none" aria-hidden="true" className="auth-spinner">
          <circle
            cx="8"
            cy="8"
            r="6"
            stroke="currentColor"
            strokeWidth="2.4"
            fill="none"
            strokeDasharray="26"
            strokeDashoffset="16"
            strokeLinecap="round"
          />
        </svg>
      ) : (
        <svg width="14" viewBox="0 0 14 16" fill="none" aria-hidden="true">
          <path
            d="M7 14 V2 M2.5 6.5 L7 2 L11.5 6.5"
            stroke="currentColor"
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </button>
  );
}

function FlyingGull() {
  return (
    <span className="auth-flying-gull block text-accent">
      <svg width="24" viewBox="0 0 32 14" fill="none" aria-hidden="true" className="block overflow-visible">
        <path
          d="M16 8 Q8 3.5 1 7"
          stroke="currentColor"
          strokeWidth="2.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="auth-wing-left"
        />
        <path
          d="M16 8 Q24 3.5 31 7"
          stroke="currentColor"
          strokeWidth="2.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="auth-wing-right"
        />
      </svg>
    </span>
  );
}

function setAuthError(
  error: AppMutationError,
  setStatus: (status: { tone: "error" | "ok"; message: string }) => void,
) {
  const friendlyMessages: Record<string, string> = {
    CodeMismatchException: "That code wasn't accepted. Check it and try again.",
    ExpiredCodeException: "That code expired. Request a new one.",
    LimitExceededException: "Too many attempts. Wait a moment and try again.",
    TooManyRequestsException: "Too many attempts. Wait a moment and try again.",
    UserNotConfirmedException: "Finish creating your account before signing in.",
  };
  setStatus({
    tone: "error",
    message: friendlyMessages[error.name] || error.message || "Authentication failed. Try again.",
  });
}

import { useState } from "react";
import { Navigate } from "react-router";
import { useMutation } from "@tanstack/react-query";

import { SocialApiClient, SocialApiError } from "../lib/api";
import { beginHostedLogin, type AuthConfig } from "../lib/auth";
import type { HumanIdentity } from "../lib/social";
import { AmbientFlock } from "./gulls";
import type { Notice } from "./shared";

type AppMutationError = Error | SocialApiError;

export function LoginPage({
  api,
  authConfig,
  isAuthenticated,
  postAuthPath = "/sky",
  onLocalIdentity,
  onNotice,
}: {
  api: SocialApiClient;
  authConfig: AuthConfig;
  isAuthenticated: boolean;
  postAuthPath?: string;
  onLocalIdentity: (identity: HumanIdentity) => void;
  onNotice: (notice: Notice) => void;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");

  const localLoginMutation = useMutation({
    mutationFn: async () => {
      const subject = email.trim().toLowerCase() || name.trim().toLowerCase().replace(/\s+/g, "-");
      const identity = (
        await api.identifyHuman({
          provider: "local",
          subject,
          email: email.trim() || undefined,
          display_name: name.trim() || undefined,
        })
      ).identity;
      return identity;
    },
    onSuccess: (identity) => {
      onLocalIdentity(identity);
      onNotice({ tone: "ok", message: "Welcome to the sky." });
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

  const localMode = authConfig.mode === "local";
  const hostLabel = window.location.hostname || "sea.gulls.ai";

  return (
    <div className="relative grid min-h-screen grid-rows-[auto_1fr] overflow-hidden">
      <header className="flex items-center gap-2.5 px-7 py-[22px]">
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-[0.9rem] font-black text-white">S</span>
        <strong className="font-extrabold tracking-[-0.01em]">seagulls</strong>
      </header>
      <main className="grid content-center justify-items-center px-[22px] pt-6 pb-24">
        <h1 className="m-0 mb-2.5 text-center text-[clamp(2.2rem,5vw,3.4rem)] font-extrabold leading-[1.05] tracking-[-0.03em]">
          Your sky is waiting<span className="text-accent">.</span>
        </h1>
        <p className="m-0 mb-9 text-center text-[1.02rem] text-muted">Sign in to talk to your flock.</p>
        <form
          className="relative z-10 grid w-[min(360px,100%)] gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (localMode) {
              if (name.trim() || email.trim()) {
                localLoginMutation.mutate();
              }
              return;
            }
            cognitoLoginMutation.mutate();
          }}
        >
          {localMode ? (
            <>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Display name"
                aria-label="Display name"
                className="min-h-[46px]"
              />
              <input
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="Email"
                aria-label="Email"
                type="email"
                className="min-h-[46px]"
              />
            </>
          ) : null}
          <button
            type="submit"
            className="min-h-[46px] rounded-lg border-0 bg-accent font-extrabold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
            disabled={
              localMode
                ? (!name.trim() && !email.trim()) || localLoginMutation.isPending
                : cognitoLoginMutation.isPending
            }
          >
            {localMode ? "Enter the sky" : "Continue with Cognito"}
          </button>
          <span className="text-center text-[0.76rem] font-bold text-faint">
            {localMode ? "Local mode" : "Cognito Hosted UI"} &middot; {hostLabel}
          </span>
        </form>
      </main>
      <AmbientFlock />
    </div>
  );
}

export function RegisterPage(props: Parameters<typeof LoginPage>[0]) {
  return <LoginPage {...props} />;
}

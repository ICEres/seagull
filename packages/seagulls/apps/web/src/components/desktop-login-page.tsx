import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router";

import type { AuthPageProps } from "./auth-pages";
import { LoginPage } from "./auth-pages";
import { Wing, YOUR_WING } from "@seagulls/ui";
import {
  DESKTOP_LOGIN_PATH,
  clearDesktopLoginRequest,
  DESKTOP_LOGIN_TRANSFER_TIMEOUT_MS,
  isDesktopLoginRequestActive,
  loadDesktopLoginRequest,
  parseDesktopLoginFragment,
  saveDesktopLoginRequest,
  transferDesktopLogin,
  type DesktopLoginRequest,
} from "../lib/desktop-login";
import type { AuthSession } from "../lib/auth";

type DesktopLoginPageProps = AuthPageProps & {
  authSession: AuthSession | null;
};

type TransferState = "idle" | "sending" | "success";

export function DesktopLoginPage({ authSession, ...authProps }: DesktopLoginPageProps) {
  const location = useLocation();
  const [initialRequest] = useState(() => {
    const hadStoredRequest = Boolean(window.sessionStorage.getItem("seagull.desktop.login.request"));
    const pending = loadDesktopLoginRequest();
    return {
      pending,
      error: hadStoredRequest && !pending ? "This sign-in request expired or is invalid. Start again from the Mac app." : null,
    };
  });
  const [request, setRequest] = useState<DesktopLoginRequest | null>(initialRequest.pending);
  const [requestError, setRequestError] = useState<string | null>(initialRequest.error);
  const [transferError, setTransferError] = useState<string | null>(null);
  const [transferState, setTransferState] = useState<TransferState>("idle");
  const [processedHash, setProcessedHash] = useState<string | null>(null);
  const transferController = useRef<AbortController | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      transferController.current?.abort();
    };
  }, []);

  useEffect(() => {
    setProcessedHash(location.hash || "");
    if (location.hash) {
      const parsed = parseDesktopLoginFragment(location.hash);
      window.history.replaceState(window.history.state, "", `${location.pathname}${location.search}`);
      clearDesktopLoginRequest();
      if (parsed.error || !parsed.request) {
        setRequest(null);
        setRequestError(parsed.error ?? "This desktop sign-in request is invalid.");
        return;
      }
      saveDesktopLoginRequest(parsed.request);
      setRequest(parsed.request);
      setRequestError(null);
      setTransferError(null);
      setTransferState("idle");
      return;
    }

    const hadStoredRequest = Boolean(window.sessionStorage.getItem("seagull.desktop.login.request"));
    const pending = loadDesktopLoginRequest();
    setRequest(pending);
    if (pending) {
      setRequestError(null);
    } else if (hadStoredRequest) {
      setRequestError("This sign-in request expired or is invalid. Start again from the Mac app.");
    }
  }, [location.hash, location.pathname, location.search]);

  const waitingForFragment = Boolean(location.hash && processedHash !== location.hash);

  if (!authProps.isAuthenticated) {
    if (!request || waitingForFragment) {
      return <HandoffUnavailable message={requestError ?? "Open this page from Gulls on your Mac to start a connection."} />;
    }
    const pageProps = {
      ...authProps,
      postAuthPath: DESKTOP_LOGIN_PATH,
    };
    return <LoginPage {...pageProps} />;
  }

  const canContinue = Boolean(request && isDesktopLoginRequestActive(request) && authSession);

  async function continueToMac() {
    if (transferController.current) {
      return;
    }
    if (!request || !isDesktopLoginRequestActive(request)) {
      clearDesktopLoginRequest();
      setRequest(null);
      setTransferError("This sign-in request expired. Start again from the Mac app.");
      return;
    }
    if (!authSession) {
      setTransferError("This signed-in account cannot be shared from the current session.");
      return;
    }

    setTransferState("sending");
    setTransferError(null);
    const controller = new AbortController();
    transferController.current = controller;
    try {
      await transferDesktopLogin(request, authSession, fetch, DESKTOP_LOGIN_TRANSFER_TIMEOUT_MS, controller.signal);
      if (!mounted.current) return;
      clearDesktopLoginRequest();
      setRequest(null);
      setTransferState("success");
    } catch (error) {
      if (!mounted.current || controller.signal.aborted) return;
      setTransferState("idle");
      setTransferError(error instanceof Error ? error.message : "The Mac app could not receive this sign-in.");
    } finally {
      if (transferController.current === controller) {
        transferController.current = null;
      }
    }
  }

  function cancel() {
    clearDesktopLoginRequest();
    setRequest(null);
    setRequestError("The sign-in was cancelled. Start again from Gulls when you are ready.");
    setTransferError(null);
    setTransferState("idle");
  }

  if (waitingForFragment) {
    return <HandoffUnavailable message="Preparing your secure connection…" />;
  }

  return (
    <div className="relative grid min-h-screen content-center justify-items-center overflow-hidden bg-bg px-5 py-10">
      <div className="relative z-10 w-[min(520px,100%)] rounded-2xl border border-line bg-card p-7 shadow-panel sm:p-9">
        <div className="mb-7 flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-[0.9rem] font-black text-white">S</span>
          <strong className="font-extrabold tracking-[-0.01em]">seagulls</strong>
        </div>

        {transferState === "success" ? (
          <SuccessState />
        ) : (
          <>
            <div className="mb-6 flex items-center gap-4">
              <span className="grid h-12 w-12 place-items-center rounded-full bg-accent text-white">
                <Wing path={YOUR_WING} size={25} strokeWidth={3.2} />
              </span>
              <div>
                <h1 className="m-0 text-[1.55rem] font-extrabold tracking-[-0.025em]">
                  Continue to Gulls<span className="text-accent">.</span>
                </h1>
                <p className="m-0 mt-1 text-sm text-muted">Connect this signed-in account to Gulls on this computer.</p>
              </div>
            </div>

            {request ? (
              <div className="rounded-xl bg-accent-soft px-4 py-3 text-sm leading-[1.45] text-accent-strong">
                Continuing will share this signed-in account with the Mac app and CLI on this computer.
              </div>
            ) : (
              <div className="rounded-xl bg-bg px-4 py-3 text-sm leading-[1.45] text-muted">
                Open this page from Gulls on your Mac to start a connection.
              </div>
            )}

            {requestError || transferError ? (
              <p role="alert" className="mt-3 mb-0 text-sm font-bold text-danger">
                {requestError || transferError}
              </p>
            ) : null}

            <div className="mt-7 flex flex-wrap justify-end gap-3">
              <button
                type="button"
                onClick={cancel}
                disabled={transferState === "sending"}
                className="rounded-lg border-0 bg-transparent px-3.5 py-2.5 text-sm font-extrabold text-muted hover:bg-bg disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void continueToMac()}
                disabled={!canContinue || transferState === "sending"}
                className="rounded-lg border-0 bg-accent px-4 py-2.5 text-sm font-extrabold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:bg-[#d4d4d4] dark:disabled:bg-[#333333]"
              >
                {transferState === "sending" ? "Connecting…" : "Continue on this computer"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function SuccessState() {
  return (
    <div className="py-5 text-center">
      <div className="mx-auto mb-5 grid h-14 w-14 place-items-center rounded-full bg-accent-soft text-accent-strong">
        <Wing path={YOUR_WING} size={28} strokeWidth={3} />
      </div>
      <h1 className="m-0 text-[1.65rem] font-extrabold tracking-[-0.025em]">
        You’re connected<span className="text-accent">.</span>
      </h1>
      <p className="mx-auto mt-3 mb-0 max-w-[35ch] text-sm leading-[1.5] text-muted">
        Return to Gulls on your Mac. You can close this tab when you are done.
      </p>
    </div>
  );
}

function HandoffUnavailable({ message }: { message: string }) {
  return (
    <div className="relative grid min-h-screen content-center justify-items-center overflow-hidden bg-bg px-5 py-10">
      <div className="relative z-10 w-[min(520px,100%)] rounded-2xl border border-line bg-card p-7 shadow-panel sm:p-9">
        <div className="mb-7 flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-[0.9rem] font-black text-white">S</span>
          <strong className="font-extrabold tracking-[-0.01em]">seagulls</strong>
        </div>
        <h1 className="m-0 text-[1.55rem] font-extrabold tracking-[-0.025em]">
          Connect to Gulls<span className="text-accent">.</span>
        </h1>
        <p className="mt-3 mb-0 text-sm leading-[1.5] text-muted">{message}</p>
      </div>
    </div>
  );
}

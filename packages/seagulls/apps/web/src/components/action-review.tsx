import { useState, type ReactNode } from "react";

import { reviewOpenUrl, type OpenUrlEffect } from "../lib/action-effect";

const secondaryButton =
  "min-h-8 rounded-[7px] border-[1.5px] border-line bg-transparent px-3 text-[0.76rem] font-extrabold text-muted hover:border-accent hover:text-accent-strong disabled:cursor-not-allowed disabled:opacity-60";

// Proposes an open_url action in two steps. Review freezes the exact request
// and states its effect; Confirm submits that frozen request. Editing the URL
// withdraws the review, so nothing reaches the hub that was not shown first.
export function ActionReview({
  initialTarget,
  senderUrls,
  senderHandle,
  pending,
  onConfirm,
}: {
  initialTarget: string;
  senderUrls: readonly string[];
  senderHandle: string;
  pending: boolean;
  onConfirm: (effect: OpenUrlEffect) => void;
}) {
  const [target, setTarget] = useState(initialTarget);
  const [reviewed, setReviewed] = useState<OpenUrlEffect | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  function review() {
    const result = reviewOpenUrl(target, senderUrls);
    setReviewed(result.ok ? result.effect : null);
    setProblem(result.ok ? null : result.reason);
  }

  return (
    <div className="grid gap-2">
      <div className="grid gap-1.5 text-[0.72rem] font-extrabold text-muted">
        <span>Open a URL</span>
        <span className="flex gap-2">
          <input
            aria-label="URL to open"
            value={target}
            onChange={(event) => {
              setTarget(event.target.value);
              setReviewed(null);
              setProblem(null);
            }}
            spellCheck={false}
            className="min-w-0 flex-1 bg-bg text-[0.88rem]"
          />
          <button type="button" onClick={review} disabled={!target.trim() || pending} className={secondaryButton}>
            Review
          </button>
        </span>
      </div>
      {problem ? (
        <p role="alert" className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-xs font-bold text-danger">
          {problem}
        </p>
      ) : null}
      {reviewed ? (
        <div aria-label="Effect summary" role="group" className="grid gap-2 rounded-lg bg-bg p-3">
          <span className="text-[0.66rem] font-black tracking-[0.08em] text-faint uppercase">Effect summary</span>
          <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
            <EffectRow term="Operation">
              Open a URL <code>{reviewed.type}</code>
            </EffectRow>
            <EffectRow term="Destination">
              <strong data-testid="effect-host" className="text-ink">
                {reviewed.host}
              </strong>
            </EffectRow>
            <EffectRow term="Full URL">{reviewed.target}</EffectRow>
            <EffectRow term="Source">
              {reviewed.fromSender ? `Supplied by ${senderHandle}'s message` : "Entered by you"}
            </EffectRow>
            <EffectRow term="Runs on">
              Cloud node <code>{reviewed.runtime}</code>
            </EffectRow>
            <EffectRow term="On confirm">
              Records a pending action request on this delivery, which moves to pending_action. Nothing opens now;
              the request waits for approval.
            </EffectRow>
          </dl>
          {reviewed.warnings.length > 0 ? (
            <ul className="m-0 grid list-none gap-1 rounded-lg bg-amber-soft px-3 py-2 text-xs font-bold text-amber">
              {reviewed.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => onConfirm(reviewed)}
              disabled={pending}
              className="min-h-8 rounded-[7px] border-0 bg-accent px-3 text-[0.76rem] font-extrabold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
            >
              Confirm request
            </button>
            <button type="button" onClick={() => setReviewed(null)} disabled={pending} className={secondaryButton}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function EffectRow({ term, children }: { term: string; children: ReactNode }) {
  return (
    <>
      <dt className="font-extrabold text-faint">{term}</dt>
      <dd className="m-0 text-body [overflow-wrap:anywhere]">{children}</dd>
    </>
  );
}

import type { ActionRequest } from "./message-hub";

// The exact open_url request an owner reviewed. Confirming submits these
// fields and nothing else, so the request cannot drift from what was shown.
export type OpenUrlEffect = {
  type: "open_url";
  target: string;
  host: string;
  runtime: "cloud_node";
  requiresApproval: true;
  // The target matches a URL the remote sender's message supplied.
  fromSender: boolean;
  warnings: string[];
};

export type OpenUrlReview = { ok: true; effect: OpenUrlEffect } | { ok: false; reason: string };

export function reviewOpenUrl(rawTarget: string, senderUrls: readonly string[]): OpenUrlReview {
  const target = rawTarget.trim();
  if (!target) {
    return { ok: false, reason: "Enter the URL to open." };
  }

  let url: URL;
  try {
    url = new URL(target);
  } catch {
    return { ok: false, reason: "Not an absolute URL. Include the scheme, such as https://." };
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    return { ok: false, reason: `Only http and https URLs can be opened, not ${url.protocol}` };
  }

  const host = url.hostname;
  const warnings: string[] = [];
  if (url.username || url.password) {
    warnings.push(`Text before the @ is not the destination. This URL goes to ${host}.`);
  }
  if (host.split(".").some((label) => label.startsWith("xn--"))) {
    warnings.push(`The host uses non-Latin characters and is really ${host}. Check it is the site you expect.`);
  }
  if (url.protocol === "http:") {
    warnings.push("This URL uses http, so the connection is not encrypted.");
  }

  return {
    ok: true,
    effect: {
      type: "open_url",
      target,
      host,
      runtime: "cloud_node",
      requiresApproval: true,
      fromSender: senderUrls.includes(target),
      warnings,
    },
  };
}

export function recordedMatchesReview(effect: OpenUrlEffect, recorded: ActionRequest | null | undefined): boolean {
  return (
    recorded != null &&
    recorded.type === effect.type &&
    recorded.target === effect.target &&
    recorded.runtime === effect.runtime &&
    recorded.requires_approval === effect.requiresApproval
  );
}

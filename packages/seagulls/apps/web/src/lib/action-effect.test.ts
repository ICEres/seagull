import { describe, expect, it } from "vitest";

import { recordedMatchesReview, reviewOpenUrl, type OpenUrlEffect } from "./action-effect";
import type { ActionRequest } from "./message-hub";

function reviewed(target: string, senderUrls: string[] = []): OpenUrlEffect {
  const check = reviewOpenUrl(target, senderUrls);
  if (!check.ok) {
    throw new Error(`expected ${target} to pass review: ${check.reason}`);
  }
  return check.effect;
}

function recorded(overrides: Partial<ActionRequest> = {}): ActionRequest {
  return {
    action_request_id: "action_1",
    type: "open_url",
    target: "https://docs.example.test/guide",
    runtime: "cloud_node",
    requires_approval: true,
    status: "pending",
    created_at: "2026-10-15T00:00:00Z",
    ...overrides,
  };
}

describe("reviewOpenUrl", () => {
  it("names the operation, destination host, runtime, and approval it will request", () => {
    const effect = reviewed("https://docs.example.test/guide?page=2");

    expect(effect).toEqual({
      type: "open_url",
      target: "https://docs.example.test/guide?page=2",
      host: "docs.example.test",
      runtime: "cloud_node",
      requiresApproval: true,
      fromSender: false,
      warnings: [],
    });
  });

  it("submits the trimmed target it displays, not the raw input", () => {
    expect(reviewed("  https://docs.example.test/  ").target).toBe("https://docs.example.test/");
  });

  it("marks a target the remote sender supplied", () => {
    expect(reviewed("https://docs.example.test/", ["https://docs.example.test/"]).fromSender).toBe(true);
    expect(reviewed("https://docs.example.test/", ["https://other.example.test/"]).fromSender).toBe(false);
  });

  it.each([
    ["javascript:alert(1)", "javascript:"],
    ["data:text/html,<b>hi</b>", "data:"],
    ["file:///etc/passwd", "file:"],
  ])("refuses the %s scheme", (target, scheme) => {
    const check = reviewOpenUrl(target, []);

    expect(check.ok).toBe(false);
    expect(check.ok ? "" : check.reason).toContain(scheme);
  });

  it("refuses a target that is not an absolute URL", () => {
    expect(reviewOpenUrl("docs.example.test/guide", []).ok).toBe(false);
    expect(reviewOpenUrl("   ", []).ok).toBe(false);
  });

  it("reports the real host when text before an @ imitates another one", () => {
    const effect = reviewed("https://docs.example.test@attacker.example.test/login");

    expect(effect.host).toBe("attacker.example.test");
    expect(effect.warnings.join(" ")).toContain("attacker.example.test");
  });

  it("shows an internationalized host in its punycode form and warns about it", () => {
    // Cyrillic "а" (U+0430) in place of the Latin "a".
    const effect = reviewed("https://exаmple.test/");

    expect(effect.host).toMatch(/^xn--/);
    expect(effect.warnings.join(" ")).toContain(effect.host);
  });

  it("warns that a plain http target is unencrypted", () => {
    expect(reviewed("http://docs.example.test/").warnings.join(" ")).toContain("http");
  });
});

describe("recordedMatchesReview", () => {
  it("accepts the action request the hub recorded for the reviewed effect", () => {
    expect(recordedMatchesReview(reviewed("https://docs.example.test/guide"), recorded())).toBe(true);
  });

  it.each([
    ["a different target", { target: "https://attacker.example.test/" }],
    ["a different operation", { type: "run_tool" }],
    ["a different runtime", { runtime: "lan_node" }],
    ["no approval requirement", { requires_approval: false }],
  ])("rejects %s", (_, overrides) => {
    expect(recordedMatchesReview(reviewed("https://docs.example.test/guide"), recorded(overrides))).toBe(false);
  });

  it("rejects a missing action request", () => {
    expect(recordedMatchesReview(reviewed("https://docs.example.test/guide"), null)).toBe(false);
  });
});

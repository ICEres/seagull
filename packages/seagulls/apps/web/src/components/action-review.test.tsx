import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActionReview } from "./action-review";
import type { OpenUrlEffect } from "../lib/action-effect";

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = null;
  container = null;
});

type Props = Parameters<typeof ActionReview>[0];

function render(props: Partial<Props> = {}) {
  const onConfirm = vi.fn<(effect: OpenUrlEffect) => void>();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  const rerender = (next: Partial<Props> = {}) =>
    act(() => {
      root?.render(
        <ActionReview
          initialTarget=""
          senderUrls={[]}
          senderHandle="@sender:gulls.ai"
          pending={false}
          onConfirm={onConfirm}
          {...props}
          {...next}
        />,
      );
    });
  rerender();
  return { onConfirm, rerender, view: container };
}

function input(view: HTMLElement): HTMLInputElement {
  const element = view.querySelector('input[aria-label="URL to open"]');
  if (!(element instanceof HTMLInputElement)) {
    throw new Error("URL input not found.");
  }
  return element;
}

function button(view: HTMLElement, label: string): HTMLButtonElement | null {
  return (
    Array.from(view.querySelectorAll("button")).find((candidate) => candidate.textContent?.trim() === label) ?? null
  );
}

function click(view: HTMLElement, label: string): void {
  const target = button(view, label);
  if (!target) {
    throw new Error(`Button "${label}" not found in: ${view.textContent ?? ""}`);
  }
  act(() => target.click());
}

function type(view: HTMLElement, value: string): void {
  const element = input(view);
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  act(() => {
    setter?.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function summary(view: HTMLElement): HTMLElement | null {
  return view.querySelector('[aria-label="Effect summary"]');
}

describe("ActionReview", () => {
  it("states the effect before anything is submitted, then submits exactly what it stated", () => {
    const senderUrl = "https://docs.example.test/guide";
    const { onConfirm, view } = render({ initialTarget: senderUrl, senderUrls: [senderUrl] });

    expect(summary(view)).toBeNull();
    expect(button(view, "Confirm request")).toBeNull();

    click(view, "Review");

    const shown = summary(view)?.textContent ?? "";
    expect(shown).toContain("open_url");
    expect(shown).toContain("docs.example.test");
    expect(shown).toContain("@sender:gulls.ai");
    expect(shown).toContain("cloud_node");
    expect(shown).toContain("Nothing opens now");
    expect(onConfirm).not.toHaveBeenCalled();

    click(view, "Confirm request");

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0][0]).toMatchObject({
      type: "open_url",
      target: senderUrl,
      host: "docs.example.test",
      runtime: "cloud_node",
      requiresApproval: true,
      fromSender: true,
    });
  });

  it("withdraws the review when the URL changes after it was reviewed", () => {
    const { onConfirm, view } = render({ initialTarget: "https://docs.example.test/" });

    click(view, "Review");
    expect(button(view, "Confirm request")).not.toBeNull();

    type(view, "https://attacker.example.test/");

    expect(summary(view)).toBeNull();
    expect(button(view, "Confirm request")).toBeNull();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("refuses a non-web scheme with a reason and offers nothing to confirm", () => {
    const { onConfirm, view } = render();

    type(view, "javascript:alert(1)");
    click(view, "Review");

    expect(view.textContent).toContain("javascript:");
    expect(summary(view)).toBeNull();
    expect(button(view, "Confirm request")).toBeNull();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("names the real destination when the URL disguises its host", () => {
    const { view } = render({ initialTarget: "https://docs.example.test@attacker.example.test/login" });

    click(view, "Review");

    const shown = summary(view)?.textContent ?? "";
    expect(shown).toContain("Text before the @ is not the destination");
    expect(view.querySelector('[data-testid="effect-host"]')?.textContent).toBe("attacker.example.test");
  });

  it("says when the owner typed the URL rather than the sender", () => {
    const { view } = render({ initialTarget: "https://docs.example.test/", senderUrls: ["https://other.example.test/"] });

    click(view, "Review");

    expect(summary(view)?.textContent).toContain("Entered by you");
  });

  it("cannot be confirmed again while a request is in flight", () => {
    const { onConfirm, rerender, view } = render({ initialTarget: "https://docs.example.test/" });

    click(view, "Review");
    click(view, "Confirm request");
    rerender({ pending: true });

    expect(button(view, "Confirm request")?.disabled).toBe(true);
    expect(button(view, "Review")?.disabled).toBe(true);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});

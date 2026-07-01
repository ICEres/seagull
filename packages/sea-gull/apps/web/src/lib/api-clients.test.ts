import { afterEach, describe, expect, it, vi } from "vitest";

import { AiProviderApiError, AiProviderClient } from "./ai-provider";
import { MessageHubClient, MessageHubError } from "./message-hub";
import { SocialApiClient, SocialApiError } from "./api";

describe("API clients", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("rejects invalid JSON responses", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("not-json", { status: 200 }));

    await expect(new SocialApiClient("https://social.example.test").health()).rejects.toMatchObject({
      name: "SocialApiError",
      code: "invalid_json",
      status: 200,
    } satisfies Partial<SocialApiError>);
    await expect(new MessageHubClient("https://message.example.test").health()).rejects.toMatchObject({
      name: "MessageHubError",
      code: "invalid_json",
      status: 200,
    } satisfies Partial<MessageHubError>);
    await expect(new AiProviderClient("https://ai.example.test", "token").health()).rejects.toMatchObject({
      name: "AiProviderApiError",
      code: "invalid_json",
      status: 200,
    } satisfies Partial<AiProviderApiError>);
  });
});

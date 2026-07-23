const DEFAULT_AI_PROVIDER_API_URL = "http://localhost:8400";

export function trimBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

export function aiProviderApiUrl(): string {
  return trimBaseUrl(window.SEAGULL_CONFIG?.aiProviderApiUrl || DEFAULT_AI_PROVIDER_API_URL);
}

type DemoRunPayload = {
  message?: string;
  output_text?: string;
};

export class DemoProviderError extends Error {
  readonly serverMessage?: string;

  constructor(serverMessage?: string) {
    super(serverMessage || "provider error");
    this.name = "DemoProviderError";
    this.serverMessage = serverMessage;
  }
}

export async function landingDemoProviderResponse(text: string): Promise<string> {
  const result = await fetch(aiProviderApiUrl() + "/demo/landing/ai-run", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message: text }),
  });
  const payload: DemoRunPayload = await result.json().catch(() => ({}));
  if (!result.ok) {
    throw new DemoProviderError(payload.message);
  }
  return payload.output_text || "Provider completed the demo run.";
}

/**
 * Shared JSON-over-HTTP base for the browser API clients (social API,
 * message hub, AI provider). Each service keeps a thin error subclass so
 * component-level `instanceof` checks and error unions keep working.
 */

type ErrorPayload = {
  error?: string;
  message?: string;
};

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly service: string;

  constructor(status: number, code: string, message: string, service = "api") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.service = service;
  }
}

export function trimBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

export class JsonApiClient {
  readonly baseUrl: string;
  private readonly getAuthToken?: () => string | null;

  constructor(baseUrl: string, getAuthToken?: () => string | null) {
    this.baseUrl = trimBaseUrl(baseUrl);
    this.getAuthToken = getAuthToken;
  }

  /** Human-readable label used in default error messages. */
  protected get serviceLabel(): string {
    return "API";
  }

  /** Subclasses override this so failures throw their service-specific error. */
  protected createError(status: number, code: string, message: string): ApiError {
    return new ApiError(status, code, message);
  }

  protected async request<T>(method: HttpMethod, path: string, body?: unknown): Promise<T> {
    const headers = new Headers();
    const requestInit: RequestInit = { method, headers };

    if (body !== undefined) {
      headers.set("content-type", "application/json");
      requestInit.body = JSON.stringify(body);
    }
    const authToken = this.getAuthToken?.();
    if (authToken) {
      headers.set("authorization", `Bearer ${authToken}`);
    }

    const response = await fetch(`${this.baseUrl}${path}`, requestInit);
    const text = await response.text();
    const payload = text ? this.parseJson(text, response.status) : {};

    if (!response.ok) {
      const errorPayload = payload as ErrorPayload;
      throw this.createError(
        response.status,
        errorPayload.error ?? "request_failed",
        errorPayload.message ?? `${this.serviceLabel} request failed with ${response.status}`,
      );
    }

    return payload as T;
  }

  private parseJson(text: string, status: number): unknown {
    try {
      return JSON.parse(text);
    } catch {
      throw this.createError(status, "invalid_json", `${this.serviceLabel} returned invalid JSON.`);
    }
  }
}

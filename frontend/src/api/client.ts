import type { components } from "./schema";

export type Schema = components["schemas"];
export type Job = Schema["JobView"];
export type JobDetail = Schema["JobDetail"];
export type Document = Schema["DocumentView"];
export type Report = Schema["Report"];
export type Finding = Schema["Finding"];

let csrfToken = "";
export function setCsrfToken(value: string) {
  csrfToken = value;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (options.method && options.method !== "GET")
    headers.set("X-CSRF-Token", csrfToken);
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      headers,
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, "无法连接服务，请检查网络后重试。");
  }
  if (!response.ok) {
    const error: unknown = await response.json().catch(() => null);
    const message =
      error &&
      typeof error === "object" &&
      "detail" in error &&
      typeof error.detail === "string"
        ? error.detail
        : "请求未完成，请稍后重试。";
    if (response.status === 401 && !path.startsWith("/auth/"))
      window.dispatchEvent(new Event("session-expired"));
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const queryKeys = {
  documents: ["documents"] as const,
  jobs: ["analyses"] as const,
  job: (id: string) => ["analysis", id] as const,
  usage: ["usage"] as const,
  invites: ["invites"] as const,
  account: ["account"] as const,
  adminModels: ["admin-models"] as const,
  models: ["models"] as const,
};

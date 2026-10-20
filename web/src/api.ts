// Thin client for the API. Every rule lives on the server; this only carries requests.

const TOKEN_KEY = "pipeline.token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode: stay signed in for this tab only */
  }
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

function messageFrom(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // Validation errors: name the field in plain words.
    const first = detail[0] as { loc?: unknown[]; msg?: string } | undefined;
    const field = first?.loc?.filter((p) => typeof p === "string" && p !== "body").join(" ");
    return field ? `${field.replace(/_/g, " ")}: ${first?.msg ?? "invalid"}` : (first?.msg ?? "Something is missing.");
  }
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  return "Something went wrong.";
}

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

async function request<T>(method: string, path: string, body?: unknown, params?: Record<string, unknown>): Promise<T> {
  let url = `/api${path}`;
  if (params) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
    const s = q.toString();
    if (s) url += `?${s}`;
  }
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";

  let res: Response;
  try {
    res = await fetch(url, { method, headers, body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "No connection. Check the signal and try again.", null);
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    if (res.status === 401) onUnauthorized();
    const detail = data?.detail ?? data;
    throw new ApiError(res.status, messageFrom(detail), detail);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string, params?: Record<string, unknown>) => request<T>("GET", path, undefined, params),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  /** Files: the browser sets the multipart boundary itself. */
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, form),
};

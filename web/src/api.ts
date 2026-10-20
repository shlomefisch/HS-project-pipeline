// Thin client for the API. Every rule lives on the server; this only carries requests.
import { cacheable, flush, hold, isOffline, newKey, queueLabel, recall, remember, setOffline, waiting, type Waiting } from "./offline";

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

async function send(method: string, url: string, body: unknown, key?: string): Promise<Response> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (key) headers["Idempotency-Key"] = key;
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  return fetch(url, { method, headers, body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body) });
}

async function parse(res: Response): Promise<unknown> {
  const text = await res.text();
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    return null;
  }
}

async function request<T>(method: string, path: string, body?: unknown, params?: Record<string, unknown>): Promise<T> {
  let rel = path;
  if (params) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
    const s = q.toString();
    if (s) rel += `?${s}`;
  }
  const url = `/api${rel}`;
  const label = method !== "GET" ? queueLabel(method, path) : null;

  // Keep the order: if saves are already waiting, this one waits behind them.
  if (label && waiting().length > 0) {
    hold(method, rel, body, label);
    void flushOutbox();
    return null as T;
  }

  const key = label ? newKey() : undefined;
  let res: Response;
  try {
    res = await send(method, url, body, key);
  } catch {
    setOffline(true);
    if (label) {
      hold(method, rel, body, label, key);
      return null as T; // saved on the phone; the bar says it's waiting
    }
    if (method === "GET" && cacheable(rel)) {
      const old = recall<T>(rel);
      if (old !== undefined) return old;
    }
    throw new ApiError(0, "No signal. Saves wait on this phone; this screen needs a connection.", null);
  }
  setOffline(false);
  const data = (await parse(res)) as { detail?: unknown } | null;
  if (!res.ok) {
    if (res.status === 401) onUnauthorized();
    const detail = data?.detail ?? data;
    throw new ApiError(res.status, messageFrom(detail), detail);
  }
  if (method === "GET" && cacheable(rel)) remember(rel, data);
  if (waiting().length) void flushOutbox();
  return data as T;
}

/** Sends what's waiting on this phone. Safe to call any time. */
export function flushOutbox(): Promise<void> {
  return flush(async (w: Waiting) => {
    const res = await send(w.method, `/api${w.path}`, w.body, w.id);
    const data = (await parse(res)) as { detail?: unknown } | null;
    return { ok: res.ok, status: res.status, message: res.ok ? "" : messageFrom(data?.detail ?? data) };
  });
}

export { isOffline };

export const api = {
  get: <T>(path: string, params?: Record<string, unknown>) => request<T>("GET", path, undefined, params),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  /** Files: the browser sets the multipart boundary itself. */
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, form),
};

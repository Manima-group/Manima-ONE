// Thin API client: same-origin /api (proxied by Next), cookie session, CSRF header, typed errors.

export type ErrorDetail = { field?: string; issue?: string; message?: string };

export class ApiError extends Error {
  status: number;
  code: string;
  details: ErrorDetail[];
  actionHint?: string;
  constructor(status: number, code: string, message: string, details: ErrorDetail[] = [], actionHint?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.actionHint = actionHint;
  }
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const d of this.details) {
      if (d.field) out[d.field] = d.message ?? d.issue ?? "Invalid";
    }
    return out;
  }
}

type Opts = { idempotent?: boolean; signal?: AbortSignal };

function newKey() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function request<T>(method: string, url: string, body?: unknown, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", "X-Requested-With": "manima" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.idempotent) headers["Idempotency-Key"] = newKey();
  let res: Response;
  try {
    res = await fetch(url.startsWith("/api") ? url : `/api/v1${url}`, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: opts.signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "NETWORK_ERROR", "Cannot reach the server. Check your connection.");
  }
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    const err = (data as { error?: { code?: string; message?: string; details?: ErrorDetail[]; action_hint?: string } })?.error;
    if (res.status === 401 && typeof window !== "undefined" && !url.includes("/auth/") && !url.endsWith("/me")) {
      // Session expired/revoked: hard navigation clears all in-memory tenant data.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
    }
    throw new ApiError(res.status, err?.code ?? "HTTP_" + res.status, err?.message ?? res.statusText, err?.details ?? [], err?.action_hint);
  }
  return data as T;
}

function safeJson(t: string) {
  try {
    return JSON.parse(t);
  } catch {
    return t;
  }
}

export const api = {
  get: <T,>(url: string, opts?: Opts) => request<T>("GET", url, undefined, opts),
  post: <T,>(url: string, body?: unknown, opts?: Opts) => request<T>("POST", url, body ?? {}, opts),
  patch: <T,>(url: string, body: unknown, opts?: Opts) => request<T>("PATCH", url, body, opts),
  put: <T,>(url: string, body: unknown, opts?: Opts) => request<T>("PUT", url, body, opts),
  del: <T,>(url: string, opts?: Opts) => request<T>("DELETE", url, undefined, opts),
};

export type Page<T> = { data: T[]; total: number; limit: number; offset: number };

export function qs(params: Record<string, string | number | boolean | null | undefined>) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

// Thin fetch wrapper. The session token lives in sessionStorage (cleared when the tab closes);
// the app never renders server data as HTML, which limits the XSS exposure of that choice.

const TOKEN_KEY = "adaptive-ids.token";

export class ApiError extends Error {
  constructor(public status: number, message: string, public details?: unknown) {
    super(message);
  }
}

export const tokenStore = {
  get: (): string | null => { try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set: (t: string) => { try { sessionStorage.setItem(TOKEN_KEY, t); } catch { /* storage unavailable */ } },
  clear: () => { try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ } },
};

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn; }

type Query = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

export function buildQuery(q?: Query): string {
  if (!q) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => p.append(k, String(x)));
    else p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function request<T>(method: string, path: string, opts: { query?: Query; body?: unknown; form?: FormData; raw?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }
  let res: Response;
  try {
    res = await fetch(`/api${path}${buildQuery(opts.query)}`, { method, headers, body });
  } catch {
    throw new ApiError(0, "Cannot reach the Adaptive IDS server. Check that `adaptive-ids serve` is running.");
  }
  if (res.status === 401 && path !== "/auth/login") onUnauthorized();
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    let details: unknown;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") msg = data.detail;
      if (data.reference) msg += ` (reference ${data.reference})`;
      details = data.errors;
    } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, msg, details);
  }
  if (res.status === 204) return undefined as T;
  if (opts.raw) return (await res.text()) as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>("GET", path, { query }),
  getText: (path: string, query?: Query) => request<string>("GET", path, { query, raw: true }),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, { body: body ?? {} }),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, { body }),
  del: <T>(path: string) => request<T>("DELETE", path),
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, { form }),
};

/** Download an authenticated file (CSV/Markdown export) without exposing the token in a URL. */
export async function downloadFile(path: string, filename: string, query?: Query) {
  const text = await api.getText(path, query);
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

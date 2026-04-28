const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 423) throw new ApiError(423, "setup_required");
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const j = await res.json();
      detail = j.detail ?? j.error ?? detail;
    } catch {}
    throw new ApiError(res.status, String(detail));
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") ?? "";
  return ct.includes("application/json") ? ((await res.json()) as T) : ((await res.text()) as unknown as T);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const api = {
  get:    <T>(p: string)               => request<T>("GET", p),
  post:   <T>(p: string, body?: unknown) => request<T>("POST", p, body),
  put:    <T>(p: string, body?: unknown) => request<T>("PUT", p, body),
  patch:  <T>(p: string, body?: unknown) => request<T>("PATCH", p, body),
  delete: <T>(p: string)               => request<T>("DELETE", p),
};

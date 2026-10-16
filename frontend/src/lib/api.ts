const base = (
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  (process.env.NODE_ENV === "production" ? "" : "http://localhost:8000")
).replace(/\/$/, "");
function requestUrl(path: string) {
  return new URL(
    `${base}${path}`,
    typeof window === "undefined" ? undefined : window.location.origin,
  );
}
let accessToken = "";
let activeTenant = "";
export function setToken(token: string) {
  accessToken = token.trim();
  activeTenant = "";
}
export function setTenant(tenant: string) {
  activeTenant = tenant;
}
export async function api<T>(
  path: string,
  method = "GET",
  signal?: AbortSignal,
  payload?: unknown,
): Promise<T> {
  const url = requestUrl(path);
  if (activeTenant) url.searchParams.set("tenant_id", activeTenant);
  const response = await fetch(url, {
    method,
    cache: "no-store",
    signal: signal
      ? AbortSignal.any([signal, AbortSignal.timeout(15000)])
      : AbortSignal.timeout(15000),
    headers: {
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...(payload !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: payload !== undefined ? JSON.stringify(payload) : undefined,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : `Request failed (${response.status})`,
    );
  }
  const body = await response.json();
  function presentation(value: unknown): unknown {
    if (Array.isArray(value)) return value.map(presentation);
    if (value && typeof value === "object") {
      return Object.fromEntries(
        Object.entries(value).map(([key, item]) => [
          key,
          key === "status" &&
          typeof item === "string" &&
          ["HEALTHY", "DEGRADED", "UNHEALTHY", "UNKNOWN"].includes(item)
            ? item.toLowerCase()
            : presentation(item),
        ]),
      );
    }
    return value;
  }
  return presentation(body) as T;
}
export const percent = (n: number | null | undefined) =>
  n == null ? "—" : `${(n * 100).toFixed(1)}%`;
export const ms = (n: number | null | undefined) =>
  n == null ? "—" : `${Math.round(n).toLocaleString()} ms`;
export const time = (s: string | undefined | null) =>
  s
    ? new Date(s).toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Not evaluated";
export const typeName = (s: string) =>
  ({
    payroll: "Payroll",
    e_signature: "E-signature",
    ats: "ATS",
    directory_sync: "Directory sync",
    notifications: "Notifications",
  })[s.toLowerCase()] ?? s;

export const apiBaseUrl = base;
export async function uploadFile<T>(
  file: File,
  format: string,
  signal: AbortSignal,
  digest?: string,
): Promise<T> {
  const url = requestUrl(`/api/imports/${digest ? "commit" : "preview"}`);
  url.searchParams.set("format", format);
  if (activeTenant) url.searchParams.set("tenant_id", activeTenant);
  const response = await fetch(url, {
    method: "POST",
    cache: "no-store",
    signal: AbortSignal.any([signal, AbortSignal.timeout(30000)]),
    headers: {
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      "Content-Type":
        format === "csv"
          ? "text/csv"
          : format === "json"
            ? "application/json"
            : "application/x-ndjson",
      ...(digest
        ? { "X-Confirm-Import": "true", "X-Preview-Digest": digest }
        : {}),
    },
    body: file,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : "File validation/import failed. No success is assumed; check the results or retry safely.",
    );
  return body as T;
}

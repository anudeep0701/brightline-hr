const base = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
let accessToken = "";
export function setToken(token: string) {
  accessToken = token;
}
export async function api<T>(path: string, method = "GET"): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    method,
    cache: "no-store",
    signal: AbortSignal.timeout(15000),
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : `Request failed (${response.status})`,
    );
  }
  return response.json() as Promise<T>;
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

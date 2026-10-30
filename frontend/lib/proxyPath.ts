// Validation for the server-side API proxy: only plain API path segments are forwarded, so the
// proxy can never be used to reach another host or escape the /api prefix.
const SAFE_SEGMENT = /^[A-Za-z0-9._-]+$/;

export function proxyTarget(base: string, segments: string[], search: string): URL | null {
  if (!segments.length || !segments.every((p) => SAFE_SEGMENT.test(p) && p !== ".." && p !== ".")) return null;
  const url = new URL(`/api/${segments.join("/")}`, base);
  if (url.origin !== new URL(base).origin || !url.pathname.startsWith("/api/")) return null;
  url.search = search;
  return url;
}

export const DEFAULT_DASHBOARD_HOSTS = ["127.0.0.1:3000", "localhost:3000", "[::1]:3000"];

export type RequestInfo = { method: string; host: string | null; origin: string | null; secFetchSite: string | null };

// Blocks DNS rebinding (a web page whose domain resolves to 127.0.0.1 sends a foreign Host) and
// cross-site requests (another site's page posting to the dashboard), because the proxy attaches
// the API token to whatever it forwards.
export function requestAllowed(req: RequestInfo, allowedHosts: string[] = DEFAULT_DASHBOARD_HOSTS): boolean {
  const hosts = allowedHosts.map((h) => h.trim().toLowerCase()).filter(Boolean);
  if (!req.host || !hosts.includes(req.host.toLowerCase())) return false;
  if (req.secFetchSite && !["same-origin", "none"].includes(req.secFetchSite)) return false;
  if (req.origin && req.origin !== "null") {
    let o: URL;
    try {
      o = new URL(req.origin);
    } catch {
      return false;
    }
    if (!["http:", "https:"].includes(o.protocol) || !hosts.includes(o.host.toLowerCase())) return false;
  } else if (req.origin === "null" && !["GET", "HEAD"].includes(req.method)) {
    return false;
  }
  return true;
}

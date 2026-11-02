// Server-side proxy to the local InvestIQ API. It adds the API token, which therefore never
// reaches the browser, and only forwards well-formed API paths to the configured local backend.
import { NextRequest } from "next/server";
import { DEFAULT_DASHBOARD_HOSTS, proxyTarget, requestAllowed } from "@/lib/proxyPath";

const API = process.env.INVESTIQ_API_URL ?? "http://127.0.0.1:8765";
const TOKEN = process.env.INVESTIQ_API_TOKEN ?? "";
const MAX_BODY = 2_000_000;
const HOSTS = process.env.INVESTIQ_DASHBOARD_HOSTS?.split(",") ?? DEFAULT_DASHBOARD_HOSTS;

async function forward(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const allowed = requestAllowed({
    method: req.method,
    host: req.headers.get("host"),
    origin: req.headers.get("origin"),
    secFetchSite: req.headers.get("sec-fetch-site"),
  }, HOSTS);
  if (!allowed) return Response.json({ detail: "forbidden" }, { status: 403 });
  if (!TOKEN) {
    return Response.json({ detail: "INVESTIQ_API_TOKEN is not set for the dashboard (see docs/INSTALL.md)." }, { status: 503 });
  }
  const url = proxyTarget(API, path, req.nextUrl.search);
  if (!url) return Response.json({ detail: "invalid path" }, { status: 400 });
  const headers: Record<string, string> = { Authorization: `Bearer ${TOKEN}` };
  const ctype = req.headers.get("content-type");
  if (ctype) headers["Content-Type"] = ctype;
  let body: ArrayBuffer | undefined;
  if (req.method !== "GET" && req.method !== "HEAD") {
    body = await req.arrayBuffer();
    if (body.byteLength > MAX_BODY) return Response.json({ detail: "request too large" }, { status: 413 });
  }
  try {
    const res = await fetch(url, { method: req.method, headers, body, cache: "no-store" });
    const out = new Headers();
    for (const h of ["content-type", "content-disposition", "content-security-policy"]) {
      const v = res.headers.get(h);
      if (v) out.set(h, v);
    }
    return new Response(res.body, { status: res.status, headers: out });
  } catch {
    return Response.json({ detail: "InvestIQ API is not reachable. Is 'investiq serve' running?" }, { status: 502 });
  }
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const dynamic = "force-dynamic";

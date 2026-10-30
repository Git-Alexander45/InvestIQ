import type { NextConfig } from "next";

// Local-only dashboard. Security headers apply to every page; the API token never reaches the
// browser (it is added by the server-side proxy in app/api/iq).
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const config: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      // Pages may never be framed, except stored report HTML shown in our own sandboxed viewer.
      { source: "/((?!api/iq/reports/).*)", headers: [{ key: "X-Frame-Options", value: "DENY" }] },
      { source: "/api/iq/reports/:id/html", headers: [{ key: "X-Frame-Options", value: "SAMEORIGIN" }] },
    ];
  },
};

export default config;

import type { NextConfig } from "next";

// Where the Next server itself reaches the API. Only the server uses this; the
// browser never sees it. Locally that is the API on this machine; inside the
// compose network it is the `api` service.
const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Emits a self-contained server bundle, so the runtime image carries only
  // what the app actually imports rather than the whole node_modules tree.
  output: "standalone",

  // The browser calls /api on the same origin it loaded the page from, and
  // Next forwards it to the backend. One address then serves the whole app,
  // which is what makes a single tunnel work: a visitor's browser never tries
  // to reach 127.0.0.1, which on their machine would be their own computer.
  // Same origin also means no CORS to get wrong.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_INTERNAL_URL}/api/:path*` }];
  },
};

export default nextConfig;

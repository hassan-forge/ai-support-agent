import type { NextConfig } from "next";

// The browser calls /api/*, and Next.js forwards it to the FastAPI service.
// That keeps the API off the public internet and avoids CORS entirely.
const API_URL = process.env.API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/:path*` }];
  },
};

export default nextConfig;

import type { NextConfig } from "next";

// The browser talks to /api/* on this site; Next forwards it to the FastAPI backend.
// That keeps the backend URL in one place and avoids cross-origin requests.
const apiUrl = (process.env.API_URL ?? "http://localhost:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // The share-card images read their fonts from disk at request time.
  outputFileTracingIncludes: {
    "/opengraph-image": ["./src/og/fonts/*.woff"],
    "/stocks/[ticker]/opengraph-image": ["./src/og/fonts/*.woff"],
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};

export default nextConfig;

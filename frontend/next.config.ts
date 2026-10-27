import path from "node:path";
import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = {
  // Production: static export to `out/`, served by FastAPI on the same origin.
  output: isDev ? undefined : "export",
  trailingSlash: false,
  images: { unoptimized: true },
  // Pin the workspace root (a stray lockfile in the user's home dir confuses detection).
  turbopack: { root: path.resolve(__dirname) },
  // Dev only: proxy /api/* to the FastAPI backend on :8000.
  ...(isDev
    ? {
        async rewrites() {
          return [{ source: "/api/:path*", destination: "http://localhost:8000/api/:path*" }];
        },
      }
    : {}),
};

export default nextConfig;

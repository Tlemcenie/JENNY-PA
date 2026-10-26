import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Sortie « standalone » : build autonome (node server.js) pour une image
  // Docker minimale, idéale pour Cloud Run. Voir frontend/Dockerfile + DEPLOY.md.
  output: "standalone",
  async headers() {
    return [
      // anti-iframe sauf le widget
      {
        source: "/((?!widget/).*)",
        headers: [
          { key: "Content-Security-Policy", value: "frame-ancestors 'self'" },
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
        ],
      },
      // widget : iframe ok partout
      {
        source: "/widget/:path*",
        headers: [
          { key: "Content-Security-Policy", value: "frame-ancestors *" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;

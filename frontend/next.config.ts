import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Sortie « standalone » : build autonome (node server.js) pour une image
  // Docker minimale, idéale pour Cloud Run. Voir frontend/Dockerfile + DEPLOY.md.
  output: "standalone",
};

export default nextConfig;

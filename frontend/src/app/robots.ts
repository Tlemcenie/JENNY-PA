import type { MetadataRoute } from "next";
import { getSiteUrl } from "@/lib/site-url";

// pages privées : noindex dans leur layout
// pas de liste à tenir ici
const BLOCKED = [
  // widget : iframe, pas une page
  "/widget/",
];

export default async function robots(): Promise<MetadataRoute.Robots> {
  const site = await getSiteUrl();
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: BLOCKED }],
    sitemap: `${site}/sitemap.xml`,
  };
}

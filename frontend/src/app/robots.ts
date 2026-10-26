import type { MetadataRoute } from "next";
import { getSiteUrl } from "@/lib/site-url";

// espace connecté : pas d'index
// le layout (dashboard) met aussi noindex
const PRIVATE = [
  "/admin",
  "/analytics",
  "/assistant",
  "/brain",
  "/calendar",
  "/campaigns",
  "/channels",
  "/chat",
  "/conversations",
  "/customers",
  "/dashboard",
  "/efficacy",
  "/forgot-password",
  "/knowledge",
  "/lab",
  "/learning",
  "/messages",
  "/onboarding",
  "/prestations",
  "/profile",
  "/stats",
  "/team",
  "/verify",
  // widget : iframe, pas une page
  "/widget/",
];

export default async function robots(): Promise<MetadataRoute.Robots> {
  const site = await getSiteUrl();
  return {
    rules: [{ userAgent: "*", allow: ["/", "/book/"], disallow: PRIVATE }],
    sitemap: `${site}/sitemap.xml`,
  };
}

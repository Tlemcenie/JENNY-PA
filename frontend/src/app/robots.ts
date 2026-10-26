import type { MetadataRoute } from "next";
import { getSiteUrl } from "@/lib/site-url";

// espace connecté : pas d'index
const PRIVATE = [
  "/admin",
  "/analytics",
  "/assistant",
  "/brain",
  "/calendar",
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
  "/verify",
];

export default async function robots(): Promise<MetadataRoute.Robots> {
  const site = await getSiteUrl();
  return {
    rules: [{ userAgent: "*", allow: ["/", "/book/"], disallow: PRIVATE }],
    sitemap: `${site}/sitemap.xml`,
  };
}

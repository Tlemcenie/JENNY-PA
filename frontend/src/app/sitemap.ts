import type { MetadataRoute } from "next";
import { getSiteUrl } from "@/lib/site-url";

// pages publiques du site
const PAGES: { path: string; priority: number; freq: "weekly" | "monthly" | "yearly" }[] = [
  { path: "", priority: 1, freq: "weekly" },
  { path: "/register", priority: 0.8, freq: "monthly" },
  { path: "/login", priority: 0.5, freq: "yearly" },
  { path: "/conditions", priority: 0.3, freq: "yearly" },
  { path: "/confidentialite", priority: 0.3, freq: "yearly" },
];

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const site = await getSiteUrl();
  return PAGES.map((p) => ({
    url: `${site}${p.path}`,
    changeFrequency: p.freq,
    priority: p.priority,
  }));
}

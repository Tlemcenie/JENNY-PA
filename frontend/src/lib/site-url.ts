import { headers } from "next/headers";

// url publique du site

function clean(url: string): string {
  return url.trim().replace(/\/+$/, "");
}

/** Origine publique, env puis requête. */
export async function getSiteUrl(): Promise<string> {
  const fromEnv = process.env.NEXT_PUBLIC_SITE_URL;
  if (fromEnv && /^https?:\/\//.test(fromEnv)) return clean(fromEnv);
  try {
    const h = await headers();
    const host = (h.get("x-forwarded-host") || h.get("host") || "").split(",")[0].trim();
    // hôte valide seulement
    if (host && /^[a-z0-9.-]+(:\d+)?$/i.test(host)) {
      const proto = (h.get("x-forwarded-proto") || "").split(",")[0].trim();
      const local = /^(localhost|127\.0\.0\.1)(:|$)/.test(host);
      return `${proto === "http" || proto === "https" ? proto : local ? "http" : "https"}://${host}`;
    }
  } catch {
    // hors requête
  }
  return "http://localhost:3000";
}

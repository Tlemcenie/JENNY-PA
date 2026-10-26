import { cache } from "react";
import { ApiError, request, type BookingBusinessInfo } from "./api";

// lecture serveur de la page publique

/** Infos publiques, champs bonus optionnels. */
export interface PublicBookingInfo extends BookingBusinessInfo {
  phone?: string | null;
  address?: string | null;
  city?: string | null;
  postal_code?: string | null;
}

export type PublicBookingResult =
  | { status: "ok"; info: PublicBookingInfo }
  | { status: "notfound" }
  | { status: "error" };

const TIMEOUT_MS = 2500;
const TTL_OK_MS = 120_000;
const TTL_NOTFOUND_MS = 60_000;
const MAX_ENTRIES = 300;

// petit cache mémoire
const memo = new Map<string, { exp: number; value: Promise<PublicBookingResult> }>();

async function fetchBooking(slug: string): Promise<PublicBookingResult> {
  try {
    const info = await request<PublicBookingInfo>(
      `/api/v1/public/booking/${encodeURIComponent(slug)}`,
      { signal: AbortSignal.timeout(TIMEOUT_MS) }
    );
    if (!info || typeof info.name !== "string") return { status: "error" };
    return { status: "ok", info };
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return { status: "notfound" };
    return { status: "error" };
  }
}

/** Infos salon côté serveur, jamais d'exception. */
export const getPublicBooking = cache(async (slug: string): Promise<PublicBookingResult> => {
  const now = Date.now();
  const hit = memo.get(slug);
  if (hit && hit.exp > now) return hit.value;

  const value = fetchBooking(slug);
  memo.set(slug, { exp: now + TTL_OK_MS, value });
  if (memo.size > MAX_ENTRIES) {
    const oldest = memo.keys().next().value;
    if (oldest !== undefined) memo.delete(oldest);
  }

  const res = await value;
  // erreur : pas de cache
  if (res.status === "error") memo.delete(slug);
  else if (res.status === "notfound") memo.set(slug, { exp: now + TTL_NOTFOUND_MS, value });
  return res;
});

// jours schema.org
const DAYS: Record<string, string> = {
  mon: "Monday",
  tue: "Tuesday",
  wed: "Wednesday",
  thu: "Thursday",
  fri: "Friday",
  sat: "Saturday",
  sun: "Sunday",
};

export const DAY_LABELS: [string, string][] = [
  ["mon", "Lundi"],
  ["tue", "Mardi"],
  ["wed", "Mercredi"],
  ["thu", "Jeudi"],
  ["fri", "Vendredi"],
  ["sat", "Samedi"],
  ["sun", "Dimanche"],
];

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

/** Plage valide ou null. */
export function dayWindow(info: PublicBookingInfo, key: string): [string, string] | null {
  const w = info.business_hours?.[key];
  if (!Array.isArray(w) || w.length !== 2) return null;
  const [open, close] = w;
  if (!HHMM.test(open) || !HHMM.test(close) || close <= open) return null;
  return [open, close];
}

/** Données structurées HairSalon. */
export function hairSalonJsonLd(info: PublicBookingInfo, url: string): Record<string, unknown> {
  // regroupe les jours identiques
  const groups = new Map<string, string[]>();
  for (const key of Object.keys(DAYS)) {
    const w = dayWindow(info, key);
    if (!w) continue;
    const k = w.join("-");
    groups.set(k, [...(groups.get(k) ?? []), `https://schema.org/${DAYS[key]}`]);
  }
  const hours = [...groups.entries()].map(([k, days]) => {
    const [opens, closes] = k.split("-");
    return { "@type": "OpeningHoursSpecification", dayOfWeek: days, opens, closes };
  });

  const ld: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "HairSalon",
    name: info.name,
    url,
    potentialAction: {
      "@type": "ReserveAction",
      target: { "@type": "EntryPoint", urlTemplate: url, inLanguage: "fr" },
    },
  };
  if (info.description?.trim()) ld.description = info.description.trim();
  if (info.phone?.trim()) ld.telephone = info.phone.trim();
  if (info.address?.trim()) {
    ld.address = {
      "@type": "PostalAddress",
      streetAddress: info.address.trim(),
      ...(info.postal_code ? { postalCode: info.postal_code } : {}),
      ...(info.city ? { addressLocality: info.city } : {}),
      addressCountry: "FR",
    };
  }
  if (hours.length) ld.openingHoursSpecification = hours;
  return ld;
}

/** JSON sûr dans une balise script. */
export function safeJsonLd(data: unknown): string {
  return JSON.stringify(data)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026");
}

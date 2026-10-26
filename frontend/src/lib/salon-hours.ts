import type { PublicBookingInfoFull } from "./api-staff";

// horaires du salon, serveur et client

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
export function dayWindow(info: PublicBookingInfoFull, key: string): [string, string] | null {
  const w = info.business_hours?.[key];
  if (!Array.isArray(w) || w.length !== 2) return null;
  const [open, close] = w;
  if (!HHMM.test(open) || !HHMM.test(close) || close <= open) return null;
  return [open, close];
}

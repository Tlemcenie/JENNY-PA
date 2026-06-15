"use client";

import { formatRelativeTime } from "@/lib/utils";
import { useTick } from "@/lib/time-context";

/**
 * Heure relative (« il y a 3 min ») qui se met à jour toute seule grâce à
 * l'horloge partagée (TimeProvider), sans recharger la page.
 */
export function RelativeTime({ date, className }: { date: string | Date; className?: string }) {
  useTick(); // re-render périodique
  return <span className={className}>{formatRelativeTime(date)}</span>;
}

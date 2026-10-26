// tendance honnête du volume

export type DayCount = { count: number };

export type Trend = { pct: number; span: number };

/** Compare deux blocs de semaines complètes. */
export function computeTrend(daily: DayCount[]): Trend | null {
  // 1er jour tronqué, aujourd'hui pas fini
  const full = daily.slice(1, -1);
  // semaines entières, même taille
  const weeks = Math.floor(full.length / 14) * 14;
  if (weeks === 0) return null;
  const kept = full.slice(full.length - weeks);
  const span = weeks / 2;
  const sum = (xs: DayCount[]) => xs.reduce((s, d) => s + d.count, 0);
  const first = sum(kept.slice(0, span));
  const second = sum(kept.slice(span));
  if (first === 0) return null; // rien à comparer
  // arrondi, pas de « -0 % »
  const pct = Math.round(((second - first) / first) * 100) || 0;
  return { pct, span };
}

"use client";

import type { BusinessHours } from "@/lib/api";

/** éditeur d'horaires compact */

export const WEEK_DAYS: { key: string; label: string }[] = [
  { key: "mon", label: "Lundi" },
  { key: "tue", label: "Mardi" },
  { key: "wed", label: "Mercredi" },
  { key: "thu", label: "Jeudi" },
  { key: "fri", label: "Vendredi" },
  { key: "sat", label: "Samedi" },
  { key: "sun", label: "Dimanche" },
];

export type DayHours = { open: boolean; from: string; to: string };
export type WeekHours = Record<string, DayHours>;

// mêmes horaires que le repli serveur
const FALLBACK: Record<string, [string, string] | null> = {
  mon: ["09:00", "19:00"],
  tue: ["09:00", "19:00"],
  wed: ["09:00", "19:00"],
  thu: ["09:00", "19:00"],
  fri: ["09:00", "19:00"],
  sat: ["09:00", "18:00"],
  sun: null,
};

export function weekFromBusiness(bh: BusinessHours | null | undefined): WeekHours {
  const src = bh && Object.values(bh).some((v) => Array.isArray(v)) ? bh : FALLBACK;
  const out: WeekHours = {};
  for (const d of WEEK_DAYS) {
    const rng = src[d.key];
    out[d.key] = Array.isArray(rng) && rng.length === 2
      ? { open: true, from: rng[0], to: rng[1] }
      : { open: false, from: "09:00", to: "19:00" };
  }
  return out;
}

export function weekToBusiness(week: WeekHours): BusinessHours | null {
  const out: BusinessHours = {};
  let anyOpen = false;
  for (const d of WEEK_DAYS) {
    const s = week[d.key];
    if (s?.open) {
      out[d.key] = [s.from, s.to];
      anyOpen = true;
    } else {
      out[d.key] = null;
    }
  }
  return anyOpen ? out : null;
}

/** jour mal saisi, sinon null */
export function invalidDay(week: WeekHours): string | null {
  for (const d of WEEK_DAYS) {
    const s = week[d.key];
    if (s?.open && !(s.from < s.to)) return d.label;
  }
  return null;
}

export function HoursEditor({ value, onChange }: { value: WeekHours; onChange: (next: WeekHours) => void }) {
  const set = (key: string, patch: Partial<DayHours>) =>
    onChange({ ...value, [key]: { ...value[key], ...patch } });

  return (
    <div className="flex flex-col gap-2">
      {WEEK_DAYS.map((d) => {
        const s = value[d.key];
        return (
          <div
            key={d.key}
            className="rounded-xl bg-jenny-surface border border-jenny-divider px-4 py-2.5 flex items-center gap-3 flex-wrap"
          >
            <label className="flex items-center gap-2.5 w-[130px] cursor-pointer select-none">
              <input
                type="checkbox"
                checked={s.open}
                onChange={(e) => set(d.key, { open: e.target.checked })}
                className="w-4 h-4 accent-jenny-coral cursor-pointer"
              />
              <span className="text-[14px] font-medium text-jenny-text">{d.label}</span>
            </label>
            {s.open ? (
              <div className="flex items-center gap-2 text-[13px] text-jenny-text-secondary">
                <input
                  type="time"
                  aria-label={`${d.label}, ouverture`}
                  value={s.from}
                  onChange={(e) => set(d.key, { from: e.target.value })}
                  className="h-9 px-2 rounded-lg bg-jenny-bg border border-jenny-divider text-jenny-text"
                />
                à
                <input
                  type="time"
                  aria-label={`${d.label}, fermeture`}
                  value={s.to}
                  onChange={(e) => set(d.key, { to: e.target.value })}
                  className="h-9 px-2 rounded-lg bg-jenny-bg border border-jenny-divider text-jenny-text"
                />
              </div>
            ) : (
              <span className="text-[13px] text-jenny-text-secondary">Fermé</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

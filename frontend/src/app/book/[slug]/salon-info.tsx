import { Fragment } from "react";
import type { PublicBookingInfoFull } from "@/lib/api-staff";
import { DAY_LABELS, dayWindow } from "@/lib/salon-hours";

/** Infos pratiques du salon. */
export default function SalonInfo({ info }: { info: PublicBookingInfoFull }) {
  const phone = info.phone?.trim();
  const prestations = info.prestations ?? [];
  const days = DAY_LABELS.map(([key, label]) => ({ key, label, w: dayWindow(info, key) }));
  // pas d'horaires, pas de bloc
  const hasHours = days.some((d) => d.w);

  return (
    <section aria-labelledby="salon-infos" className="mt-6">
      <div
        className="w-full rounded-[24px] p-6 sm:p-7"
        style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}
      >
        <h2
          id="salon-infos"
          className="font-mono text-[11px] tracking-[0.22em] uppercase text-jenny-coral mb-3"
        >
          Infos pratiques
        </h2>
        <p className="text-[15px] font-semibold break-words">{info.name}</p>
        {phone && (
          <p className="mt-1 text-[13.5px]">
            <a
              href={`tel:${phone.replace(/[^\d+]/g, "")}`}
              className="text-[#F4F1ED]/80 underline-offset-2 hover:underline hover:text-white"
            >
              {phone}
            </a>
          </p>
        )}

        {hasHours && (
          <>
            <h3 className="mt-5 mb-2 text-[13px] font-semibold text-[#F4F1ED]/85">
              Horaires d&apos;ouverture
            </h3>
            <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1.5 text-[13.5px]">
              {days.map(({ key, label, w }) => (
                <Fragment key={key}>
                  <dt className="text-[#F4F1ED]/65">{label}</dt>
                  <dd className={w ? "tabular-nums text-right" : "text-right text-[#F4F1ED]/50"}>
                    {w ? `${w[0]} – ${w[1]}` : "Fermé"}
                  </dd>
                </Fragment>
              ))}
            </dl>
          </>
        )}

        {prestations.length > 0 && (
          <>
            <h3 className="mt-5 mb-2 text-[13px] font-semibold text-[#F4F1ED]/85">Prestations</h3>
            <ul className="space-y-1.5 text-[13.5px]">
              {prestations.map((p) => (
                <li key={p.id} className="flex items-baseline justify-between gap-4">
                  <span className="min-w-0 break-words text-[#F4F1ED]/80">{p.name}</span>
                  <span className="shrink-0 tabular-nums text-right text-[#F4F1ED]/60">
                    {p.duration_minutes} min
                    {p.price_cents ? ` · ${(p.price_cents / 100).toLocaleString("fr-FR")} €` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}

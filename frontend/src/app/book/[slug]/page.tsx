import { Fragment } from "react";
import type { Metadata, Viewport } from "next";
import BookingClient from "./booking-client";
import {
  DAY_LABELS,
  dayWindow,
  getPublicBooking,
  hairSalonJsonLd,
  safeJsonLd,
  type PublicBookingInfo,
} from "@/lib/api-public";
import { getSiteUrl } from "@/lib/site-url";

// page publique de réservation

type Props = { params: Promise<{ slug: string }> };

export const viewport: Viewport = {
  themeColor: "#0E0B14",
  colorScheme: "dark",
};

// description courte pour partage
function describe(info: PublicBookingInfo): string {
  const base =
    info.description?.trim() ||
    `Prenez rendez-vous en ligne chez ${info.name} : choisissez votre créneau en quelques secondes, 24h/24.`;
  return base.length > 160 ? `${base.slice(0, 157).trimEnd()}…` : base;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const [res, site] = await Promise.all([getPublicBooking(slug), getSiteUrl()]);
  const url = `${site}/book/${encodeURIComponent(slug)}`;

  if (res.status === "notfound") {
    return {
      title: "Page de réservation introuvable",
      robots: { index: false, follow: false },
    };
  }

  // api injoignable : titre neutre
  if (res.status === "error") {
    return {
      metadataBase: new URL(site),
      title: "Réservation en ligne",
      description: "Choisissez votre créneau et réservez en quelques clics.",
      alternates: { canonical: url },
    };
  }

  const { info } = res;
  const description = describe(info);
  return {
    metadataBase: new URL(site),
    title: { absolute: `${info.name} · Réservation en ligne` },
    description,
    alternates: { canonical: url },
    openGraph: {
      type: "website",
      locale: "fr_FR",
      url,
      siteName: info.name,
      title: `${info.name} · Réservez en ligne`,
      description,
    },
    twitter: {
      card: "summary_large_image",
      title: `${info.name} · Réservez en ligne`,
      description,
    },
  };
}

export default async function BookPage({ params }: Props) {
  const { slug } = await params;
  const [res, site] = await Promise.all([getPublicBooking(slug), getSiteUrl()]);

  return (
    <BookingClient slug={slug}>
      {res.status === "ok" && (
        <SalonInfo info={res.info} url={`${site}/book/${encodeURIComponent(slug)}`} />
      )}
    </BookingClient>
  );
}

// infos pratiques rendues serveur
function SalonInfo({ info, url }: { info: PublicBookingInfo; url: string }) {
  const phone = info.phone?.trim();
  const address = [info.address, [info.postal_code, info.city].filter(Boolean).join(" ")]
    .map((part) => part?.trim())
    .filter(Boolean)
    .join(", ");
  const days = DAY_LABELS.map(([key, label]) => ({ key, label, w: dayWindow(info, key) }));
  // pas d'horaires, pas de bloc
  const hasHours = days.some((d) => d.w);

  return (
    <section aria-labelledby="salon-infos" className="mt-6">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: safeJsonLd(hairSalonJsonLd(info, url)) }}
      />
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
        <p className="text-[15px] font-semibold">{info.name}</p>
        {address && <p className="mt-1 text-[13.5px] text-[#F4F1ED]/65">{address}</p>}
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
      </div>
    </section>
  );
}

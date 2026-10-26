import type { Metadata, Viewport } from "next";
import { notFound } from "next/navigation";
import BookingClient from "./booking-client";
import {
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
  // vrai 404, pas de soft 404
  if (res.status === "notfound") notFound();
  const info = res.status === "ok" ? res.info : null;
  const url = `${site}/book/${encodeURIComponent(slug)}`;

  return (
    <>
      {/* données seo, serveur seul */}
      {info && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: safeJsonLd(hairSalonJsonLd(info, url)) }}
        />
      )}
      <BookingClient slug={slug} initialInfo={info} />
    </>
  );
}

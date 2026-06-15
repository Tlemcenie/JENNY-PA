import BookingClient from "./booking-client";

// Page publique de réservation (esprit Calendly, DA « Jenny Front »).
// Hors du groupe (dashboard) : aucune auth, aucune sidebar — hérite du layout
// racine (fond deep-night appliqué côté client).
//
// Next.js 16 — route dynamique [slug] : `params` est une Promise. On l'attend
// ici dans un composant serveur (Option a) puis on passe le slug, déjà résolu,
// à un composant client dédié qui porte toute l'interactivité.
export default async function BookPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  return <BookingClient slug={slug} />;
}

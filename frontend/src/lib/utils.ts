import { clsx, type ClassValue } from "clsx";
import { formatDistanceToNow } from "date-fns";
import { fr } from "date-fns/locale";

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

export function generateUUID(): string {
  return crypto.randomUUID();
}

export function formatDate(date: string | Date): string {
  return new Intl.DateTimeFormat("fr-FR", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(date));
}

export function formatRelativeTime(date: string | Date): string {
  const d = new Date(date);
  const diffMin = (Date.now() - d.getTime()) / 60000;
  if (diffMin < 1) return "À l'instant";
  // Au-delà d'une semaine, on affiche la date complète (plus lisible).
  if (diffMin >= 7 * 24 * 60) return formatDate(date);
  return formatDistanceToNow(d, { addSuffix: true, locale: fr });
}

export function truncate(str: string, length: number): string {
  if (str.length <= length) return str;
  return str.slice(0, length) + "...";
}

// Montant stocké en plus petite unité (centimes) → libellé monétaire localisé.
export function formatMoney(minor: number | null | undefined, currency = "EUR"): string {
  const value = (minor ?? 0) / 100;
  try {
    return new Intl.NumberFormat("fr-FR", { style: "currency", currency }).format(value);
  } catch {
    // Devise inconnue d'Intl → repli simple.
    return `${value.toFixed(2)} ${currency}`;
  }
}

export function channelLabel(channel: string): string {
  const labels: Record<string, string> = {
    whatsapp: "WhatsApp",
    instagram: "Instagram",
    twitter: "Twitter",
    email: "Email",
    snapchat: "Snapchat",
    form: "Formulaire",
    api: "API",
  };
  return labels[channel] || channel;
}

export function channelColor(channel: string): string {
  const colors: Record<string, string> = {
    whatsapp: "bg-jenny-whatsapp",
    instagram: "bg-jenny-instagram",
    twitter: "bg-jenny-twitter",
    email: "bg-jenny-email",
    snapchat: "bg-yellow-400",
    form: "bg-jenny-slate",
    api: "bg-jenny-coral",
  };
  return colors[channel] || "bg-jenny-slate";
}

// Met une majuscule sur la première lettre (repli pour les libellés inconnus).
function capitalize(value: string): string {
  if (!value) return value;
  return value.charAt(0).toUpperCase() + value.slice(1);
}

// Statuts de conversation (open/closed) et de message (received/processing/responded).
export function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    open: "Ouverte",
    closed: "Fermée",
    archived: "Archivée",
    received: "Reçu",
    processing: "En cours",
    responded: "Répondu",
    escalated: "Escaladé",
    resolved: "Résolu",
    pending: "En attente",
  };
  return labels[status] || capitalize(status);
}

// Catégories de connaissances et de messages.
export function categoryLabel(category: string): string {
  const labels: Record<string, string> = {
    general: "Général",
    horaires: "Horaires",
    tarifs: "Tarifs",
    faq: "FAQ",
    politique: "Politique",
    services: "Services",
    equipe: "Équipe",
    commande: "Commande",
    livraison: "Livraison",
    paiement: "Paiement",
    retour: "Retour",
    reclamation: "Réclamation",
    autre: "Autre",
  };
  return labels[category] || capitalize(category);
}

// Source d'une entrée de connaissances (texte saisi ou PDF importé).
export function sourceLabel(source: string): string {
  const labels: Record<string, string> = {
    text: "Texte",
    pdf: "PDF",
    manual: "Manuel",
    url: "Lien",
  };
  return labels[source] || capitalize(source);
}

// Intentions détectées par le classifieur (cf. ml/models/intent/config.py).
export function intentLabel(intent: string): string {
  const labels: Record<string, string> = {
    greeting: "Salutation",
    order_status: "Suivi de commande",
    pricing: "Tarifs",
    appointment: "Rendez-vous",
    complaint: "Réclamation",
    faq: "FAQ",
    closing: "Fin de conversation",
    escalation: "Transfert humain",
    payment: "Paiement",
    quote: "Devis",
    planning: "Planning",
    general: "Général",
    small_talk: "Bavardage",
    payment_question: "Moyens de paiement",
  };
  return labels[intent] || capitalize(intent);
}

// Rôle d'un membre dans l'entreprise (cf. business_member.role).
export function roleLabel(role: string): string {
  const labels: Record<string, string> = {
    owner: "Propriétaire",
    admin: "Administrateur",
    member: "Membre",
    agent: "Agent",
  };
  return labels[role] || capitalize(role);
}

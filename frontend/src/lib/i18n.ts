// Configuration i18n (FR/EN) via i18next + react-i18next (#20).
// FR est la langue par défaut (le produit est conçu en français) ; EN est une
// traduction complète des éléments de chrome (navigation, barre, actions
// communes). La langue est persistée dans localStorage `jenny-lang`.

import i18n from "i18next";
import { initReactI18next } from "react-i18next";

export const LANGS = [
  { code: "fr", label: "Français", flag: "🇫🇷" },
  { code: "en", label: "English", flag: "🇬🇧" },
] as const;

export type LangCode = (typeof LANGS)[number]["code"];

const fr = {
  nav: {
    dashboard: "Tableau de bord",
    chat: "Test Jenny (client)",
    assistant: "Assistant Jenny",
    conversations: "Conversations",
    customers: "Clients",
    channels: "Canaux",
    messages: "Messages",
    knowledge: "Base de connaissances",
    learning: "Apprentissage",
    brain: "Cerveau de Jenny",
    analytics: "Analytics",
    efficacy: "Efficacité",
    lab: "Modèle maison",
    stats: "Statistiques",
    prestations: "Prestations",
    calendar: "Agenda",
    settings: "Configuration",
    logout: "Déconnexion",
    admin: "Administration",
    account: "Compte",
    autopilot: "Mode auto-pilote",
    autopilotDesc: "Jenny gère seule les questions courantes.",
    autopilotOn: "Activé",
  },
  topbar: {
    search: "Rechercher",
    notifications: "Notifications",
    markAllRead: "Tout lire",
    noNotifications: "Aucune notification",
    appearance: "Apparence",
    api: "API",
    offline: "Hors ligne",
  },
  theme: {
    title: "Thème",
    light: "Clair",
    dark: "Sombre",
    system: "Système",
    accent: "Couleur d'accent",
  },
  common: {
    save: "Enregistrer",
    cancel: "Annuler",
    delete: "Supprimer",
    edit: "Modifier",
    close: "Fermer",
    loading: "Chargement…",
    language: "Langue",
  },
  priority: {
    low: "Basse",
    medium: "Normale",
    high: "Haute",
    critical: "Critique",
  },
};

const en: typeof fr = {
  nav: {
    dashboard: "Dashboard",
    chat: "Test Jenny (customer)",
    assistant: "Jenny Assistant",
    conversations: "Conversations",
    customers: "Customers",
    channels: "Channels",
    messages: "Messages",
    knowledge: "Knowledge base",
    learning: "Learning",
    brain: "Jenny's brain",
    analytics: "Analytics",
    efficacy: "Efficiency",
    lab: "Home model",
    stats: "Stats",
    prestations: "Services",
    calendar: "Calendar",
    settings: "Settings",
    logout: "Sign out",
    admin: "Administration",
    account: "Account",
    autopilot: "Auto-pilot mode",
    autopilotDesc: "Jenny handles common questions on her own.",
    autopilotOn: "On",
  },
  topbar: {
    search: "Search",
    notifications: "Notifications",
    markAllRead: "Mark all read",
    noNotifications: "No notifications",
    appearance: "Appearance",
    api: "API",
    offline: "Offline",
  },
  theme: {
    title: "Theme",
    light: "Light",
    dark: "Dark",
    system: "System",
    accent: "Accent color",
  },
  common: {
    save: "Save",
    cancel: "Cancel",
    delete: "Delete",
    edit: "Edit",
    close: "Close",
    loading: "Loading…",
    language: "Language",
  },
  priority: {
    low: "Low",
    medium: "Normal",
    high: "High",
    critical: "Critical",
  },
};

export function getStoredLang(): LangCode {
  if (typeof localStorage === "undefined") return "fr";
  const l = localStorage.getItem("jenny-lang");
  return l === "en" || l === "fr" ? l : "fr";
}

if (!i18n.isInitialized) {
  void i18n.use(initReactI18next).init({
    resources: { fr: { translation: fr }, en: { translation: en } },
    lng: "fr",
    fallbackLng: "fr",
    interpolation: { escapeValue: false },
  });
}

export default i18n;

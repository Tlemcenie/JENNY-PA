import type { Transition, Variants } from "framer-motion";

// Courbes d'easing « premium » (proches de Linear / Stripe / Vercel)
export const easeOutExpo: [number, number, number, number] = [0.16, 1, 0.3, 1];
export const easeOutQuint: [number, number, number, number] = [0.22, 1, 0.36, 1];

// Springs réutilisables pour les micro-interactions
export const springSnappy: Transition = {
  type: "spring",
  stiffness: 400,
  damping: 32,
  mass: 0.8,
};

export const springSoft: Transition = {
  type: "spring",
  stiffness: 260,
  damping: 26,
};

// Apparition douce vers le haut (cartes, sections)
export const fadeInUp: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: easeOutExpo } },
};

// Transition de page (utilisée par template.tsx) — rapide et discrète
export const pageTransition: Variants = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.32, ease: easeOutExpo } },
};

// Conteneur orchestrant l'apparition séquentielle de ses enfants
export const staggerContainer: Variants = {
  hidden: {},
  show: {
    transition: { staggerChildren: 0.05, delayChildren: 0.04 },
  },
};

// Enfant d'un conteneur `staggerContainer`
export const staggerItem: Variants = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: easeOutExpo } },
};

// Apparition par mise à l'échelle (modales, pop-overs, toasts)
export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.96 },
  show: { opacity: 1, scale: 1, transition: { duration: 0.3, ease: easeOutExpo } },
};

// ── Listes / tableaux : apparition en cascade rapide et discrète ──
// Variante plus « serrée » que staggerContainer (pas de delayChildren) pour les
// longues listes : on veut un balayage fluide, pas une intro théâtrale.
export const listStagger: Variants = {
  hidden: {},
  show: {
    transition: { staggerChildren: 0.035, delayChildren: 0 },
  },
};

// Enfant d'un conteneur `listStagger` (lignes de tableau, items de liste).
export const listItem: Variants = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: easeOutExpo } },
};

// ── Transitions d'étapes / d'onglets (wizard, segments) ──
// Glissement horizontal léger + fondu. Utiliser avec AnimatePresence
// (mode="wait") et une `key` par étape/onglet.
export const slideInLeft: Variants = {
  hidden: { opacity: 0, x: -24 },
  show: { opacity: 1, x: 0, transition: { duration: 0.4, ease: easeOutExpo } },
};

export const slideInRight: Variants = {
  hidden: { opacity: 0, x: 24 },
  show: { opacity: 1, x: 0, transition: { duration: 0.4, ease: easeOutExpo } },
};

// ── Micro-interaction « pressable » (boutons, cartes cliquables) ──
// À étaler sur un composant motion : `<motion.button {...pressable} />`.
// Désactiver (ne pas étaler) si `useReducedMotion()` est vrai.
export const pressable = {
  whileHover: { y: -1 },
  whileTap: { scale: 0.97 },
  transition: springSnappy,
} as const;

"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Toaster, toast as sonnerToast } from "sonner";

type ToastType = "success" | "error" | "info" | "warning";

interface ToastContextValue {
  show: (message: string, type?: ToastType) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
  warning: (message: string) => void;
}

// API conservée (toast.success/error/info) mais adossée à sonner pour un rendu
// pro (empilement, swipe, couleurs riches, accessibilité). On ajoute `warning`
// sans rien retirer : les appels existants restent valides.
const api: ToastContextValue = {
  show: (m, type = "info") => {
    if (type === "success") sonnerToast.success(m);
    else if (type === "error") sonnerToast.error(m);
    else if (type === "warning") sonnerToast.warning(m);
    else sonnerToast(m);
  },
  success: (m) => sonnerToast.success(m),
  error: (m) => sonnerToast.error(m),
  info: (m) => sonnerToast(m),
  warning: (m) => sonnerToast.warning(m),
};

export function useToast(): ToastContextValue {
  return api;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    const read = () =>
      setTheme(document.documentElement.classList.contains("dark") ? "dark" : "light");
    read();
    const obs = new MutationObserver(read);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);

  return (
    <>
      {children}
      {/* Sonner pilote lui-même l'entrée (slide-in + fondu + écrasement via --y),
          la sortie et `prefers-reduced-motion`. On NE redéfinit PAS son transform :
          on l'habille seulement (ombre premium, rayon, anneau) + un poil plus de
          présence à l'entrée via l'easing « premium ». richColors fournit déjà les
          teintes sémantiques success / error / warning. */}
      <style>{`
        /* Easing premium (easeOutExpo) sur l'animation native de sonner. */
        [data-sonner-toast] {
          transition-timing-function: cubic-bezier(0.16, 1, 0.3, 1) !important;
        }
        [data-sonner-toast][data-styled='true'] {
          box-shadow: 0 8px 28px -6px rgba(15, 23, 42, 0.18),
            0 2px 8px -2px rgba(15, 23, 42, 0.1);
          border-radius: 0.75rem;
        }
        /* On respecte le réglage natif de sonner : pas d'easing custom si le
           visiteur demande moins de mouvement. */
        @media (prefers-reduced-motion: reduce) {
          [data-sonner-toast] {
            transition-timing-function: linear !important;
          }
        }
      `}</style>
      <Toaster
        theme={theme}
        position="bottom-right"
        richColors
        closeButton
        duration={4000}
        toastOptions={{
          style: { borderRadius: "0.75rem", fontSize: "0.875rem" },
        }}
      />
    </>
  );
}

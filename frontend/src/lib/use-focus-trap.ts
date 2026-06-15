"use client";

import { useEffect, type RefObject } from "react";

const SELECTOR =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * Piège le focus clavier à l'intérieur d'un conteneur (modale/tiroir) tant que
 * ``active`` est vrai : Tab/Shift+Tab bouclent, et le focus est restauré à la
 * fermeture sur l'élément précédemment actif. Améliore l'accessibilité.
 */
export function useFocusTrap(active: boolean, ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!active || !ref.current) return;
    const root = ref.current;
    const previouslyFocused = document.activeElement as HTMLElement | null;

    const focusables = () =>
      [...root.querySelectorAll<HTMLElement>(SELECTOR)].filter(
        (el) => !el.hasAttribute("disabled") && el.offsetParent !== null
      );

    // Focus le premier élément après un tick (le temps que la modale soit montée).
    const t = setTimeout(() => focusables()[0]?.focus(), 30);

    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const els = focusables();
      if (els.length === 0) return;
      const first = els[0];
      const last = els[els.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    root.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(t);
      root.removeEventListener("keydown", onKey);
      previouslyFocused?.focus?.();
    };
  }, [active, ref]);
}

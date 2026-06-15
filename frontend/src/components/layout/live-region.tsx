"use client";

import { useEffect, useState } from "react";

/**
 * Région ARIA live : annonce les mises à jour temps réel (nouveaux messages…)
 * aux lecteurs d'écran. Alimentée par un événement `jenny:announce`.
 */
export function LiveRegion() {
  const [msg, setMsg] = useState("");
  useEffect(() => {
    const h = (e: Event) => setMsg((e as CustomEvent<string>).detail || "");
    window.addEventListener("jenny:announce", h as EventListener);
    return () => window.removeEventListener("jenny:announce", h as EventListener);
  }, []);
  return (
    <div aria-live="polite" aria-atomic="true" className="sr-only">
      {msg}
    </div>
  );
}

"use client";

import { createContext, useContext, useEffect, useState } from "react";

// Horloge partagée : un seul setInterval pour toute l'app. Les composants qui
// affichent une heure relative se ré-affichent toutes les 30 s sans recharger.
const TickContext = createContext<number>(0);

export function TimeProvider({ children }: { children: React.ReactNode }) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);
  return <TickContext.Provider value={tick}>{children}</TickContext.Provider>;
}

/** Force un re-render toutes les 30 s (heure relative auto-rafraîchie). */
export function useTick(): number {
  return useContext(TickContext);
}

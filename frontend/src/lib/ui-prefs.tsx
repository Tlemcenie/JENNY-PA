"use client";

import { createContext, useContext, useEffect, useState } from "react";

export type Density = "comfortable" | "compact";

interface UiPrefs {
  density: Density;
  setDensity: (d: Density) => void;
}

const Ctx = createContext<UiPrefs>({ density: "comfortable", setDensity: () => {} });

export function useUiPrefs(): UiPrefs {
  return useContext(Ctx);
}

export function UiPrefsProvider({ children }: { children: React.ReactNode }) {
  const [density, setDensityState] = useState<Density>("comfortable");

  useEffect(() => {
    try {
      const d = localStorage.getItem("jenny-density");
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (d === "compact" || d === "comfortable") setDensityState(d);
    } catch {
      // ignore
    }
  }, []);

  const setDensity = (d: Density) => {
    setDensityState(d);
    try {
      localStorage.setItem("jenny-density", d);
    } catch {
      // ignore
    }
  };

  // Applique la densité au document : la racine en rem est mise à l'échelle, ce
  // qui compacte proportionnellement toute l'interface (Tailwind utilise rem).
  useEffect(() => {
    document.documentElement.dataset.density = density;
  }, [density]);

  return <Ctx.Provider value={{ density, setDensity }}>{children}</Ctx.Provider>;
}

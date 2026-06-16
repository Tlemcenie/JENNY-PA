"use client";

import { useEffect, useState } from "react";
import { Moon } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { applyTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

/**
 * Ligne « Mode sombre » prête à poser (sidebar, paramètres…). Utilise le
 * Switch premium et pilote VRAIMENT le thème (`applyTheme`). Un MutationObserver
 * sur la classe de <html> garde l'état synchrone avec le sélecteur d'apparence
 * de la topbar — bascule ici ou là-bas, les deux suivent.
 */
export function ThemeSwitch({ className }: { className?: string }) {
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    const root = document.documentElement;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setIsDark(root.classList.contains("dark"));
    const obs = new MutationObserver(() => setIsDark(root.classList.contains("dark")));
    obs.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);

  return (
    <div
      className={cn(
        "flex items-center gap-3 px-3 py-2.5 rounded-2xl text-white/55 transition-colors",
        className
      )}
    >
      <Moon className="w-[18px] h-[18px] flex-shrink-0" />
      <span className="text-[0.8125rem] font-medium">Mode sombre</span>
      <Switch
        checked={isDark}
        onCheckedChange={(v) => applyTheme(v ? "dark" : "light")}
        size="sm"
        aria-label="Basculer le mode sombre"
        className="ml-auto"
      />
    </div>
  );
}

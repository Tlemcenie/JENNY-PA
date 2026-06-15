"use client";

import { Rows3, Rows2 } from "lucide-react";
import { useUiPrefs } from "@/lib/ui-prefs";
import { cn } from "@/lib/utils";

export function DensityToggle({ className }: { className?: string }) {
  const { density, setDensity } = useUiPrefs();
  const compact = density === "compact";
  return (
    <button
      onClick={() => setDensity(compact ? "comfortable" : "compact")}
      aria-label={compact ? "Affichage confortable" : "Affichage compact"}
      title={compact ? "Affichage confortable" : "Affichage compact"}
      className={cn(
        "w-9 h-9 rounded-xl flex items-center justify-center text-jenny-text-secondary hover:text-jenny-coral hover:bg-jenny-coral/10 transition-colors",
        className
      )}
    >
      {compact ? <Rows2 className="w-[18px] h-[18px]" /> : <Rows3 className="w-[18px] h-[18px]" />}
    </button>
  );
}

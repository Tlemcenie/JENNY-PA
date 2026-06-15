"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Sun, Moon, Monitor, Check } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  ACCENTS,
  applyTheme,
  getStoredAccent,
  getStoredTheme,
  setStoredAccent,
  type ThemeMode,
} from "@/lib/theme";

const MODES: { mode: ThemeMode; label: string; icon: typeof Sun }[] = [
  { mode: "light", label: "Clair", icon: Sun },
  { mode: "dark", label: "Sombre", icon: Moon },
  { mode: "system", label: "Système", icon: Monitor },
];

export function ThemeToggle({ className }: { className?: string }) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<ThemeMode>("system");
  const [accent, setAccent] = useState(ACCENTS[0].value);
  const ref = useRef<HTMLDivElement>(null);

  // Lecture de l'état persistant après montage (pas d'accès DOM au SSR).
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMode(getStoredTheme());
    setAccent(getStoredAccent());
  }, []);

  // Suit les changements système quand le mode est « système ».
  useEffect(() => {
    if (mode !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => applyTheme("system");
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [mode]);

  // Fermeture au clic extérieur.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const pickMode = (m: ThemeMode) => {
    setMode(m);
    applyTheme(m);
  };

  const pickAccent = (hex: string) => {
    setAccent(hex);
    setStoredAccent(hex);
  };

  const ActiveIcon =
    mode === "light" ? Sun : mode === "dark" ? Moon : Monitor;

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label="Apparence"
        title="Apparence"
        className={cn(
          "relative w-9 h-9 rounded-xl flex items-center justify-center",
          "text-jenny-text-secondary hover:text-jenny-coral hover:bg-jenny-coral/10 transition-colors",
          className
        )}
      >
        <ActiveIcon className="w-[18px] h-[18px]" />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.14 }}
            className="absolute right-0 mt-2 w-52 rounded-2xl bg-jenny-surface border border-jenny-divider shadow-xl z-50 p-2"
          >
            <p className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-jenny-text-secondary">
              Thème
            </p>
            {MODES.map(({ mode: m, label, icon: Icon }) => (
              <button
                key={m}
                onClick={() => pickMode(m)}
                className={cn(
                  "w-full flex items-center gap-2.5 px-2 py-1.5 rounded-lg text-sm transition-colors",
                  m === mode
                    ? "bg-jenny-coral/10 text-jenny-coral"
                    : "text-jenny-text hover:bg-jenny-bg"
                )}
              >
                <Icon className="w-4 h-4" />
                {label}
                {m === mode && <Check className="w-3.5 h-3.5 ml-auto" />}
              </button>
            ))}

            <p className="px-2 pt-2.5 pb-1 text-[11px] font-semibold uppercase tracking-wide text-jenny-text-secondary">
              Couleur d&apos;accent
            </p>
            <div className="flex flex-wrap gap-1.5 px-2 pb-1">
              {ACCENTS.map((a) => (
                <button
                  key={a.value}
                  onClick={() => pickAccent(a.value)}
                  aria-label={a.name}
                  title={a.name}
                  className={cn(
                    "w-6 h-6 rounded-full flex items-center justify-center transition-transform hover:scale-110",
                    accent === a.value && "ring-2 ring-offset-2 ring-offset-jenny-surface ring-jenny-text/30"
                  )}
                  style={{ backgroundColor: a.value }}
                >
                  {accent === a.value && <Check className="w-3.5 h-3.5 text-white" />}
                </button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

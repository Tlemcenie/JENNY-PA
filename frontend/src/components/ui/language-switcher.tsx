"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { LANGS, type LangCode } from "@/lib/i18n";

export function LanguageSwitcher({ className }: { className?: string }) {
  const { i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  // Dérivé directement d'i18n (re-render via useTranslation) — pas d'état miroir.
  const lang = ((i18n.language as LangCode) || "fr") as LangCode;
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const pick = (code: LangCode) => {
    void i18n.changeLanguage(code);
    try {
      localStorage.setItem("jenny-lang", code);
    } catch {
      // ignore
    }
    setOpen(false);
  };

  const active = LANGS.find((l) => l.code === lang) || LANGS[0];

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label="Langue / Language"
        title={active.label}
        className={cn(
          "w-9 h-9 rounded-xl flex items-center justify-center text-base",
          "hover:bg-jenny-coral/10 transition-colors",
          className
        )}
      >
        <span aria-hidden>{active.flag}</span>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.14 }}
            className="absolute right-0 mt-2 w-40 rounded-2xl bg-jenny-surface border border-jenny-divider shadow-xl z-50 p-1.5"
          >
            {LANGS.map((l) => (
              <button
                key={l.code}
                onClick={() => pick(l.code)}
                className={cn(
                  "w-full flex items-center gap-2.5 px-2 py-1.5 rounded-lg text-sm transition-colors",
                  l.code === lang
                    ? "bg-jenny-coral/10 text-jenny-coral"
                    : "text-jenny-text hover:bg-jenny-bg"
                )}
              >
                <span aria-hidden>{l.flag}</span>
                {l.label}
                {l.code === lang && <Check className="w-3.5 h-3.5 ml-auto" />}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

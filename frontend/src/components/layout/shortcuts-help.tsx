"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X, Keyboard } from "lucide-react";
import { useFocusTrap } from "@/lib/use-focus-trap";
import { easeOutExpo } from "@/lib/motion";

const SHORTCUTS: Array<{ keys: string[]; label: string }> = [
  { keys: ["⌘", "K"], label: "Recherche globale" },
  { keys: ["?"], label: "Afficher cette aide" },
  { keys: ["j"], label: "Conversation suivante" },
  { keys: ["k"], label: "Conversation précédente" },
  { keys: ["r"], label: "Répondre (focus composer)" },
  { keys: ["Échap"], label: "Fermer le détail / la fenêtre" },
  { keys: ["Entrée"], label: "Envoyer la réponse" },
  { keys: ["⇧", "Entrée"], label: "Nouvelle ligne dans la réponse" },
];

export function ShortcutsHelp() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(open, ref);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const typing =
        el?.tagName === "INPUT" || el?.tagName === "TEXTAREA" || el?.isContentEditable;
      if (e.key === "?" && !typing) {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="fixed inset-0 z-[75] bg-black/40 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={() => setOpen(false)}
          />
          <motion.div
            ref={ref}
            role="dialog"
            aria-modal="true"
            aria-label="Raccourcis clavier"
            className="fixed left-1/2 top-1/2 z-[76] w-[min(92vw,440px)] -translate-x-1/2 -translate-y-1/2 bg-jenny-surface border border-jenny-divider rounded-2xl shadow-2xl overflow-hidden"
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 8 }}
            transition={{ duration: 0.2, ease: easeOutExpo }}
          >
            <div className="flex items-center justify-between p-4 border-b border-jenny-divider">
              <h2 className="flex items-center gap-2 font-semibold text-jenny-text">
                <Keyboard className="w-4 h-4 text-jenny-coral" />
                Raccourcis clavier
              </h2>
              <button
                onClick={() => setOpen(false)}
                aria-label="Fermer"
                className="p-1.5 rounded-lg text-jenny-text-secondary hover:text-jenny-text hover:bg-jenny-divider/40 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-4 space-y-2">
              {SHORTCUTS.map((s) => (
                <div key={s.label} className="flex items-center justify-between gap-3">
                  <span className="text-sm text-jenny-text-secondary">{s.label}</span>
                  <span className="flex items-center gap-1">
                    {s.keys.map((k) => (
                      <kbd
                        key={k}
                        className="min-w-6 text-center text-[11px] font-medium text-jenny-text bg-jenny-bg border border-jenny-divider rounded px-1.5 py-0.5"
                      >
                        {k}
                      </kbd>
                    ))}
                  </span>
                </div>
              ))}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

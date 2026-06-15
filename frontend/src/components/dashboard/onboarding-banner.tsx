"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Sparkles, X, Command, Keyboard, Radio } from "lucide-react";

const TIPS = [
  { icon: Command, label: "⌘K", text: "rechercher partout" },
  { icon: Keyboard, label: "?", text: "voir les raccourcis" },
  { icon: Radio, label: "Canaux", text: "connecter WhatsApp & co." },
];

export function OnboardingBanner() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setShow(localStorage.getItem("jenny-onboarded") !== "1");
    } catch {
      // ignore
    }
  }, []);

  const dismiss = () => {
    setShow(false);
    try {
      localStorage.setItem("jenny-onboarded", "1");
    } catch {
      // ignore
    }
  };

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          initial={{ opacity: 0, y: -8, height: 0 }}
          animate={{ opacity: 1, y: 0, height: "auto" }}
          exit={{ opacity: 0, y: -8, height: 0 }}
          className="relative overflow-hidden rounded-2xl bg-brand-gradient text-white p-4 pr-10"
        >
          <div className="flex items-center gap-3 flex-wrap">
            <span className="flex items-center gap-1.5 font-semibold">
              <Sparkles className="w-4 h-4" />
              Bienvenue sur Jenny !
            </span>
            <span className="hidden sm:flex items-center gap-3 text-white/90 text-sm">
              {TIPS.map((t) => (
                <span key={t.label} className="flex items-center gap-1.5">
                  <kbd className="bg-white/20 rounded px-1.5 py-0.5 text-[11px] font-medium">
                    {t.label}
                  </kbd>
                  {t.text}
                </span>
              ))}
            </span>
          </div>
          <button
            onClick={dismiss}
            aria-label="Masquer"
            className="absolute top-3 right-3 text-white/70 hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

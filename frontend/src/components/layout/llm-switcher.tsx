"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Cpu, Check, ChevronDown } from "lucide-react";
import { getLlmSettings, switchLlm, type LlmState, ApiError } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

// Bascule du « cerveau » de Jenny côté client : Ollama (local) / Groq (hébergé) /
// NanoGPT (maison). Compact dans la topbar ; grise les moteurs non prêts.
const SHORT: Record<string, string> = {
  ollama: "Ollama",
  groq: "Groq 70B",
  nanogpt: "NanoGPT",
};

export function LlmSwitcher() {
  const toast = useToast();
  const [state, setState] = useState<LlmState | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      setState(await getLlmSettings());
    } catch {
      /* silencieux : le bouton reste masqué si l'API ne répond pas */
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!state) return null;

  const select = async (key: string) => {
    if (busy || key === state.active) {
      setOpen(false);
      return;
    }
    setBusy(true);
    try {
      const next = await switchLlm(key);
      setState(next);
      setOpen(false);
      const label = next.options.find((o) => o.current)?.label ?? key;
      toast.success(`Jenny tourne maintenant sur ${label}.`);
    } catch (err) {
      const detail =
        err instanceof ApiError ? (err.data as { detail?: string })?.detail : null;
      toast.error(detail || "Impossible de changer de moteur.");
      void load();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        title="Moteur d'IA de Jenny"
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex items-center gap-1.5 h-8 pl-2 pr-1.5 rounded-lg border border-jenny-divider text-jenny-text-secondary hover:border-jenny-coral/40 hover:text-jenny-coral transition-colors"
      >
        <Cpu className="w-3.5 h-3.5 text-jenny-coral" />
        <span className="hidden sm:inline text-[12px] font-medium">
          {SHORT[state.active] ?? state.active}
        </span>
        <ChevronDown className={cn("w-3.5 h-3.5 transition-transform", open && "rotate-180")} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            role="menu"
            initial={{ opacity: 0, y: -6, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.97 }}
            transition={{ duration: 0.15 }}
            className="absolute right-0 mt-2 w-72 rounded-xl bg-jenny-surface border border-jenny-divider shadow-xl overflow-hidden z-50"
          >
            <div className="px-3.5 py-2.5 border-b border-jenny-divider">
              <p className="text-[0.8125rem] font-semibold text-jenny-text">Moteur de Jenny</p>
              <p className="text-[0.6875rem] text-jenny-text-secondary">
                Le « cerveau » qui répond aux clients.
              </p>
            </div>
            <div className="p-1.5">
              {state.options.map((o) => {
                const disabled = !o.available && !o.current;
                return (
                  <button
                    key={o.key}
                    role="menuitemradio"
                    aria-checked={o.current}
                    disabled={disabled || busy}
                    onClick={() => void select(o.key)}
                    className={cn(
                      "w-full text-left flex items-start gap-2.5 px-2.5 py-2 rounded-lg transition-colors",
                      o.current
                        ? "bg-jenny-coral/[0.08]"
                        : disabled
                          ? "opacity-45 cursor-not-allowed"
                          : "hover:bg-jenny-divider/40"
                    )}
                  >
                    <span className="mt-0.5 w-4 shrink-0">
                      {o.current && <Check className="w-4 h-4 text-jenny-coral" />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="text-[0.8125rem] font-medium text-jenny-text">
                          {o.label}
                        </span>
                        {!o.available && (
                          <span className="text-[0.625rem] font-mono uppercase tracking-wide text-jenny-text-secondary/70 border border-jenny-divider rounded px-1 py-px">
                            indispo
                          </span>
                        )}
                      </span>
                      <span className="block text-[0.6875rem] text-jenny-text-secondary leading-snug mt-0.5">
                        {o.hint}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

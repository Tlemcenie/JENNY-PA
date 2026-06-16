"use client";

import { createContext, useCallback, useContext, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle } from "lucide-react";
import { useFocusTrap } from "@/lib/use-focus-trap";
import { easeOutExpo } from "@/lib/motion";
import { PressableButton } from "@/components/ui/pressable-button";

interface ConfirmOptions {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}

type ConfirmFn = (opts: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn>(async () => false);

export function useConfirm(): ConfirmFn {
  return useContext(ConfirmContext);
}

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [opts, setOpts] = useState<ConfirmOptions | null>(null);
  const resolver = useRef<((v: boolean) => void) | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(opts !== null, dialogRef);

  const confirm = useCallback<ConfirmFn>((options) => {
    setOpts(options);
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  const close = (value: boolean) => {
    resolver.current?.(value);
    resolver.current = null;
    setOpts(null);
  };

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <AnimatePresence>
        {opts && (
          <>
            <motion.div
              className="fixed inset-0 z-[80] bg-black/40 backdrop-blur-[2px]"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              onClick={() => close(false)}
            />
            <motion.div
              ref={dialogRef}
              role="alertdialog"
              aria-modal="true"
              aria-label={opts.title}
              className="fixed left-1/2 top-1/2 z-[81] w-[min(92vw,420px)] -translate-x-1/2 -translate-y-1/2 bg-jenny-surface border border-jenny-divider rounded-2xl shadow-2xl p-5"
              initial={{ opacity: 0, scale: 0.96, y: 8 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96, y: 8 }}
              transition={{ duration: 0.2, ease: easeOutExpo }}
              onKeyDown={(e) => {
                if (e.key === "Escape") close(false);
                if (e.key === "Enter") close(true);
              }}
            >
              <div className="flex items-start gap-3">
                {opts.danger && (
                  <span className="w-9 h-9 rounded-xl bg-jenny-error/10 text-jenny-error flex items-center justify-center shrink-0">
                    <AlertTriangle className="w-5 h-5" />
                  </span>
                )}
                <div className="min-w-0">
                  <h2 className="font-semibold text-jenny-text">{opts.title}</h2>
                  {opts.message && (
                    <p className="text-sm text-jenny-text-secondary mt-1">{opts.message}</p>
                  )}
                </div>
              </div>
              <div className="flex justify-end gap-2 mt-5">
                <PressableButton variant="ghost" size="sm" onClick={() => close(false)}>
                  {opts.cancelLabel || "Annuler"}
                </PressableButton>
                <PressableButton
                  variant={opts.danger ? "danger" : "primary"}
                  size="sm"
                  onClick={() => close(true)}
                >
                  {opts.confirmLabel || "Confirmer"}
                </PressableButton>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </ConfirmContext.Provider>
  );
}

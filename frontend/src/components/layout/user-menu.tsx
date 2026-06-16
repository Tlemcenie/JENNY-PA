"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { LogOut, Settings, ChevronDown } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";

// Menu utilisateur (topbar) : avatar + nom, et surtout un bouton « Se déconnecter »
// bien visible (en plus de celui de la sidebar).
export function UserMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

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

  const initial = (user?.full_name || user?.email || "?").trim().charAt(0).toUpperCase();

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Menu du compte"
        className="flex items-center gap-1.5 h-8 pl-1 pr-1.5 rounded-lg border border-jenny-divider hover:border-jenny-coral/40 transition-colors"
      >
        <span className="w-6 h-6 rounded-full bg-brand-gradient text-white text-[11px] font-bold flex items-center justify-center">
          {initial}
        </span>
        <ChevronDown
          className={cn(
            "w-3.5 h-3.5 text-jenny-text-secondary transition-transform",
            open && "rotate-180"
          )}
        />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            role="menu"
            initial={{ opacity: 0, y: -6, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.97 }}
            transition={{ duration: 0.15 }}
            className="absolute right-0 mt-2 w-60 rounded-xl bg-jenny-surface border border-jenny-divider shadow-xl overflow-hidden z-50"
          >
            <div className="px-3.5 py-3 border-b border-jenny-divider">
              <p className="text-[0.8125rem] font-semibold text-jenny-text truncate">
                {user?.full_name || "Mon compte"}
              </p>
              {user?.email && (
                <p className="text-[0.75rem] text-jenny-text-secondary truncate">{user.email}</p>
              )}
            </div>
            <div className="p-1.5">
              <Link
                href="/profile"
                onClick={() => setOpen(false)}
                role="menuitem"
                className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-[0.8125rem] text-jenny-text hover:bg-jenny-divider/40 transition-colors"
              >
                <Settings className="w-4 h-4 text-jenny-text-secondary" />
                Paramètres du compte
              </Link>
              <button
                onClick={() => {
                  setOpen(false);
                  logout();
                }}
                role="menuitem"
                className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-[0.8125rem] font-medium text-jenny-error hover:bg-jenny-error/[0.08] transition-colors"
              >
                <LogOut className="w-4 h-4" />
                Se déconnecter
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

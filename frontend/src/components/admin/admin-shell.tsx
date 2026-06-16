"use client";

import type { ComponentType, ReactNode } from "react";
import Image from "next/image";
import { motion } from "framer-motion";
import { ArrowLeft, LogOut, Shield } from "lucide-react";

// ── Coque visuelle de la console admin (thème nuit autonome, hors (dashboard)).
// Regroupe : fond plein écran, barre supérieure (identité + email + quitter +
// déconnexion), écran de refus, loader plein écran et la barre d'onglets animée.
// Aucune logique de gating ici : la page décide quoi afficher.

export const PAGE_BG =
  "radial-gradient(ellipse at 75% -5%, rgba(255,127,106,0.16) 0%, transparent 52%), radial-gradient(ellipse at 0% 90%, rgba(114,132,168,0.12) 0%, transparent 50%), var(--color-jenny-night)";

export interface AdminTab<T extends string> {
  id: T;
  label: string;
  icon: ComponentType<{ className?: string }>;
}

// Fond + typographie communs.
export function AdminScreen({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={className ?? "min-h-screen w-full flex flex-col text-[#F4F1ED]"}
      style={{ background: PAGE_BG, fontFamily: "var(--font-sans)" }}
    >
      {children}
    </div>
  );
}

export function AdminTopbar({
  email,
  onExit,
  onLogout,
}: {
  email: string | undefined;
  onExit: () => void;
  onLogout: () => void;
}) {
  return (
    <header
      className="sticky top-0 z-20 flex items-center gap-4 px-5 md:px-10 py-4"
      style={{
        backdropFilter: "blur(12px)",
        background: "rgba(14,11,20,0.72)",
        borderBottom: "1px solid rgba(255,255,255,0.07)",
      }}
    >
      <div className="flex items-center gap-2.5 min-w-0">
        <span className="w-9 h-9 rounded-[10px] overflow-hidden bg-jenny-coral block shrink-0">
          <Image src="/jenny.png" alt="Jenny" width={36} height={36} className="object-cover w-full h-full" />
        </span>
        <div className="min-w-0">
          <div className="text-[15px] font-bold tracking-[-0.02em] leading-tight">
            Jenny <span className="text-[#F4F1ED]/40">·</span> Admin
          </div>
          <div className="font-mono text-[10.5px] tracking-[0.16em] uppercase text-jenny-coral/80 leading-tight">
            Console plateforme
          </div>
        </div>
      </div>

      <div className="ml-auto flex items-center gap-2 md:gap-3">
        <span
          className="hidden sm:block font-mono text-[12px] text-[#F4F1ED]/55 truncate max-w-[220px]"
          title={email}
        >
          {email}
        </span>
        <button
          type="button"
          onClick={onExit}
          className="h-9 px-3.5 rounded-lg text-[13px] font-semibold inline-flex items-center gap-1.5 text-[#F4F1ED]/85 transition-colors hover:bg-white/10"
          style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)" }}
        >
          <ArrowLeft className="w-4 h-4" />
          <span className="hidden md:inline">Quitter l&apos;admin</span>
        </button>
        <button
          type="button"
          onClick={onLogout}
          className="h-9 px-3.5 rounded-lg text-[13px] font-semibold inline-flex items-center gap-1.5 text-[#F4F1ED]/70 hover:text-[#F4F1ED] transition-colors hover:bg-white/10"
        >
          <LogOut className="w-4 h-4" />
          <span className="hidden md:inline">Déconnexion</span>
        </button>
      </div>
    </header>
  );
}

// Barre d'onglets (pill animée partagée via layoutId).
export function AdminTabBar<T extends string>({
  tabs,
  active,
  onSelect,
}: {
  tabs: AdminTab<T>[];
  active: T;
  onSelect: (id: T) => void;
}) {
  return (
    <div
      className="inline-flex flex-wrap gap-1 p-1 rounded-xl mb-8"
      style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
    >
      {tabs.map((t) => {
        const Icon = t.icon;
        const isActive = active === t.id;
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => onSelect(t.id)}
            aria-pressed={isActive}
            className="relative h-9 px-3.5 rounded-lg text-[13px] font-semibold inline-flex items-center gap-2 transition-colors"
            style={{ color: isActive ? "#FFFFFF" : "rgba(244,241,237,0.6)" }}
          >
            {isActive && (
              <motion.span
                layoutId="admin-tab-bg"
                className="absolute inset-0 rounded-lg bg-jenny-coral"
                style={{ boxShadow: "0 4px 14px rgba(255,127,106,0.25)" }}
                transition={{ type: "spring", stiffness: 380, damping: 32 }}
              />
            )}
            <Icon className="w-4 h-4 relative z-10" />
            <span className="relative z-10">{t.label}</span>
          </button>
        );
      })}
    </div>
  );
}

// Écran « accès refusé » (compte authentifié mais non super-admin).
export function AccessDenied({ onBack }: { onBack: () => void }) {
  return (
    <AdminScreen className="min-h-screen w-full flex items-center justify-center px-6 text-[#F4F1ED]">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="max-w-[440px] w-full text-center rounded-[22px] p-9 md:p-11"
        style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
      >
        <span
          className="w-14 h-14 rounded-2xl mx-auto mb-6 flex items-center justify-center text-jenny-coral"
          style={{ background: "rgba(255,127,106,0.12)" }}
        >
          <Shield className="w-7 h-7" />
        </span>
        <div className="font-mono text-[11px] tracking-[0.28em] uppercase text-jenny-coral mb-3">
          — accès restreint —
        </div>
        <h1 className="font-display text-[34px] md:text-[40px] leading-[1.05] tracking-[-0.02em] mb-3.5">
          Accès réservé aux <span className="italic text-jenny-coral">administrateurs.</span>
        </h1>
        <p className="text-[14.5px] leading-[1.55] text-[#F4F1ED]/60 mb-8">
          Cette console est réservée aux administrateurs de la plateforme. Votre compte n&apos;a pas les
          droits nécessaires.
        </p>
        <button
          type="button"
          onClick={onBack}
          className="h-11 px-5 rounded-xl text-[14px] font-semibold inline-flex items-center gap-2 bg-jenny-coral text-white hover:bg-jenny-coral-dark transition-colors"
          style={{ boxShadow: "0 4px 14px rgba(255,127,106,0.25)" }}
        >
          <ArrowLeft className="w-4 h-4" />
          Retour à l&apos;application
        </button>
      </motion.div>
    </AdminScreen>
  );
}

// Loader plein écran (variante nuit, cohérent avec la DA admin).
export function AdminFullScreenLoader({ label }: { label: string }) {
  return (
    <AdminScreen className="min-h-screen w-full flex items-center justify-center">
      <div className="flex flex-col items-center gap-5">
        <div className="relative w-14 h-14">
          <motion.span
            className="absolute inset-0 rounded-2xl border-2 border-jenny-coral/25 border-t-jenny-coral"
            animate={{ rotate: 360 }}
            transition={{ duration: 0.9, ease: "linear", repeat: Infinity }}
          />
          <motion.div
            className="absolute inset-[5px] rounded-xl bg-jenny-coral flex items-center justify-center"
            animate={{ scale: [1, 0.9, 1] }}
            transition={{ duration: 1.4, ease: "easeInOut", repeat: Infinity }}
          >
            <span className="text-white font-bold text-lg">J</span>
          </motion.div>
        </div>
        <p className="text-[#F4F1ED]/55 text-sm">{label}</p>
      </div>
    </AdminScreen>
  );
}

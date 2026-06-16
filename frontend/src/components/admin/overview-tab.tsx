"use client";

import type { ComponentType } from "react";
import { motion } from "framer-motion";
import { Building2, MessageSquare, Users } from "lucide-react";
import { AnimatedNumber } from "@/components/ui/animated-number";
import { SkeletonStat } from "@/components/ui/skeleton";
import { staggerContainer, staggerItem } from "@/lib/motion";
import type { AdminOverview } from "@/lib/api";
import { formatNumber } from "./admin-shared";
import { SystemHealthCard } from "./system-health-card";

// ── Onglet « Vue d'ensemble » : 5 compteurs (AnimatedNumber) + carte santé. ──
// Données réelles via getAdminOverview() (passées en props par la page) et
// /ready (chargé par SystemHealthCard). Apparition en cascade (staggerItem).

interface OverviewCard {
  key: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  value: number | undefined;
}

export function OverviewTab({
  loading,
  overview,
}: {
  loading: boolean;
  overview: AdminOverview | null;
}) {
  const cards: OverviewCard[] = [
    { key: "businesses", label: "Entreprises", icon: Building2, value: overview?.businesses },
    { key: "users", label: "Comptes", icon: Users, value: overview?.users },
    { key: "conversations", label: "Conversations", icon: MessageSquare, value: overview?.conversations },
    { key: "messages", label: "Messages", icon: MessageSquare, value: overview?.messages },
    { key: "customers", label: "Clients", icon: Users, value: overview?.customers },
  ];

  return (
    <div className="flex flex-col gap-6">
      {loading ? (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="rounded-2xl p-5"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.06)" }}
            >
              <SkeletonStat />
            </div>
          ))}
        </div>
      ) : (
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="grid grid-cols-2 lg:grid-cols-5 gap-4"
        >
          {cards.map((c) => {
            const Icon = c.icon;
            return (
              <motion.div
                key={c.key}
                variants={staggerItem}
                className="rounded-2xl p-5"
                style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
              >
                <span
                  className="w-10 h-10 rounded-[11px] flex items-center justify-center mb-4 text-jenny-coral"
                  style={{ background: "rgba(255,127,106,0.12)" }}
                >
                  <Icon className="w-[18px] h-[18px]" />
                </span>
                <div className="font-display text-[40px] leading-none tracking-[-0.02em] mb-1.5">
                  <AnimatedNumber value={c.value ?? 0} format={formatNumber} />
                </div>
                <div className="font-mono text-[10.5px] tracking-[0.16em] uppercase text-[#F4F1ED]/50">
                  {c.label}
                </div>
              </motion.div>
            );
          })}
        </motion.div>
      )}

      {/* Santé plateforme (réel, /ready, auto-refresh 30 s). */}
      <SystemHealthCard />
    </div>
  );
}

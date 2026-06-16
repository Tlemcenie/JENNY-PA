"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Download, Power } from "lucide-react";
import { PressableButton } from "@/components/ui/pressable-button";
import { SkeletonRow } from "@/components/ui/skeleton";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { listItem, listStagger } from "@/lib/motion";
import type { AdminBusiness } from "@/lib/api";
import {
  downloadCsv,
  EmptyRow,
  formatDate,
  formatNumber,
  MetaPill,
  SectionShell,
  StatusBadge,
  ToolbarRow,
  type SortOption,
} from "./admin-shared";

// ── Onglet « Entreprises » : lignes animées, recherche + tri client-side,
// export CSV généré en JS, suspendre / réactiver (confirmation danger réelle).
// Données réelles : listAdminBusinesses + setBusinessActive (gérées par la page).

const SORT_OPTIONS: SortOption[] = [
  { value: "created_desc", label: "Plus récentes" },
  { value: "created_asc", label: "Plus anciennes" },
  { value: "name_asc", label: "Nom (A→Z)" },
  { value: "conversations_desc", label: "Conversations ↓" },
];

function sortBusinesses(list: AdminBusiness[], sort: string): AdminBusiness[] {
  const copy = [...list];
  switch (sort) {
    case "created_asc":
      return copy.sort((a, b) => +new Date(a.created_at) - +new Date(b.created_at));
    case "name_asc":
      return copy.sort((a, b) => a.name.localeCompare(b.name, "fr"));
    case "conversations_desc":
      return copy.sort((a, b) => b.conversations - a.conversations);
    case "created_desc":
    default:
      return copy.sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at));
  }
}

export function BusinessesTab({
  loading,
  businesses,
  pendingId,
  onToggle,
}: {
  loading: boolean;
  businesses: AdminBusiness[];
  pendingId: string | null;
  onToggle: (biz: AdminBusiness) => void;
}) {
  const confirm = useConfirm();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("created_desc");

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const base = q
      ? businesses.filter(
          (b) =>
            b.name.toLowerCase().includes(q) ||
            b.slug.toLowerCase().includes(q) ||
            (b.email ?? "").toLowerCase().includes(q)
        )
      : businesses;
    return sortBusinesses(base, sort);
  }, [businesses, search, sort]);

  async function handleToggle(biz: AdminBusiness) {
    const next = !biz.is_active;
    const ok = await confirm({
      title: next ? `Réactiver « ${biz.name} » ?` : `Suspendre « ${biz.name} » ?`,
      message: next
        ? "L'entreprise pourra de nouveau accéder à la plateforme."
        : "L'entreprise et ses membres perdront l'accès jusqu'à réactivation.",
      confirmLabel: next ? "Réactiver" : "Suspendre",
      danger: !next,
    });
    if (ok) onToggle(biz);
  }

  function exportCsv() {
    const rows = filtered.map((b) => [
      b.name,
      b.slug,
      b.email ?? "",
      b.is_active ? "active" : "suspendue",
      b.members,
      b.conversations,
      formatDate(b.created_at),
    ]);
    downloadCsv(
      "jenny-entreprises.csv",
      ["Nom", "Slug", "Email", "Statut", "Membres", "Conversations", "Créée le"],
      rows
    );
  }

  return (
    <SectionShell
      title="Entreprises"
      count={loading ? null : filtered.length}
      action={
        !loading && businesses.length > 0 ? (
          <PressableButton variant="secondary" size="sm" onClick={exportCsv} disabled={filtered.length === 0}>
            <Download className="w-4 h-4" />
            Exporter CSV
          </PressableButton>
        ) : undefined
      }
    >
      {!loading && businesses.length > 0 && (
        <ToolbarRow
          search={search}
          onSearch={setSearch}
          placeholder="Rechercher (nom, slug, email)…"
          sort={sort}
          sortOptions={SORT_OPTIONS}
          onSort={setSort}
        />
      )}

      {loading ? (
        <div className="px-5 py-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonRow key={i} cells={4} />
          ))}
        </div>
      ) : businesses.length === 0 ? (
        <EmptyRow label="Aucune entreprise pour le moment." />
      ) : filtered.length === 0 ? (
        <EmptyRow label="Aucune entreprise ne correspond à la recherche." />
      ) : (
        <motion.ul
          variants={listStagger}
          initial="hidden"
          animate="show"
          className="divide-y"
          style={{ borderColor: "rgba(255,255,255,0.06)" }}
        >
          {filtered.map((b) => {
            const busy = pendingId === b.id;
            return (
              <motion.li
                key={b.id}
                variants={listItem}
                className="px-5 py-4 flex flex-col lg:flex-row lg:items-center gap-3 lg:gap-4 hover:bg-white/[0.02] transition-colors"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <span className="text-[14.5px] font-semibold text-[#F4F1ED] truncate">{b.name}</span>
                    <StatusBadge active={b.is_active} />
                  </div>
                  <div className="flex items-center gap-x-4 gap-y-1 flex-wrap mt-1.5">
                    <span className="font-mono text-[11.5px] text-jenny-coral/80">/{b.slug}</span>
                    {b.email && <span className="text-[12.5px] text-[#F4F1ED]/55 truncate">{b.email}</span>}
                  </div>
                </div>

                <div className="flex items-center gap-4 lg:gap-5 flex-wrap">
                  <MetaPill label="MEMBRES" value={formatNumber(b.members)} />
                  <MetaPill label="CONV." value={formatNumber(b.conversations)} />
                  <MetaPill label="CRÉÉE" value={formatDate(b.created_at)} />
                </div>

                <PressableButton
                  variant={b.is_active ? "danger" : "primary"}
                  size="sm"
                  isLoading={busy}
                  onClick={() => void handleToggle(b)}
                  className="shrink-0"
                >
                  {!busy && <Power className="w-4 h-4" />}
                  {b.is_active ? "Suspendre" : "Réactiver"}
                </PressableButton>
              </motion.li>
            );
          })}
        </motion.ul>
      )}
    </SectionShell>
  );
}

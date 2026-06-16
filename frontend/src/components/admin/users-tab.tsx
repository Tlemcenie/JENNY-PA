"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Check, Download, Shield, ShieldCheck } from "lucide-react";
import { PressableButton } from "@/components/ui/pressable-button";
import { SkeletonRow } from "@/components/ui/skeleton";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { listItem, listStagger } from "@/lib/motion";
import type { AdminUserItem } from "@/lib/api";
import {
  downloadCsv,
  EmptyRow,
  formatDate,
  formatNumber,
  MetaPill,
  SectionShell,
  ToolbarRow,
  type SortOption,
} from "./admin-shared";

// ── Onglet « Comptes » : lignes animées, recherche + tri client-side, export
// CSV en JS, promouvoir / retirer admin (confirmation réelle). Le backend
// interdit de retirer ses propres droits → le 400 remonte via le toast de la page.
// Données réelles : listAdminUsers + setUserSuperuser (gérées par la page).

const SORT_OPTIONS: SortOption[] = [
  { value: "created_desc", label: "Plus récents" },
  { value: "created_asc", label: "Plus anciens" },
  { value: "name_asc", label: "Nom (A→Z)" },
  { value: "admin_first", label: "Admins d'abord" },
];

function nameOf(u: AdminUserItem): string {
  return u.full_name || u.email;
}

function sortUsers(list: AdminUserItem[], sort: string): AdminUserItem[] {
  const copy = [...list];
  switch (sort) {
    case "created_asc":
      return copy.sort((a, b) => +new Date(a.created_at) - +new Date(b.created_at));
    case "name_asc":
      return copy.sort((a, b) => nameOf(a).localeCompare(nameOf(b), "fr"));
    case "admin_first":
      return copy.sort((a, b) => Number(b.is_superuser) - Number(a.is_superuser));
    case "created_desc":
    default:
      return copy.sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at));
  }
}

function VerifiedBadge({ verified }: { verified: boolean }) {
  if (verified) {
    return (
      <span
        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-mono font-semibold tracking-[0.06em] shrink-0"
        style={{ background: "rgba(16,185,129,0.14)", color: "var(--color-jenny-success)" }}
      >
        <Check className="w-[11px] h-[11px]" />
        VÉRIFIÉ
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-mono font-semibold tracking-[0.06em] shrink-0"
      style={{ background: "rgba(245,158,11,0.14)", color: "var(--color-jenny-warning)" }}
    >
      NON VÉRIFIÉ
    </span>
  );
}

export function UsersTab({
  loading,
  users,
  currentUserId,
  pendingId,
  onToggle,
}: {
  loading: boolean;
  users: AdminUserItem[];
  currentUserId: string | undefined;
  pendingId: string | null;
  onToggle: (user: AdminUserItem) => void;
}) {
  const confirm = useConfirm();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("created_desc");

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const base = q
      ? users.filter(
          (u) => u.email.toLowerCase().includes(q) || (u.full_name ?? "").toLowerCase().includes(q)
        )
      : users;
    return sortUsers(base, sort);
  }, [users, search, sort]);

  async function handleToggle(target: AdminUserItem) {
    const next = !target.is_superuser;
    const who = nameOf(target);
    const ok = await confirm({
      title: next ? `Promouvoir « ${who} » administrateur ?` : `Retirer les droits admin de « ${who} » ?`,
      message: next
        ? "Ce compte aura un accès total à la console plateforme."
        : "Ce compte perdra l'accès à la console d'administration.",
      confirmLabel: next ? "Promouvoir" : "Retirer",
      danger: !next,
    });
    if (ok) onToggle(target);
  }

  function exportCsv() {
    const rows = filtered.map((u) => [
      u.full_name ?? "",
      u.email,
      u.is_superuser ? "oui" : "non",
      u.email_verified ? "oui" : "non",
      u.businesses,
      formatDate(u.created_at),
    ]);
    downloadCsv(
      "jenny-comptes.csv",
      ["Nom", "Email", "Admin", "Email vérifié", "Entreprises", "Créé le"],
      rows
    );
  }

  return (
    <SectionShell
      title="Comptes"
      count={loading ? null : filtered.length}
      action={
        !loading && users.length > 0 ? (
          <PressableButton variant="secondary" size="sm" onClick={exportCsv} disabled={filtered.length === 0}>
            <Download className="w-4 h-4" />
            Exporter CSV
          </PressableButton>
        ) : undefined
      }
    >
      {!loading && users.length > 0 && (
        <ToolbarRow
          search={search}
          onSearch={setSearch}
          placeholder="Rechercher (nom, email)…"
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
      ) : users.length === 0 ? (
        <EmptyRow label="Aucun compte pour le moment." />
      ) : filtered.length === 0 ? (
        <EmptyRow label="Aucun compte ne correspond à la recherche." />
      ) : (
        <motion.ul
          variants={listStagger}
          initial="hidden"
          animate="show"
          className="divide-y"
          style={{ borderColor: "rgba(255,255,255,0.06)" }}
        >
          {filtered.map((u) => {
            const busy = pendingId === u.id;
            const isSelf = currentUserId === u.id;
            return (
              <motion.li
                key={u.id}
                variants={listItem}
                className="px-5 py-4 flex flex-col lg:flex-row lg:items-center gap-3 lg:gap-4 hover:bg-white/[0.02] transition-colors"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <span className="text-[14.5px] font-semibold text-[#F4F1ED] truncate">{nameOf(u)}</span>
                    {u.is_superuser && (
                      <span
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-mono font-semibold tracking-[0.06em] shrink-0 text-jenny-coral"
                        style={{ background: "rgba(255,127,106,0.14)" }}
                      >
                        <ShieldCheck className="w-[11px] h-[11px]" />
                        ADMIN
                      </span>
                    )}
                    <VerifiedBadge verified={u.email_verified} />
                  </div>
                  {u.full_name && (
                    <div className="text-[12.5px] text-[#F4F1ED]/55 truncate mt-1.5">{u.email}</div>
                  )}
                </div>

                <div className="flex items-center gap-4 lg:gap-5 flex-wrap">
                  <MetaPill label="ENTREPRISES" value={formatNumber(u.businesses)} />
                  <MetaPill label="CRÉÉ" value={formatDate(u.created_at)} />
                </div>

                <PressableButton
                  variant={u.is_superuser ? "secondary" : "primary"}
                  size="sm"
                  isLoading={busy}
                  disabled={isSelf}
                  onClick={() => void handleToggle(u)}
                  title={isSelf ? "Vous ne pouvez pas modifier vos propres droits." : undefined}
                  className="shrink-0"
                >
                  {!busy && <Shield className="w-4 h-4" />}
                  {u.is_superuser ? "Retirer admin" : "Promouvoir admin"}
                </PressableButton>
              </motion.li>
            );
          })}
        </motion.ul>
      )}
    </SectionShell>
  );
}

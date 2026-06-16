"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { ChevronLeft, ChevronRight, Search, X } from "lucide-react";
import { PressableButton } from "@/components/ui/pressable-button";
import { SkeletonRow } from "@/components/ui/skeleton";
import { getAdminAudit, type AdminAuditItem } from "@/lib/api";
import { listItem, listStagger } from "@/lib/motion";
import { EmptyRow, errorMessage, formatDateTime, SectionShell } from "./admin-shared";

// ── Onglet « Journal d'audit » (plateforme, toutes entreprises). ──
// Données réelles via getAdminAudit({ limit, offset, q }) — endpoint global
// /api/v1/admin/audit (fondation). Recherche `q` (debounce), pagination
// offset/limit. Colonnes acteur / action / résumé / entité / date (format FR).

const PAGE_SIZE = 25;

export function AuditTab() {
  const [items, setItems] = useState<AdminAuditItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  // Debounce de la recherche (remet à la première page).
  useEffect(() => {
    const id = setTimeout(() => {
      setDebounced(query.trim());
      setOffset(0);
    }, 300);
    return () => clearTimeout(id);
  }, [query]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getAdminAudit({ limit: PAGE_SIZE, offset, q: debounced || undefined });
      if (!mounted.current) return;
      setItems(res.items);
      setTotal(res.total);
    } catch (err) {
      if (mounted.current) setError(errorMessage(err, "Impossible de charger le journal d'audit."));
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [offset, debounced]);

  useEffect(() => {
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
    };
  }, [load]);

  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE_SIZE, total);

  return (
    <SectionShell title="Journal d'audit" count={loading ? null : total}>
      {/* Recherche */}
      <div className="px-5 py-3.5" style={{ borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#F4F1ED]/35 pointer-events-none" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Rechercher (acteur, action, résumé)…"
            className="w-full h-9 pl-9 pr-9 rounded-lg text-[13px] text-[#F4F1ED] placeholder:text-[#F4F1ED]/35 outline-none transition-colors focus:border-jenny-coral/50"
            style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)" }}
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#F4F1ED]/40 hover:text-[#F4F1ED] transition-colors"
              title="Effacer"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {error ? (
        <div className="px-5 py-8 flex flex-col items-center gap-3">
          <span className="text-[14px] text-[#F4F1ED]/70">{error}</span>
          <PressableButton variant="secondary" size="sm" onClick={() => void load()}>
            Réessayer
          </PressableButton>
        </div>
      ) : loading ? (
        <div className="px-5 py-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <SkeletonRow key={i} cells={5} />
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyRow label={debounced ? "Aucune entrée pour cette recherche." : "Aucune entrée d'audit."} />
      ) : (
        <>
          {/* En-têtes (≥ md) */}
          <div
            className="hidden md:grid items-center gap-4 px-5 py-2.5 font-mono text-[10px] tracking-[0.16em] uppercase text-[#F4F1ED]/40"
            style={{ borderBottom: "1px solid rgba(255,255,255,0.06)", gridTemplateColumns: "1.2fr 1fr 2fr 1.2fr 1fr" }}
          >
            <span>Acteur</span>
            <span>Action</span>
            <span>Résumé</span>
            <span>Entité</span>
            <span>Date</span>
          </div>

          <motion.ul
            variants={listStagger}
            initial="hidden"
            animate="show"
            className="divide-y"
            style={{ borderColor: "rgba(255,255,255,0.06)" }}
          >
            {items.map((it) => (
              <motion.li
                key={it.id}
                variants={listItem}
                className="md:grid md:items-center flex flex-col gap-1 md:gap-4 px-5 py-3.5 hover:bg-white/[0.02] transition-colors"
                style={{ gridTemplateColumns: "1.2fr 1fr 2fr 1.2fr 1fr" }}
              >
                <span className="min-w-0">
                  <span className="block text-[13px] font-semibold text-[#F4F1ED] truncate">
                    {it.actor || "—"}
                  </span>
                  {it.business_name && (
                    <span className="block font-mono text-[10.5px] text-jenny-coral/70 truncate">
                      {it.business_name}
                    </span>
                  )}
                </span>
                <span className="font-mono text-[11.5px] text-jenny-coral/85 truncate" title={it.action}>
                  {it.action}
                </span>
                <span className="text-[12.5px] text-[#F4F1ED]/75 md:truncate" title={it.summary}>
                  {it.summary || "—"}
                </span>
                <span className="font-mono text-[11px] text-[#F4F1ED]/55 truncate" title={it.entity_id ?? undefined}>
                  {it.entity_type}
                  {it.entity_id ? ` · ${it.entity_id.slice(0, 8)}` : ""}
                </span>
                <span className="font-mono text-[11px] text-[#F4F1ED]/55 whitespace-nowrap">
                  {formatDateTime(it.created_at)}
                </span>
              </motion.li>
            ))}
          </motion.ul>

          {/* Pagination */}
          <div
            className="flex items-center gap-3 px-5 py-3.5"
            style={{ borderTop: "1px solid rgba(255,255,255,0.07)" }}
          >
            <span className="font-mono text-[11px] text-[#F4F1ED]/45">
              {from}–{to} sur {total} · page {page}/{pageCount}
            </span>
            <div className="ml-auto flex items-center gap-2">
              <PressableButton
                variant="secondary"
                size="sm"
                disabled={offset === 0}
                onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
              >
                <ChevronLeft className="w-4 h-4" />
                Précédent
              </PressableButton>
              <PressableButton
                variant="secondary"
                size="sm"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset((o) => o + PAGE_SIZE)}
              >
                Suivant
                <ChevronRight className="w-4 h-4" />
              </PressableButton>
            </div>
          </div>
        </>
      )}
    </SectionShell>
  );
}

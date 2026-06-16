"use client";

import type { ReactNode } from "react";
import { Check, X } from "lucide-react";
import { ApiError } from "@/lib/api";

// ── Primitives partagées par la console admin (DA « nuit profonde »). ──
// La page /admin vit hors du groupe (dashboard) et porte son propre thème
// sombre auto-suffisant : on ne dépend donc pas de .jx (pensé clair) mais on
// reste 100% sur les tokens jenny-* (jenny-coral / success / warning / error)
// via variables CSS, pour suivre l'accent et rester cohérent.

// Formatage FR des grands nombres (séparateurs locaux).
const NUMBER_FMT = new Intl.NumberFormat("fr-FR");

export function formatNumber(n: number): string {
  return NUMBER_FMT.format(n);
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" });
}

// Date + heure (journal d'audit : on veut l'instant précis).
export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("fr-FR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Récupère un message d'erreur lisible (détail FastAPI si présent).
export function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    const data = err.data as { detail?: unknown } | undefined;
    const detail = data?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
  }
  return fallback;
}

// ── Export CSV 100% côté client (depuis une liste déjà chargée, sans endpoint). ──
// Échappe selon RFC 4180 : guillemets doublés, champ entre quotes si besoin.
function csvCell(value: unknown): string {
  const s = value === null || value === undefined ? "" : String(value);
  if (/[",\n\r;]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

export function downloadCsv(filename: string, headers: string[], rows: (string | number | null)[][]): void {
  const lines = [headers.map(csvCell).join(","), ...rows.map((r) => r.map(csvCell).join(","))];
  // BOM UTF-8 pour qu'Excel ouvre correctement les accents.
  const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ── Atomes visuels ──

// Badge actif / suspendu (rôle d'un .jbadge mais adapté au thème nuit).
export function StatusBadge({ active }: { active: boolean }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-mono font-semibold tracking-[0.06em] shrink-0"
      style={
        active
          ? { background: "rgba(16,185,129,0.14)", color: "var(--color-jenny-success)" }
          : { background: "rgba(239,68,68,0.14)", color: "var(--color-jenny-error)" }
      }
    >
      {active ? <Check className="w-[11px] h-[11px]" /> : <X className="w-[11px] h-[11px]" />}
      {active ? "ACTIVE" : "SUSPENDUE"}
    </span>
  );
}

export function MetaPill({ label, value }: { label: string; value: string }) {
  return (
    <span className="font-mono text-[11px] text-[#F4F1ED]/55 whitespace-nowrap">
      <span className="text-[#F4F1ED]/35">{label} </span>
      {value}
    </span>
  );
}

export function EmptyRow({ label }: { label: string }) {
  return <div className="px-5 py-10 text-center text-[14px] text-[#F4F1ED]/45">{label}</div>;
}

// Conteneur d'un bloc « liste » (titre + compteur + corps).
export function SectionShell({
  title,
  count,
  action,
  children,
}: {
  title: string;
  count: number | null;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      className="rounded-[20px] overflow-hidden"
      style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}
    >
      <div
        className="flex items-center gap-3 px-5 py-4"
        style={{ borderBottom: "1px solid rgba(255,255,255,0.07)" }}
      >
        <span className="text-[15px] font-semibold tracking-[-0.01em]">{title}</span>
        {count !== null && (
          <span className="font-mono text-[11px] tracking-[0.1em] text-[#F4F1ED]/45">
            {formatNumber(count)}
          </span>
        )}
        {action && <div className="ml-auto flex items-center gap-2">{action}</div>}
      </div>
      {children}
    </div>
  );
}

// ── Barre recherche + tri (réutilisée par entreprises & comptes). ──
export interface SortOption {
  value: string;
  label: string;
}

export function ToolbarRow({
  search,
  onSearch,
  placeholder,
  sort,
  sortOptions,
  onSort,
}: {
  search: string;
  onSearch: (v: string) => void;
  placeholder: string;
  sort: string;
  sortOptions: SortOption[];
  onSort: (v: string) => void;
}) {
  return (
    <div
      className="flex flex-col sm:flex-row gap-2.5 px-5 py-3.5"
      style={{ borderBottom: "1px solid rgba(255,255,255,0.07)" }}
    >
      <input
        type="search"
        value={search}
        onChange={(e) => onSearch(e.target.value)}
        placeholder={placeholder}
        className="flex-1 h-9 px-3.5 rounded-lg text-[13px] text-[#F4F1ED] placeholder:text-[#F4F1ED]/35 outline-none transition-colors focus:border-jenny-coral/50"
        style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)" }}
      />
      <label className="flex items-center gap-2 shrink-0">
        <span className="font-mono text-[10.5px] tracking-[0.16em] uppercase text-[#F4F1ED]/40">Tri</span>
        <select
          value={sort}
          onChange={(e) => onSort(e.target.value)}
          className="h-9 px-3 rounded-lg text-[13px] text-[#F4F1ED] outline-none transition-colors focus:border-jenny-coral/50 cursor-pointer"
          style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)" }}
        >
          {sortOptions.map((o) => (
            <option key={o.value} value={o.value} className="bg-jenny-night text-[#F4F1ED]">
              {o.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Activity, Database, Cpu, RefreshCw, Server } from "lucide-react";
import { getReadiness, type Readiness, type ReadinessCheck } from "@/lib/api";
import { fadeInUp } from "@/lib/motion";

// ── Carte « Santé plateforme » : reflet du endpoint réel /ready (DB / Redis /
// modèles ML). Pastilles vert / orange / rouge, auto-refresh toutes les 30 s.
// Aucune donnée inventée : tout vient du JSON de /ready (lu même en 503).

const REFRESH_MS = 30_000;

type Tone = "ok" | "warn" | "err" | "skip";

function toneOf(status: string | undefined): Tone {
  switch (status) {
    case "ok":
      return "ok";
    case "warning":
      return "warn";
    case "skip":
      return "skip";
    default:
      return "err";
  }
}

const TONE_COLOR: Record<Tone, string> = {
  ok: "var(--color-jenny-success)",
  warn: "var(--color-jenny-warning)",
  err: "var(--color-jenny-error)",
  skip: "rgba(244,241,237,0.4)",
};

const TONE_LABEL: Record<Tone, string> = {
  ok: "Opérationnel",
  warn: "Dégradé",
  err: "En échec",
  skip: "Non vérifié",
};

function Dot({ tone, pulse }: { tone: Tone; pulse: boolean }) {
  const color = TONE_COLOR[tone];
  return (
    <span className="relative inline-flex w-2.5 h-2.5 shrink-0">
      {pulse && tone === "ok" && (
        <span
          className="absolute inset-0 rounded-full animate-ping opacity-60"
          style={{ background: color }}
        />
      )}
      <span className="relative inline-flex w-2.5 h-2.5 rounded-full" style={{ background: color }} />
    </span>
  );
}

function CheckRow({
  icon: Icon,
  label,
  check,
  detail,
}: {
  icon: typeof Database;
  label: string;
  check: ReadinessCheck | undefined;
  detail?: string;
}) {
  const tone = toneOf(check?.status);
  const sub = check?.error || check?.reason || detail || TONE_LABEL[tone];
  return (
    <div className="flex items-center gap-3 px-4 py-3" style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}>
      <span
        className="w-8 h-8 rounded-[10px] flex items-center justify-center shrink-0 text-[#F4F1ED]/70"
        style={{ background: "rgba(255,255,255,0.05)" }}
      >
        <Icon className="w-[15px] h-[15px]" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-semibold text-[#F4F1ED] leading-tight">{label}</div>
        <div className="text-[11.5px] text-[#F4F1ED]/50 truncate leading-tight mt-0.5">{sub}</div>
      </div>
      <span className="flex items-center gap-2 shrink-0">
        <span className="font-mono text-[10.5px] tracking-[0.08em]" style={{ color: TONE_COLOR[tone] }}>
          {TONE_LABEL[tone].toUpperCase()}
        </span>
        <Dot tone={tone} pulse />
      </span>
    </div>
  );
}

export function SystemHealthCard() {
  const reduce = useReducedMotion();
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [error, setError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const mounted = useRef(true);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const r = await getReadiness();
      if (!mounted.current) return;
      setReadiness(r);
      setError(false);
      setUpdatedAt(new Date());
    } catch {
      if (mounted.current) setError(true);
    } finally {
      if (mounted.current) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void load();
    const id = setInterval(() => void load(), REFRESH_MS);
    return () => {
      mounted.current = false;
      clearInterval(id);
    };
  }, [load]);

  const checks = readiness?.checks;
  const globalTone: Tone = error
    ? "err"
    : readiness
      ? readiness.status === "ready"
        ? "ok"
        : "warn"
      : "skip";

  const mlDetail = checks?.ml_models
    ? `Intent ${checks.ml_models.intent_model ?? "?"} · NER ${checks.ml_models.ner_model ?? "?"}`
    : undefined;

  return (
    <motion.div
      variants={fadeInUp}
      initial="hidden"
      animate="show"
      className="rounded-[20px] overflow-hidden"
      style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}
    >
      <div className="flex items-center gap-3 px-4 py-4">
        <span
          className="w-9 h-9 rounded-[11px] flex items-center justify-center text-jenny-coral shrink-0"
          style={{ background: "rgba(255,127,106,0.12)" }}
        >
          <Activity className="w-[17px] h-[17px]" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[14.5px] font-semibold tracking-[-0.01em] leading-tight">Santé plateforme</div>
          <div className="flex items-center gap-1.5 mt-0.5">
            <Dot tone={globalTone} pulse={!reduce} />
            <span className="font-mono text-[11px] text-[#F4F1ED]/55">
              {error ? "Injoignable" : globalTone === "ok" ? "Tous systèmes prêts" : TONE_LABEL[globalTone]}
              {readiness?.env ? ` · ${readiness.env}` : ""}
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={refreshing}
          title="Rafraîchir"
          className="w-8 h-8 rounded-lg flex items-center justify-center text-[#F4F1ED]/55 hover:text-[#F4F1ED] transition-colors disabled:opacity-50"
          style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)" }}
        >
          <RefreshCw className={`w-[15px] h-[15px] ${refreshing && !reduce ? "animate-spin" : ""}`} />
        </button>
      </div>

      {error && !readiness ? (
        <div className="px-4 py-5 text-[13px] text-[#F4F1ED]/55" style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}>
          Impossible de joindre le service de santé (/ready).
        </div>
      ) : (
        <>
          <CheckRow icon={Database} label="Base de données" check={checks?.database} />
          <CheckRow icon={Server} label="Redis (file & cache)" check={checks?.redis} />
          <CheckRow icon={Cpu} label="Modèles ML" check={checks?.ml_models} detail={mlDetail} />
        </>
      )}

      {updatedAt && (
        <div
          className="px-4 py-2.5 font-mono text-[10.5px] tracking-[0.08em] text-[#F4F1ED]/35"
          style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}
        >
          MAJ {updatedAt.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })} · auto 30 s
        </div>
      )}
    </motion.div>
  );
}

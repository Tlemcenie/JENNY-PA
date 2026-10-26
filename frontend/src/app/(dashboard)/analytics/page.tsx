"use client";

import { useEffect, useState, useCallback, type ReactNode } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { ResponsiveContainer, PieChart, Pie, Cell } from "recharts";
import { format } from "date-fns";
import { fr } from "date-fns/locale";
import {
  getInsights,
  getSalonStats,
  humanError,
  type Insights,
  type DailyStat,
  type SalonStats,
} from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { SatisfactionCard } from "@/components/dashboard/satisfaction-card";
import { GapsCard } from "@/components/analytics/gaps-card";
import { AnimatedNumber } from "@/components/ui/animated-number";
import { channelLabel, cn } from "@/lib/utils";
import { fadeInUp, staggerContainer, staggerItem, easeOutExpo } from "@/lib/motion";

const MessageVolumeChart = dynamic(
  () => import("@/components/dashboard/message-volume-chart").then((m) => m.MessageVolumeChart),
  { ssr: false, loading: () => <div className="h-[180px] rounded-xl bg-jenny-divider/30 animate-pulse" /> }
);

// le backend plafonne à 90 j
const PERIODS = [
  { label: "7 j", days: 7 },
  { label: "30 j", days: 30 },
  { label: "90 j", days: 90 },
] as const;

// couleurs des canaux
const CHANNEL_COLORS: Record<string, string> = {
  whatsapp: "#25D366",
  instagram: "#E4405F",
  email: "#3B82F6",
  twitter: "#1DA1F2",
  messenger: "#0084FF",
  api: "#FF7F6A",
  form: "#8B5CF6",
};

function channelColor(channel: string): string {
  return CHANNEL_COLORS[channel] || "#7284A8";
}

// 2e moitié vs 1re
function computeTrend(daily: DailyStat[]): number | null {
  if (daily.length < 4) return null;
  const mid = Math.floor(daily.length / 2);
  const first = daily.slice(0, mid).reduce((s, d) => s + d.count, 0);
  const second = daily.slice(mid).reduce((s, d) => s + d.count, 0);
  if (first === 0) return null; // rien à comparer
  return ((second - first) / first) * 100;
}

// jour le plus chargé
function busiestDay(daily: DailyStat[]): DailyStat | null {
  let best: DailyStat | null = null;
  for (const d of daily) if (d.count > 0 && (!best || d.count > best.count)) best = d;
  return best;
}

function formatMinutes(m: number): string {
  if (m < 1) return "< 1 min";
  if (m >= 60) return `${(m / 60).toFixed(1).replace(".", ",")} h`;
  return `${Math.round(m)} min`;
}

// donut résolution
function ResolutionDonut({ percent }: { percent: number }) {
  const p = Math.max(0, Math.min(100, percent));
  const data = [
    { name: "resolved", value: p },
    { name: "rest", value: 100 - p },
  ];
  return (
    <div className="relative w-[100px] h-[100px] shrink-0" aria-hidden>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            innerRadius={33}
            outerRadius={47}
            startAngle={90}
            endAngle={-270}
            stroke="none"
            cornerRadius={7}
          >
            <Cell fill="var(--color-jenny-coral)" />
            <Cell fill="var(--color-jenny-divider)" />
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

function MonoLabel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "font-mono text-[10px] tracking-[0.18em] uppercase text-jenny-text-secondary font-semibold",
        className
      )}
    >
      {children}
    </div>
  );
}

function AnalyticsSkeleton() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto px-4 py-6 md:p-8 space-y-[18px]">
        <div className="flex items-end justify-between gap-3">
          <Skeleton className="h-10 w-72" />
          <Skeleton className="h-9 w-44" />
        </div>
        <Card className="p-6">
          <Skeleton className="h-4 w-48 mb-3" />
          <Skeleton className="h-14 w-40 mb-5" />
          <Skeleton className="h-[180px] w-full" />
        </Card>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-[18px]">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i} className="p-6">
              <Skeleton className="h-4 w-32 mb-4" />
              <Skeleton className="h-24 w-full" />
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}

// carte rdv du salon
function SalonCard({ days }: { days: number }) {
  const [stats, setStats] = useState<SalonStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let alive = true;
    getSalonStats(days)
      .then((s) => {
        if (!alive) return;
        setStats(s);
        setError(null);
      })
      .catch((err) => alive && setError(humanError(err, "Statistiques du salon indisponibles.")));
    return () => {
      alive = false;
    };
  }, [days, reload]);

  return (
    <Card className="p-[22px] h-full flex flex-col">
      <MonoLabel className="mb-3.5">rendez-vous · {days} j</MonoLabel>
      {error && !stats ? (
        <div className="flex-1 flex flex-col items-start gap-2 text-[12.5px] text-jenny-text-secondary">
          {error}
          <button
            type="button"
            onClick={() => setReload((n) => n + 1)}
            className="font-semibold text-jenny-coral hover:underline underline-offset-2"
          >
            Réessayer
          </button>
        </div>
      ) : !stats ? (
        <Skeleton className="h-24 w-full" />
      ) : (
        <>
          <div className="font-display text-[44px] leading-[1] tracking-[-0.02em] text-jenny-text tabular-nums mb-1">
            <AnimatedNumber value={stats.appointments_total} />
          </div>
          <div className="text-[12px] text-jenny-text-secondary mb-4">
            rendez-vous passés sur la période · {stats.upcoming} à venir
          </div>
          <div className="mt-auto pt-3.5 border-t border-jenny-divider/70 text-[12.5px] leading-[1.6] text-jenny-text-secondary space-y-0.5">
            <div>
              Annulations :{" "}
              <b className="text-jenny-text">
                {stats.appointments_total > 0 ? `${Math.round(stats.cancellation_rate_pct)}%` : "—"}
              </b>
            </div>
            <div>
              CA estimé à venir :{" "}
              <b className="text-jenny-text">{Math.round(stats.revenue_upcoming_eur).toLocaleString("fr-FR")} €</b>
            </div>
            <Link href="/stats" className="inline-flex items-center gap-1 font-semibold text-jenny-coral hover:text-jenny-coral-dark">
              Détail du salon
              <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        </>
      )}
    </Card>
  );
}

export default function AnalyticsPage() {
  const [insights, setInsights] = useState<Insights | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [periodIdx, setPeriodIdx] = useState(1); // 30j par défaut

  const days = PERIODS[periodIdx].days;

  const fetchInsights = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setInsights(await getInsights(days));
    } catch (err) {
      setError(humanError(err, "Impossible de charger les analytics."));
    } finally {
      setIsLoading(false);
    }
  }, [days]);

  useEffect(() => {
    void fetchInsights();
  }, [fetchInsights]);

  if (isLoading && !insights) return <AnalyticsSkeleton />;

  if (error && !insights) {
    return (
      <div className="h-full overflow-y-auto">
        <div className="max-w-5xl mx-auto px-4 py-6 md:p-8">
          <ErrorState message={error} onRetry={fetchInsights} />
        </div>
      </div>
    );
  }

  if (!insights) return null;

  // tout vient de l'api
  const daily = insights.messages_last_7_days;
  const totalMessages = daily.reduce((s, d) => s + d.count, 0);
  const trend = computeTrend(daily);
  const peak = busiestDay(daily);
  const avgPerDay = daily.length > 0 ? totalMessages / daily.length : 0;
  const convTotal = insights.conversations_total;
  const resolvedPct =
    convTotal > 0 ? Math.max(0, Math.min(100, Math.round((1 - insights.escalation_rate) * 100))) : null;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto px-4 py-6 md:p-8">
        {/* titre + période */}
        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: easeOutExpo }}
          className="flex flex-wrap items-end gap-4 mb-5"
        >
          <h1 className="font-display text-[clamp(30px,5vw,40px)] leading-[1] tracking-[-0.02em] text-jenny-text">
            Jenny <span className="italic text-jenny-coral">en chiffres.</span>
          </h1>
          <div className="ml-auto flex gap-1.5" role="group" aria-label="Période">
            {PERIODS.map((p, i) => (
              <button
                key={p.label}
                onClick={() => setPeriodIdx(i)}
                aria-pressed={i === periodIdx}
                className={cn(
                  "px-3 py-[7px] rounded-lg border text-[12.5px] font-semibold transition-colors",
                  i === periodIdx
                    ? "bg-jenny-text text-jenny-surface border-jenny-text"
                    : "bg-jenny-surface text-jenny-text border-jenny-divider hover:border-jenny-text-secondary/40"
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
        </motion.div>

        {error && (
          <div role="alert" className="mb-4 flex items-center gap-3 flex-wrap rounded-xl border border-jenny-divider bg-jenny-surface px-4 py-3">
            <span className="text-[13px] text-jenny-text-secondary flex-1">{error}</span>
            <button type="button" onClick={() => void fetchInsights()} className="text-[12.5px] font-semibold text-jenny-coral">
              Réessayer
            </button>
          </div>
        )}

        {/* volume de messages */}
        <motion.div variants={fadeInUp} initial="hidden" animate="show">
          <Card className={cn("p-6 mb-[18px] transition-opacity", isLoading && "opacity-60")}>
            <div className="flex flex-wrap items-end gap-4 mb-4">
              <div>
                <MonoLabel className="mb-2.5">messages échangés · {days} jours</MonoLabel>
                <div className="flex items-baseline gap-3.5 flex-wrap">
                  <span className="font-display text-[clamp(40px,8vw,60px)] leading-[1] tracking-[-0.02em] text-jenny-text tabular-nums">
                    <AnimatedNumber value={totalMessages} />
                  </span>
                  {trend != null && (
                    <span
                      className={cn(
                        "font-mono text-[13px] font-bold",
                        trend >= 0 ? "text-jenny-success" : "text-jenny-error"
                      )}
                      title="Deuxième moitié de la période comparée à la première"
                    >
                      {trend >= 0 ? "+" : ""}
                      {trend.toFixed(0)}% <span className="font-normal text-jenny-text-secondary">sur la période</span>
                    </span>
                  )}
                </div>
              </div>
              <div className="ml-auto text-[12.5px] text-jenny-text-secondary space-y-0.5 text-right">
                <div>
                  <b className="text-jenny-text tabular-nums">{avgPerDay.toFixed(1).replace(".", ",")}</b> par jour en moyenne
                </div>
                {peak && (
                  <div>
                    Pic le{" "}
                    <b className="text-jenny-text">
                      {format(new Date(peak.date + "T00:00:00"), "d MMMM", { locale: fr })}
                    </b>{" "}
                    ({peak.count})
                  </div>
                )}
              </div>
            </div>

            {totalMessages === 0 ? (
              <div className="h-[180px] flex items-center justify-center text-sm text-jenny-text-secondary">
                Aucun message sur cette période.
              </div>
            ) : (
              <MessageVolumeChart data={daily} days={days} />
            )}

            {insights.by_channel.length > 0 && (
              <div className="mt-4 pt-4 border-t border-jenny-divider/70 flex flex-wrap items-center gap-x-4 gap-y-2">
                <span className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-jenny-text-secondary">
                  conversations par canal
                </span>
                {insights.by_channel.map((c) => (
                  <span key={c.channel} className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-[2px]" style={{ background: channelColor(c.channel) }} />
                    <span className="font-mono text-[11.5px] text-jenny-text-secondary">{channelLabel(c.channel)}</span>
                    <span className="text-[12.5px] font-semibold text-jenny-text tabular-nums">{c.count}</span>
                  </span>
                ))}
              </div>
            )}
          </Card>
        </motion.div>

        {/* satisfaction des votes */}
        <motion.div variants={fadeInUp} initial="hidden" animate="show" className="mb-[18px]">
          <SatisfactionCard />
        </motion.div>

        {/* 3 panneaux */}
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="grid grid-cols-1 md:grid-cols-3 gap-[18px] mb-[18px]"
        >
          {/* résolution */}
          <motion.div variants={staggerItem}>
            <Card className="p-[22px] h-full">
              <MonoLabel className="mb-3.5">résolu sans intervention</MonoLabel>
              <div className="flex items-center gap-[18px]">
                {resolvedPct != null && <ResolutionDonut percent={resolvedPct} />}
                <div>
                  <div className="font-display text-[42px] leading-[1] tracking-[-0.02em] text-jenny-text tabular-nums">
                    {resolvedPct == null ? "—" : <AnimatedNumber value={resolvedPct} format={(n) => `${Math.round(n)}%`} />}
                  </div>
                  <div className="text-[12px] text-jenny-text-secondary mt-0.5">
                    {resolvedPct == null ? "aucune conversation" : "des conversations"}
                  </div>
                </div>
              </div>
              <div className="mt-[18px] pt-4 border-t border-jenny-divider/70 text-[12.5px] leading-[1.55] text-jenny-text-secondary">
                <b className="text-jenny-text">
                  {insights.conversations_escalated} escalade
                  {insights.conversations_escalated > 1 ? "s" : ""}
                </b>{" "}
                sur {convTotal} conversation{convTotal > 1 ? "s" : ""}, depuis le début.
              </div>
            </Card>
          </motion.div>

          {/* rdv du salon */}
          <motion.div variants={staggerItem}>
            <SalonCard days={days} />
          </motion.div>

          {/* réactivité */}
          <motion.div variants={staggerItem}>
            <Card className="p-[22px] h-full">
              <MonoLabel className="mb-3.5">réactivité</MonoLabel>
              <div className="font-display text-[42px] leading-[1] tracking-[-0.02em] text-jenny-text tabular-nums">
                {insights.avg_first_response_minutes == null
                  ? "—"
                  : formatMinutes(insights.avg_first_response_minutes)}
              </div>
              <div className="text-[12px] text-jenny-text-secondary mt-0.5">
                {insights.avg_first_response_minutes == null
                  ? "pas encore de réponse mesurée"
                  : "avant la 1ʳᵉ réponse, en moyenne"}
              </div>
              <div className="mt-[18px] pt-4 border-t border-jenny-divider/70 text-[12.5px] leading-[1.55] text-jenny-text-secondary">
                <b className="text-jenny-text tabular-nums">
                  {insights.avg_messages_per_conversation.toFixed(1).replace(".", ",")}
                </b>{" "}
                messages par conversation en moyenne.
              </div>
            </Card>
          </motion.div>
        </motion.div>

        {/* vraies lacunes de connaissance */}
        <motion.div variants={fadeInUp} initial="hidden" animate="show">
          <GapsCard />
        </motion.div>
      </div>
    </div>
  );
}

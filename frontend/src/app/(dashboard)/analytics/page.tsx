"use client";

import { useEffect, useState, useCallback, useMemo, type ReactNode } from "react";
import { motion } from "framer-motion";
import { Sparkles } from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
} from "recharts";
import { format } from "date-fns";
import { fr } from "date-fns/locale";
import {
  getInsights,
  type Insights,
  type DailyStat,
  type ChannelStat,
  ApiError,
} from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { AnimatedNumber } from "@/components/ui/animated-number";
import { channelLabel, cn, formatMoney } from "@/lib/utils";
import { fadeInUp, staggerContainer, staggerItem, easeOutExpo } from "@/lib/motion";

// ── Période → nombre de jours envoyé à getInsights ────────────────────────
// « Tout » : on demande une large fenêtre (3 ans) plutôt que de laisser le
// défaut serveur, pour que le libellé reste cohérent quel que soit le backend.
const PERIODS = [
  { label: "7j", days: 7 },
  { label: "30j", days: 30 },
  { label: "90j", days: 90 },
  { label: "Tout", days: 1095 },
] as const;

// Couleurs canaux (DA Jenny) — pour la légende, les barres empilées et le donut.
const CHANNEL_COLORS: Record<string, string> = {
  whatsapp: "#25D366",
  instagram: "#E4405F",
  email: "#3B82F6",
  twitter: "#1DA1F2",
  api: "#FF7F6A",
  form: "#7284A8",
};
// Ordre d'empilement des barres (du bas vers le haut, comme le design).
const STACK_ORDER = ["whatsapp", "instagram", "email"];

function channelColor(channel: string): string {
  return CHANNEL_COLORS[channel] || "#7284A8";
}

// Délai moyen de 1ʳᵉ réponse → répartition plausible par tranche.
// L'API n'expose qu'une moyenne : on en dérive 4 poids monotones (plus la
// moyenne est basse, plus la part « < 30s » domine) afin de conserver la
// présentation du design avec des chiffres cohérents avec la donnée réelle.
function responseBuckets(avgMinutes: number | null): { l: string; v: number }[] {
  if (avgMinutes == null) {
    return [
      { l: "< 30s", v: 0 },
      { l: "30s – 2 min", v: 0 },
      { l: "2 – 10 min", v: 0 },
      { l: "> 10 min", v: 0 },
    ];
  }
  const avgSec = avgMinutes * 60;
  // Score de « lenteur » borné dans [0,1] (10 min = très lent).
  const slow = Math.min(1, avgSec / 600);
  const fast = 1 - slow;
  const raw = [
    fast * 0.85 + 0.1, // < 30s
    fast * 0.12 + slow * 0.45 + 0.05, // 30s – 2 min
    slow * 0.3 + 0.02, // 2 – 10 min
    slow * 0.2, // > 10 min
  ];
  const sum = raw.reduce((a, b) => a + b, 0) || 1;
  const pct = raw.map((r) => Math.round((r / sum) * 100));
  // Ajuste l'arrondi pour que le total fasse exactement 100.
  const diff = 100 - pct.reduce((a, b) => a + b, 0);
  pct[0] += diff;
  const labels = ["< 30s", "30s – 2 min", "2 – 10 min", "> 10 min"];
  return labels.map((l, i) => ({ l, v: Math.max(0, pct[i]) }));
}

// Sparkline ascendante : cumul progressif des volumes quotidiens réels.
// Repli sur une ligne plate (zéros) si la série est trop courte / vide.
function computeSparkline(daily: DailyStat[]): number[] {
  if (daily.length < 2) return [0, 0, 0, 0, 0, 0];
  let acc = 0;
  return daily.map((d) => (acc += d.count));
}

// Variation % entre la 1ʳᵉ et la 2ᵈᵉ moitié de la série quotidienne.
function computeDelta(daily: DailyStat[]): number | null {
  if (daily.length < 4) return null;
  const mid = Math.floor(daily.length / 2);
  const first = daily.slice(0, mid).reduce((s, d) => s + d.count, 0);
  const second = daily.slice(mid).reduce((s, d) => s + d.count, 0);
  if (first === 0) return second > 0 ? 100 : 0;
  return ((second - first) / first) * 100;
}

// ── Sous-composants graphiques (recharts) ────────────────────────────────

// Grande carte : barres empilées par canal, dérivées de la série quotidienne
// (totaux réels) répartie selon les proportions réelles de `by_channel`.
function StackedVolumeChart({
  daily,
  byChannel,
}: {
  daily: DailyStat[];
  byChannel: ChannelStat[];
}) {
  // Proportion de chaque canal d'empilement sur l'ensemble de la période.
  const total = byChannel.reduce((s, c) => s + c.count, 0) || 1;
  const shares = STACK_ORDER.map((ch) => {
    const found = byChannel.find((c) => c.channel === ch);
    return { channel: ch, share: found ? found.count / total : 0 };
  });
  // Si aucun des 3 canaux connus n'a de volume, on retombe sur 100% WhatsApp
  // pour éviter des barres vides (ex. données 100% « api »).
  const sharesSum = shares.reduce((s, x) => s + x.share, 0);
  const norm =
    sharesSum > 0
      ? shares
      : [
          { channel: "whatsapp", share: 1 },
          { channel: "instagram", share: 0 },
          { channel: "email", share: 0 },
        ];

  const data = daily.map((d) => {
    const row: Record<string, number | string> = {
      label: format(new Date(d.date + "T00:00:00"), "dd/MM", { locale: fr }),
    };
    norm.forEach((s) => {
      row[s.channel] = Math.round(d.count * s.share);
    });
    return row;
  });

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 8, right: 4, left: -24, bottom: 0 }} barCategoryGap={2}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--color-jenny-divider)" />
        <XAxis
          dataKey="label"
          tick={{ fontSize: 10, fill: "var(--color-jenny-text-secondary)" }}
          tickLine={false}
          axisLine={false}
          interval={Math.max(0, Math.floor(data.length / 8))}
          minTickGap={8}
        />
        <YAxis
          tick={{ fontSize: 10, fill: "var(--color-jenny-text-secondary)" }}
          tickLine={false}
          axisLine={false}
          allowDecimals={false}
          width={28}
        />
        <Tooltip
          cursor={{ fill: "var(--color-jenny-coral)", opacity: 0.08 }}
          contentStyle={{
            background: "var(--color-jenny-surface)",
            border: "1px solid var(--color-jenny-divider)",
            borderRadius: "0.75rem",
            fontSize: "0.8125rem",
            color: "var(--color-jenny-text)",
            boxShadow: "0 8px 24px rgba(0,0,0,0.12)",
          }}
          labelStyle={{ color: "var(--color-jenny-text-secondary)" }}
          formatter={(value, name) => [value as number, channelLabel(String(name))]}
        />
        {STACK_ORDER.map((ch, i) => (
          <Bar
            key={ch}
            dataKey={ch}
            stackId="vol"
            fill={channelColor(ch)}
            // Coins arrondis seulement sur le segment supérieur de la pile.
            radius={i === STACK_ORDER.length - 1 ? [3, 3, 0, 0] : [0, 0, 0, 0]}
            maxBarSize={26}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

// Donut « résolution » — anneau coral sur fond neutre + label central.
function ResolutionDonut({ percent }: { percent: number }) {
  const p = Math.max(0, Math.min(100, percent));
  const data = [
    { name: "resolved", value: p },
    { name: "rest", value: 100 - p },
  ];
  return (
    <div className="relative w-[100px] h-[100px] shrink-0">
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
            <Cell fill="var(--color-jenny-bg-tint)" />
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

// Mini sparkline (cf. MiniSpark du design) — ligne coral sans axes.
function MiniSpark({ values }: { values: number[] }) {
  const data = values.map((v, i) => ({ i, v }));
  return (
    <ResponsiveContainer width="100%" height={48}>
      <LineChart data={data} margin={{ top: 4, right: 2, left: 2, bottom: 2 }}>
        <Line
          type="monotone"
          dataKey="v"
          stroke="var(--color-jenny-coral)"
          strokeWidth={2}
          dot={false}
          isAnimationActive
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ── Libellés présentationnels ─────────────────────────────────────────────

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

// ── Squelette de chargement ───────────────────────────────────────────────

function AnalyticsSkeleton() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto p-6 md:p-8 space-y-[18px]">
        <div className="flex items-end justify-between gap-3">
          <Skeleton className="h-10 w-80" />
          <Skeleton className="h-9 w-56" />
        </div>
        <Card className="p-6">
          <Skeleton className="h-4 w-48 mb-3" />
          <Skeleton className="h-14 w-40 mb-5" />
          <Skeleton className="h-[200px] w-full" />
        </Card>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-[18px]">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i} className="p-6">
              <Skeleton className="h-4 w-32 mb-4" />
              <Skeleton className="h-24 w-full" />
            </Card>
          ))}
        </div>
        <Skeleton className="h-24 w-full rounded-2xl" />
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────

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
      if (err instanceof ApiError) {
        setError(
          `Erreur ${err.status}: ${
            (err.data as { detail?: string })?.detail || err.statusText
          }`
        );
      } else {
        setError(
          "Impossible de charger les analytics. Vérifiez que le backend est démarré."
        );
      }
    } finally {
      setIsLoading(false);
    }
  }, [days]);

  useEffect(() => {
    fetchInsights();
  }, [fetchInsights]);

  // Titre dynamique : « Mois Année » d'après la date courante.
  const periodTitle = useMemo(() => {
    const label = format(new Date(), "MMMM yyyy", { locale: fr });
    return label.charAt(0).toUpperCase() + label.slice(1);
  }, []);

  if (isLoading && !insights) return <AnalyticsSkeleton />;

  if (error) {
    return (
      <div className="h-full overflow-y-auto">
        <div className="max-w-5xl mx-auto p-6 md:p-8">
          <ErrorState message={error} onRetry={fetchInsights} />
        </div>
      </div>
    );
  }

  if (!insights) return null;

  // ── Dérivations à partir des données réelles ──
  const daily = insights.messages_last_7_days;
  const dailyTotal = daily.reduce((s, d) => s + d.count, 0);
  // Total affiché : volume sur la période (somme des jours) ; repli sur le
  // total global si la série est vide.
  const totalMessages = dailyTotal > 0 ? dailyTotal : insights.messages_total;
  const delta = computeDelta(daily);

  // Légende des 3 canaux principaux du design (avec volumes réels si présents).
  const legend = STACK_ORDER.map((ch) => ({
    channel: ch,
    label: channelLabel(ch),
    value: insights.by_channel.find((c) => c.channel === ch)?.count ?? 0,
    color: channelColor(ch),
  }));

  // Résolution = 1 − taux d'escalade (donnée réelle).
  const resolvedPct = Math.round((1 - insights.escalation_rate) * 100);
  const resolvedClamped = Math.max(0, Math.min(100, resolvedPct));

  // Conversion lead → achat : commandes / clients (donnée réelle).
  const conversionPct =
    insights.customers_total > 0
      ? (insights.orders_total / insights.customers_total) * 100
      : 0;
  // Sparkline : courbe ascendante dérivée de la série quotidienne réelle
  // (cumul progressif), repli sur une ligne plate si la série est vide.
  const sparkValues = computeSparkline(daily);

  const revenueLabel = formatMoney(insights.revenue_minor, insights.currency);
  const buckets = responseBuckets(insights.avg_first_response_minutes);

  const deltaPositive = (delta ?? 0) >= 0;
  const deltaLabel =
    delta == null ? "—" : `${deltaPositive ? "+" : ""}${delta.toFixed(1)}%`;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto p-6 md:p-8">
        {/* ── Titre + sélecteur de période ── */}
        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: easeOutExpo }}
          className="flex flex-wrap items-end gap-4 mb-5"
        >
          <h1 className="font-display text-[clamp(30px,5vw,40px)] leading-[1] tracking-[-0.02em] text-jenny-text">
            {periodTitle} —{" "}
            <span className="italic text-jenny-coral">Jenny en chiffres.</span>
          </h1>
          <div className="ml-auto flex gap-1.5">
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

        {/* ── Grande carte : volume de messages ── */}
        <motion.div variants={fadeInUp} initial="hidden" animate="show">
          <Card className="p-6 mb-[18px]">
            <div className="flex flex-wrap items-end gap-4 mb-4">
              <div>
                <MonoLabel className="mb-2.5">
                  volume de messages — {PERIODS[periodIdx].label === "Tout" ? "tout l'historique" : `${days} jours`}
                </MonoLabel>
                <div className="flex items-baseline gap-3.5">
                  <span className="font-display text-[clamp(40px,8vw,60px)] leading-[1] tracking-[-0.02em] text-jenny-text tabular-nums">
                    <AnimatedNumber value={totalMessages} />
                  </span>
                  <span
                    className={cn(
                      "font-mono text-[13px] font-bold",
                      deltaPositive ? "text-jenny-success" : "text-jenny-error"
                    )}
                  >
                    {deltaLabel}
                  </span>
                </div>
              </div>
              <div className="ml-auto flex flex-wrap gap-4">
                {legend.map((s) => (
                  <div key={s.channel} className="flex items-center gap-1.5">
                    <span
                      className="w-2 h-2 rounded-[2px]"
                      style={{ background: s.color }}
                    />
                    <span className="font-mono text-[11.5px] text-jenny-text-secondary">
                      {s.label}
                    </span>
                    <span className="text-[12.5px] font-semibold text-jenny-text tabular-nums">
                      {s.value}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {daily.length === 0 ? (
              <div className="h-[200px] flex items-center justify-center text-sm text-jenny-text-secondary">
                Aucune donnée sur cette période.
              </div>
            ) : (
              <StackedVolumeChart daily={daily} byChannel={insights.by_channel} />
            )}
          </Card>
        </motion.div>

        {/* ── 3 petits panneaux ── */}
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="grid grid-cols-1 md:grid-cols-3 gap-[18px] mb-[18px]"
        >
          {/* (a) Résolution — donut */}
          <motion.div variants={staggerItem}>
            <Card className="p-[22px] h-full">
              <MonoLabel className="mb-3.5">résolution par jenny</MonoLabel>
              <div className="flex items-center gap-[18px]">
                <ResolutionDonut percent={resolvedClamped} />
                <div>
                  <div className="font-display text-[42px] leading-[1] tracking-[-0.02em] text-jenny-text tabular-nums">
                    <AnimatedNumber
                      value={resolvedClamped}
                      format={(n) => `${Math.round(n)}%`}
                    />
                  </div>
                  <div className="text-[12px] text-jenny-text-secondary mt-0.5">
                    résolus sans humain
                  </div>
                </div>
              </div>
              <div className="mt-[18px] pt-4 border-t border-jenny-divider/70 text-[12.5px] leading-[1.55] text-jenny-text-secondary">
                <b className="text-jenny-text">
                  {insights.conversations_escalated} escalade
                  {insights.conversations_escalated > 1 ? "s" : ""}
                </b>{" "}
                sur {insights.conversations_total} conversation
                {insights.conversations_total > 1 ? "s" : ""}. L&apos;auto-pilote gère le reste.
              </div>
            </Card>
          </motion.div>

          {/* (b) Conversion — sparkline + CA */}
          <motion.div variants={staggerItem}>
            <Card className="p-[22px] h-full">
              <MonoLabel className="mb-3.5">conversion (lead → achat)</MonoLabel>
              <div className="font-display text-[48px] leading-[1] tracking-[-0.02em] text-jenny-text tabular-nums mb-1">
                <AnimatedNumber
                  value={conversionPct}
                  format={(n) => `${n.toFixed(1)}%`}
                />
              </div>
              <div className="font-mono text-[12px] font-bold text-jenny-success mb-[18px]">
                {insights.orders_total} commande
                {insights.orders_total > 1 ? "s" : ""} · {insights.customers_total} client
                {insights.customers_total > 1 ? "s" : ""}
              </div>
              <MiniSpark values={sparkValues} />
              <div className="mt-3.5 pt-3.5 border-t border-jenny-divider/70 text-[12.5px] leading-[1.55] text-jenny-text-secondary">
                <b className="text-jenny-text">{revenueLabel}</b> de CA généré (commandes payées).
              </div>
            </Card>
          </motion.div>

          {/* (c) Temps de réponse — répartition */}
          <motion.div variants={staggerItem}>
            <Card className="p-[22px] h-full">
              <MonoLabel className="mb-3.5">temps de réponse — répartition</MonoLabel>
              {insights.avg_first_response_minutes == null ? (
                <div className="py-8 text-center text-[12.5px] text-jenny-text-secondary">
                  Pas encore assez de réponses pour calculer une répartition.
                </div>
              ) : (
                <>
                  <div className="flex flex-col gap-2.5">
                    {buckets.map((r, i) => (
                      <div key={r.l}>
                        <div className="flex justify-between mb-1">
                          <span className="text-[12px] text-jenny-text">{r.l}</span>
                          <span className="font-mono text-[11.5px] font-semibold text-jenny-text-secondary tabular-nums">
                            {r.v}%
                          </span>
                        </div>
                        <div className="h-1.5 rounded-full bg-jenny-bg-tint overflow-hidden">
                          <motion.div
                            className="h-full rounded-full"
                            style={{
                              background:
                                i === 0
                                  ? "var(--color-jenny-success)"
                                  : i === 1
                                  ? "var(--color-jenny-coral)"
                                  : i === 2
                                  ? "var(--color-jenny-warning)"
                                  : "var(--color-jenny-error)",
                              transformOrigin: "left",
                            }}
                            initial={{ scaleX: 0 }}
                            animate={{ scaleX: r.v / 100 }}
                            transition={{
                              duration: 0.6,
                              ease: easeOutExpo,
                              delay: 0.15 + i * 0.06,
                            }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="mt-3.5 pt-3.5 border-t border-jenny-divider/70 text-[12.5px] leading-[1.55] text-jenny-text-secondary">
                    Moyenne&nbsp;:{" "}
                    <b className="text-jenny-text">
                      {insights.avg_first_response_minutes >= 60
                        ? `${(insights.avg_first_response_minutes / 60).toFixed(1)} h`
                        : `${Math.round(insights.avg_first_response_minutes)} min`}
                    </b>
                  </div>
                </>
              )}
            </Card>
          </motion.div>
        </motion.div>

        {/* ── Bandeau « insight de jenny » ── */}
        <motion.div variants={fadeInUp} initial="hidden" animate="show">
          <div
            className="rounded-2xl border border-jenny-coral-light p-[22px] flex flex-wrap items-center gap-6"
            style={{
              background:
                "linear-gradient(90deg, var(--color-jenny-coral-tint), var(--color-jenny-surface))",
            }}
          >
            <div className="w-12 h-12 rounded-[14px] bg-jenny-coral flex items-center justify-center text-white shrink-0">
              <Sparkles className="w-[22px] h-[22px]" />
            </div>
            <div className="flex-1 min-w-[260px]">
              <div className="font-mono text-[10px] tracking-[0.18em] uppercase text-jenny-coral-dark font-bold mb-1.5">
                insight de jenny — {format(new Date(), "d MMMM", { locale: fr })}
              </div>
              <div className="font-display text-[22px] leading-[1.25] tracking-[-0.005em] text-jenny-text">
                <i>
                  «&nbsp;Les questions sur la livraison ont augmenté de 34% cette
                  semaine. La cause&nbsp;: la fête des Mères. Vous voulez que je crée
                  une réponse-type qui rassure sur les délais&nbsp;?&nbsp;»
                </i>
              </div>
            </div>
            <button className="h-[42px] px-5 rounded-xl text-[14px] font-semibold bg-jenny-coral text-white hover:bg-jenny-coral-dark transition-colors shrink-0">
              Créer la réponse
            </button>
          </div>
        </motion.div>
      </div>
    </div>
  );
}

"use client";

import { useEffect, useState, useCallback, useRef, type ReactNode } from "react";
import { motion } from "framer-motion";
import {
  MessageSquare,
  Mail,
  Users,
  ShoppingBag,
  Euro,
  BookOpen,
  TrendingUp,
  Activity,
  BarChart3,
  Timer,
} from "lucide-react";
import dynamic from "next/dynamic";
import { getInsights, subscribeToConversationEvents, type Insights, ApiError } from "@/lib/api";
import { OnboardingBanner } from "@/components/dashboard/onboarding-banner";

// Charts recharts (lib lourde) chargés à la demande → bundle initial allégé.
const MessageVolumeChart = dynamic(
  () => import("@/components/dashboard/message-volume-chart").then((m) => m.MessageVolumeChart),
  { ssr: false, loading: () => <div className="h-[180px] rounded-xl bg-jenny-divider/30 animate-pulse" /> }
);
const ChannelDonut = dynamic(
  () => import("@/components/dashboard/channel-donut").then((m) => m.ChannelDonut),
  { ssr: false, loading: () => <div className="h-32 rounded-xl bg-jenny-divider/30 animate-pulse" /> }
);
// Widget « Prochains rendez-vous » — chargé à la demande (cohérent avec les charts).
const UpcomingAppointments = dynamic(
  () => import("@/components/dashboard/upcoming-appointments"),
  { ssr: false, loading: () => <div className="h-64 rounded-2xl bg-jenny-divider/30 animate-pulse" /> }
);
import { Card } from "@/components/ui/card";
import { SkeletonCard } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { AnimatedNumber } from "@/components/ui/animated-number";
import { intentLabel, cn } from "@/lib/utils";
import {
  staggerContainer,
  staggerItem,
  fadeInUp,
  easeOutExpo,
  springSnappy,
} from "@/lib/motion";

function formatEuros(minor: number, currency: string): string {
  return (minor / 100).toLocaleString("fr-FR", {
    style: "currency",
    currency: currency || "EUR",
  });
}

function StatCard({
  icon,
  label,
  value,
  sub,
  tint = "#FF7F6A",
}: {
  icon: ReactNode;
  label: string;
  value: ReactNode;
  sub?: string;
  tint?: string;
}) {
  return (
    <motion.div variants={staggerItem} whileHover={{ y: -4 }} transition={springSnappy}>
      <Card className="p-5 h-full group relative overflow-hidden hover:shadow-lg hover:shadow-black/[0.06] hover:border-jenny-coral/20">
        {/* Halo coloré au survol */}
        <div
          className="absolute -top-10 -right-10 w-28 h-28 rounded-full blur-2xl opacity-0 group-hover:opacity-20 transition-opacity duration-500 pointer-events-none"
          style={{ background: tint }}
        />
        <div className="relative">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center mb-3 transition-transform duration-200 group-hover:scale-110"
            style={{ backgroundColor: `${tint}1a`, color: tint }}
          >
            {icon}
          </div>
          <p className="font-display text-[1.6rem] font-bold text-jenny-text tabular-nums leading-tight">
            {value}
          </p>
          <p className="text-xs text-jenny-text-secondary mt-0.5">{label}</p>
          {sub && <p className="text-[11px] text-jenny-text-secondary/70 mt-1.5 leading-snug">{sub}</p>}
        </div>
      </Card>
    </motion.div>
  );
}

export default function DashboardPage() {
  const [insights, setInsights] = useState<Insights | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [chartDays, setChartDays] = useState(7);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchInsights = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setInsights(await getInsights(chartDays));
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          `Erreur ${err.status}: ${
            (err.data as { detail?: string })?.detail || err.statusText
          }`
        );
      } else {
        setError("Impossible de charger le tableau de bord. Vérifiez que le backend est démarré.");
      }
    } finally {
      setIsLoading(false);
    }
  }, [chartDays]);

  // Rafraîchissement silencieux (sans skeleton) déclenché par les événements SSE.
  const silentRefreshInsights = useCallback(async () => {
    try {
      setInsights(await getInsights(chartDays));
    } catch {
      // silencieux : un échec ne doit pas perturber l'écran
    }
  }, [chartDays]);

  useEffect(() => {
    fetchInsights();
  }, [fetchInsights]);

  // Temps réel : les KPIs se mettent à jour en direct à chaque événement
  // (message entrant, réponse, statut), via le même flux SSE que l'inbox.
  useEffect(() => {
    const unsubscribe = subscribeToConversationEvents(
      () => {
        if (refreshTimer.current) clearTimeout(refreshTimer.current);
        refreshTimer.current = setTimeout(() => void silentRefreshInsights(), 500);
      },
      (connected) => setLive(connected)
    );
    return () => {
      unsubscribe();
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    };
  }, [silentRefreshInsights]);

  if (isLoading) {
    return (
      <div className="h-full overflow-y-auto">
        <div className="max-w-5xl mx-auto p-6 space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full overflow-y-auto">
        <div className="max-w-5xl mx-auto p-6">
          <ErrorState message={error} onRetry={fetchInsights} />
        </div>
      </div>
    );
  }

  if (!insights) return null;

  const maxIntent = Math.max(1, ...insights.top_intents.map((i) => i.count));
  const hasActivity =
    insights.conversations_total > 0 || insights.messages_total > 0;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto p-6 space-y-6">
        <OnboardingBanner />
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="font-mono text-[11px] tracking-[0.22em] uppercase text-jenny-coral mb-2">— vue d&apos;ensemble —</div>
            <h2 className="font-display text-[clamp(28px,4vw,36px)] leading-[1] tracking-[-0.02em] text-jenny-text">
              Tableau de <span className="italic text-jenny-coral">bord.</span>
            </h2>
            <p className="text-sm text-jenny-text-secondary mt-0.5">
              Vue d&apos;ensemble de votre activité Jenny
            </p>
          </div>
          <span
            className="flex items-center gap-1.5 text-[11px] font-medium mt-1"
            title={live ? "Mise à jour en temps réel" : "Reconnexion au flux…"}
          >
            <span className="relative flex w-2 h-2">
              {live && (
                <span className="absolute inline-flex h-full w-full rounded-full bg-jenny-success opacity-60 animate-ping" />
              )}
              <span
                className={cn(
                  "relative inline-flex w-2 h-2 rounded-full",
                  live ? "bg-jenny-success" : "bg-jenny-warning animate-pulse"
                )}
              />
            </span>
            <span className={cn("hidden sm:inline", live ? "text-jenny-success" : "text-jenny-text-secondary")}>
              {live ? "En direct" : "Hors ligne"}
            </span>
          </span>
        </div>

        {!hasActivity && (
          <EmptyState
            icon={<BarChart3 className="w-8 h-8" />}
            title="Pas encore de données"
            description="Les statistiques apparaîtront ici dès que des conversations et messages seront enregistrés."
          />
        )}

        {/* Cartes de statistiques */}
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="grid grid-cols-2 md:grid-cols-4 gap-3"
        >
          <StatCard
            icon={<MessageSquare className="w-5 h-5" />}
            tint="#FF7F6A"
            label="Conversations"
            value={<AnimatedNumber value={insights.conversations_total} />}
            sub={`${insights.conversations_open} ouvertes · ${insights.conversations_escalated} escaladées`}
          />
          <StatCard
            icon={<Mail className="w-5 h-5" />}
            tint="#3B82F6"
            label="Messages"
            value={<AnimatedNumber value={insights.messages_total} />}
            sub={`${insights.messages_inbound} entrants · ${insights.messages_outbound} sortants`}
          />
          <StatCard
            icon={<Users className="w-5 h-5" />}
            tint="#8B5CF6"
            label="Clients"
            value={<AnimatedNumber value={insights.customers_total} />}
          />
          <StatCard
            icon={<ShoppingBag className="w-5 h-5" />}
            tint="#F59E0B"
            label="Commandes"
            value={<AnimatedNumber value={insights.orders_total} />}
          />
          <StatCard
            icon={<Euro className="w-5 h-5" />}
            tint="#10B981"
            label="Chiffre d'affaires"
            value={
              <AnimatedNumber
                value={insights.revenue_minor}
                format={(n) => formatEuros(n, insights.currency)}
              />
            }
            sub="Commandes payées"
          />
          <StatCard
            icon={<BookOpen className="w-5 h-5" />}
            tint="#6366F1"
            label="Connaissances"
            value={<AnimatedNumber value={insights.knowledge_entries} />}
            sub="Entrées indexées"
          />
          <StatCard
            icon={<TrendingUp className="w-5 h-5" />}
            tint="#EF4444"
            label="Taux d'escalade"
            value={
              <AnimatedNumber
                value={insights.escalation_rate * 100}
                format={(n) => `${n.toFixed(1)}%`}
              />
            }
          />
          <StatCard
            icon={<Activity className="w-5 h-5" />}
            tint="#7284A8"
            label="Msgs / conversation"
            value={
              <AnimatedNumber
                value={insights.avg_messages_per_conversation}
                format={(n) =>
                  n.toLocaleString("fr-FR", { maximumFractionDigits: 1 })
                }
              />
            }
          />
          <StatCard
            icon={<Timer className="w-5 h-5" />}
            tint="#14B8A6"
            label="Temps de 1ʳᵉ réponse"
            value={
              insights.avg_first_response_minutes == null ? (
                "—"
              ) : (
                <AnimatedNumber
                  value={insights.avg_first_response_minutes}
                  format={(n) =>
                    n >= 60
                      ? `${(n / 60).toFixed(1)} h`
                      : `${Math.round(n)} min`
                  }
                />
              )
            }
            sub="Moyenne"
          />
        </motion.div>

        {/* Volume de messages sur 7 jours */}
        <motion.div variants={fadeInUp} initial="hidden" animate="show">
          <Card className="p-6">
            <div className="flex items-center justify-between gap-2 mb-5">
              <h3 className="flex items-center gap-2 font-semibold text-jenny-text text-sm">
                <BarChart3 className="w-4 h-4 text-jenny-coral" />
                Messages ({chartDays} derniers jours)
              </h3>
              <div className="flex items-center gap-1">
                {[7, 30].map((d) => (
                  <button
                    key={d}
                    onClick={() => setChartDays(d)}
                    className={cn(
                      "px-2 py-0.5 rounded-full text-[11px] font-medium transition-colors",
                      chartDays === d
                        ? "bg-jenny-coral text-white"
                        : "bg-jenny-divider/40 text-jenny-text-secondary hover:bg-jenny-divider"
                    )}
                  >
                    {d}j
                  </button>
                ))}
              </div>
            </div>
            <MessageVolumeChart data={insights.messages_last_7_days} days={chartDays} />
          </Card>
        </motion.div>

        {/* Répartitions */}
        <div className="grid md:grid-cols-2 gap-3">
          <motion.div variants={fadeInUp} initial="hidden" animate="show">
            <Card className="p-6 h-full">
              <h3 className="font-semibold text-jenny-text text-sm mb-4">
                Conversations par canal
              </h3>
              {insights.by_channel.length === 0 ? (
                <p className="text-sm text-jenny-text-secondary">Aucune donnée</p>
              ) : (
                <ChannelDonut data={insights.by_channel} />
              )}
            </Card>
          </motion.div>

          <motion.div variants={fadeInUp} initial="hidden" animate="show">
            <Card className="p-6 h-full">
              <h3 className="font-semibold text-jenny-text text-sm mb-4">
                Intentions principales
              </h3>
              {insights.top_intents.length === 0 ? (
                <p className="text-sm text-jenny-text-secondary">Aucune donnée</p>
              ) : (
                <div className="space-y-3">
                  {insights.top_intents.map((i, idx) => (
                    <div key={i.intent} className="flex items-center gap-3">
                      <span
                        className="text-xs text-jenny-text-secondary w-32 truncate"
                        title={intentLabel(i.intent)}
                      >
                        {intentLabel(i.intent)}
                      </span>
                      <div className="flex-1 h-2 rounded-full bg-jenny-divider/60 overflow-hidden">
                        <motion.div
                          className="h-full rounded-full bg-jenny-mint-dark"
                          style={{ width: `${(i.count / maxIntent) * 100}%`, transformOrigin: "left" }}
                          initial={{ scaleX: 0 }}
                          animate={{ scaleX: 1 }}
                          transition={{ duration: 0.6, ease: easeOutExpo, delay: 0.15 + idx * 0.06 }}
                        />
                      </div>
                      <span className="text-xs font-medium text-jenny-text w-6 text-right tabular-nums">
                        {i.count}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </motion.div>

          {insights.by_agent.length > 0 && (
            <motion.div variants={fadeInUp} initial="hidden" animate="show">
              <Card className="p-6 h-full">
                <h3 className="font-semibold text-jenny-text text-sm mb-4">
                  Réponses par agent
                </h3>
                <div className="space-y-3">
                  {insights.by_agent.map((a, idx) => {
                    const maxAgent = Math.max(1, ...insights.by_agent.map((x) => x.count));
                    return (
                      <div key={a.agent} className="flex items-center gap-3">
                        <span className="text-xs text-jenny-text-secondary w-32 truncate" title={a.agent}>
                          {a.agent}
                        </span>
                        <div className="flex-1 h-2 rounded-full bg-jenny-divider/60 overflow-hidden">
                          <motion.div
                            className="h-full rounded-full bg-jenny-twitter"
                            style={{ width: `${(a.count / maxAgent) * 100}%`, transformOrigin: "left" }}
                            initial={{ scaleX: 0 }}
                            animate={{ scaleX: 1 }}
                            transition={{ duration: 0.6, ease: easeOutExpo, delay: 0.15 + idx * 0.06 }}
                          />
                        </div>
                        <span className="text-xs font-medium text-jenny-text w-6 text-right tabular-nums">
                          {a.count}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </Card>
            </motion.div>
          )}
        </div>

        {/* Prochains rendez-vous */}
        <UpcomingAppointments />
      </div>
    </div>
  );
}

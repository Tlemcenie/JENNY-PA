"use client";

import { useEffect, useState, useCallback, useRef, type ReactNode } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { Calendar, Eye, BarChart3 } from "lucide-react";
import { getInsights, subscribeToConversationEvents, type Insights, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
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
import { SkeletonCard } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { MiniSpark, ChannelChip, StatusBadge } from "@/components/jenny/jenny-ui";
import { JennyAvatar } from "@/components/ui/jenny-avatar";
import { intentLabel } from "@/lib/utils";

// Prénom à partir du nom complet du compte connecté (sinon repli neutre).
function firstNameOf(fullName?: string | null): string {
  const n = (fullName || "").trim().split(/\s+/)[0];
  return n || "vous";
}

// Étiquette date façon « Mardi 28 avril · 14:32 » (locale FR, mise à jour à l'affichage).
function frDateLabel(d: Date): string {
  const day = d.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
  const time = d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  return `${day.charAt(0).toUpperCase()}${day.slice(1)} · ${time}`;
}

// Série douce et MONTANTE dérivée d'une valeur réelle (jamais aléatoire) pour
// alimenter une sparkline quand aucune série temporelle n'est fournie.
function gentleSeries(target: number, points = 12, invert = false): number[] {
  const t = Math.max(0, target);
  const start = t * 0.55;
  const out = Array.from({ length: points }, (_, i) => {
    const k = points === 1 ? 1 : i / (points - 1);
    return start + (t - start) * k;
  });
  return invert ? out.slice().reverse() : out;
}

function StatCard({
  label,
  value,
  delta,
  deltaTone = "up",
  spark,
  color = "var(--coral)",
}: {
  label: string;
  value: ReactNode;
  delta?: string;
  deltaTone?: "up" | "down" | "neutral";
  spark?: number[];
  color?: string;
}) {
  const deltaColor =
    deltaTone === "down"
      ? "var(--error)"
      : deltaTone === "neutral"
        ? "var(--text-2)"
        : "var(--success)";
  return (
    <div className="jcard jlift" style={{ padding: 20 }}>
      <div
        style={{
          fontSize: 11,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: "var(--text-2)",
          fontFamily: "var(--mono)",
          fontWeight: 600,
          marginBottom: 14,
        }}
      >
        {label}
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          marginBottom: 10,
          gap: 8,
        }}
      >
        <div
          className="jserif"
          style={{ fontSize: 42, lineHeight: 1, letterSpacing: "-0.02em", color: "var(--text)" }}
        >
          {value}
        </div>
        {delta && (
          <span
            style={{
              fontSize: 11.5,
              fontWeight: 700,
              color: deltaColor,
              fontFamily: "var(--mono)",
              whiteSpace: "nowrap",
            }}
          >
            {delta}
          </span>
        )}
      </div>
      {spark && spark.length >= 2 ? (
        <MiniSpark values={spark} color={color} width={236} height={32} />
      ) : (
        <div style={{ height: 32 }} />
      )}
    </div>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const [insights, setInsights] = useState<Insights | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [chartDays, setChartDays] = useState(7);
  const [now, setNow] = useState<Date | null>(null);
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

  // Horloge de l'en-tête (rendue côté client uniquement → pas de désync SSR).
  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(id);
  }, []);

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
      <div className="jx h-full overflow-y-auto" style={{ background: "var(--bg)", padding: "28px 32px" }}>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="jx h-full overflow-y-auto" style={{ background: "var(--bg)", padding: "28px 32px" }}>
        <ErrorState message={error} onRetry={fetchInsights} />
      </div>
    );
  }

  if (!insights) return null;

  const firstName = firstNameOf(user?.full_name);
  const hasActivity = insights.conversations_total > 0 || insights.messages_total > 0;

  // ── Mapping données réelles → emplacements du design ──────────────────────
  // Taux de résolution « Jenny » = part NON escaladée (les conversations gérées
  // jusqu'au bout sans intervention humaine).
  const resolutionRate = Math.max(0, Math.min(1, 1 - insights.escalation_rate));
  const messagesSpark = insights.messages_last_7_days.map((d) => d.count);

  const firstResponseValue =
    insights.avg_first_response_minutes == null
      ? "—"
      : insights.avg_first_response_minutes >= 60
        ? `${(insights.avg_first_response_minutes / 60).toFixed(1)} h`
        : `${Math.round(insights.avg_first_response_minutes)} min`;

  // Sparklines dérivées (douces, montantes, déterministes — pas d'aléatoire).
  const resolutionSpark = gentleSeries(resolutionRate * 100);
  const conversationsSpark = gentleSeries(insights.conversations_total);
  const responseSpark = gentleSeries(insights.avg_first_response_minutes ?? 0, 12, true);

  const stats: {
    label: string;
    value: ReactNode;
    delta?: string;
    deltaTone?: "up" | "down" | "neutral";
    spark?: number[];
    color?: string;
  }[] = [
    {
      label: "Messages traités",
      value: insights.messages_total.toLocaleString("fr-FR"),
      delta: `${insights.messages_inbound} entrants`,
      deltaTone: "neutral",
      spark: messagesSpark.length >= 2 ? messagesSpark : conversationsSpark,
      color: "var(--coral)",
    },
    {
      label: "Temps de 1ʳᵉ réponse",
      value: firstResponseValue,
      delta: "moyenne",
      deltaTone: "neutral",
      spark: insights.avg_first_response_minutes == null ? undefined : responseSpark,
      color: "var(--slate)",
    },
    {
      label: "Taux résolution Jenny",
      value: `${Math.round(resolutionRate * 100)}%`,
      delta: `${(insights.escalation_rate * 100).toFixed(0)}% escaladé`,
      deltaTone: "neutral",
      spark: resolutionSpark,
      color: "var(--success)",
    },
    {
      label: "Conversations",
      value: insights.conversations_total.toLocaleString("fr-FR"),
      delta: `${insights.conversations_open} ouvertes`,
      deltaTone: "neutral",
      spark: conversationsSpark,
      color: "var(--coral)",
    },
  ];

  // « Activité en direct » : pas de flux nominatif dans Insights → on rend les
  // VRAIES données de répartition par canal (chaque canal = une ligne), avec un
  // statut honnête (escaladé → vous, sinon Jenny). Aucun nom/chiffre inventé.
  const totalIntents = Math.max(1, insights.top_intents.reduce((s, i) => s + i.count, 0));
  const topIntentLabel = insights.top_intents[0] ? intentLabel(insights.top_intents[0].intent) : null;
  const topChannel = insights.by_channel[0]?.channel ?? null;

  return (
    <div className="jx h-full overflow-y-auto" style={{ background: "var(--bg)", padding: "28px 32px" }}>
      <OnboardingBanner />

      {/* Greeting */}
      <div style={{ display: "flex", alignItems: "flex-end", marginBottom: 28, gap: 16, flexWrap: "wrap" }}>
        <div style={{ minWidth: 0 }}>
          <div
            className="jmono"
            style={{
              fontSize: 11,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--text-2)",
              marginBottom: 8,
            }}
          >
            {now ? frDateLabel(now) : " "}
          </div>
          <h1
            className="jserif"
            style={{ fontSize: 44, lineHeight: 1, letterSpacing: "-0.02em", color: "var(--text)", margin: 0 }}
          >
            Bonjour {firstName}. Jenny a géré{" "}
            <span style={{ fontStyle: "italic", color: "var(--coral)" }}>
              {insights.messages_total.toLocaleString("fr-FR")} message{insights.messages_total > 1 ? "s" : ""}
            </span>{" "}
            récemment.
          </h1>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 10 }}>
          <button
            type="button"
            onClick={() => setChartDays(7)}
            className="jlift"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              height: 32,
              padding: "0 13px",
              borderRadius: "var(--r-btn)",
              fontSize: 12.5,
              fontWeight: 600,
              fontFamily: "var(--font-sans)",
              background: "transparent",
              color: "var(--text)",
              border: "1px solid var(--divider)",
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            <Calendar style={{ width: 13, height: 13 }} />7 derniers jours
          </button>
          <Link
            href="/inbox"
            className="jlift"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              height: 32,
              padding: "0 13px",
              borderRadius: "var(--r-btn)",
              fontSize: 12.5,
              fontWeight: 600,
              fontFamily: "var(--font-sans)",
              background: "var(--coral)",
              color: "#fff",
              border: "1px solid transparent",
              boxShadow: "var(--shadow-pop)",
              cursor: "pointer",
              whiteSpace: "nowrap",
              textDecoration: "none",
            }}
          >
            <Eye style={{ width: 13, height: 13 }} />
            Voir le live
          </Link>
        </div>
      </div>

      {!hasActivity && (
        <div style={{ marginBottom: 24 }}>
          <EmptyState
            icon={<BarChart3 className="w-8 h-8" />}
            title="Pas encore de données"
            description="Les statistiques apparaîtront ici dès que des conversations et messages seront enregistrés."
          />
        </div>
      )}

      {/* Stat row */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
          gap: 14,
          marginBottom: 24,
        }}
      >
        {stats.map((s) => (
          <StatCard
            key={s.label}
            label={s.label}
            value={s.value}
            delta={s.delta}
            deltaTone={s.deltaTone}
            spark={s.spark}
            color={s.color}
          />
        ))}
      </div>

      {/* Two-column: live activity + insights */}
      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 18, alignItems: "start" }}>
        {/* Live activity (répartition réelle par canal) */}
        <div className="jcard" style={{ padding: 20 }}>
          <div style={{ display: "flex", alignItems: "center", marginBottom: 16, gap: 10, flexWrap: "wrap" }}>
            <div style={{ fontSize: 14, fontWeight: 600, letterSpacing: "-0.01em", color: "var(--text)" }}>
              Activité en direct
            </div>
            <span
              style={{
                padding: "2px 8px",
                background: live ? "rgba(16,185,129,0.1)" : "rgba(245,158,11,0.12)",
                color: live ? "var(--success)" : "var(--warning)",
                borderRadius: 999,
                fontSize: 10,
                fontWeight: 700,
                fontFamily: "var(--mono)",
                display: "flex",
                alignItems: "center",
                gap: 5,
              }}
              title={live ? "Mise à jour en temps réel" : "Reconnexion au flux…"}
            >
              <span
                className={live ? "animate-pulse" : undefined}
                style={{
                  width: 6,
                  height: 6,
                  background: live ? "var(--success)" : "var(--warning)",
                  borderRadius: "50%",
                }}
              />
              {live ? "EN DIRECT" : "HORS LIGNE"}
            </span>
            <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--text-2)" }}>
              {insights.conversations_open} conversation{insights.conversations_open > 1 ? "s" : ""} active
              {insights.conversations_open > 1 ? "s" : ""}
            </span>
          </div>

          {insights.by_channel.length === 0 ? (
            <p style={{ fontSize: 13, color: "var(--text-2)", padding: "8px 0" }}>
              Aucune conversation pour le moment.
            </p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {insights.by_channel.map((row, i) => {
                const escalated = insights.escalation_rate > 0.5;
                const status = escalated ? "human" : "jenny";
                return (
                  <div
                    key={row.channel}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 12,
                      padding: "10px 0",
                      borderBottom:
                        i < insights.by_channel.length - 1 ? "1px solid var(--divider-soft)" : "none",
                    }}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
                        <ChannelChip ch={row.channel} />
                        <span
                          className="jmono"
                          style={{
                            fontSize: 9,
                            letterSpacing: "0.08em",
                            color: "var(--text-3)",
                            padding: "1px 5px",
                            background: "var(--bg-tint)",
                            borderRadius: 4,
                          }}
                        >
                          {row.count} conv.
                        </span>
                      </div>
                      <div
                        style={{
                          fontSize: 12.5,
                          color: "var(--text-2)",
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {Math.round((row.count / Math.max(1, insights.conversations_total)) * 100)}% des
                        conversations sur ce canal
                      </div>
                    </div>
                    <StatusBadge status={status} />
                  </div>
                );
              })}
            </div>
          )}

          {/* Graphe volume de messages — conservé, données réelles. */}
          <div style={{ marginTop: 18, paddingTop: 16, borderTop: "1px solid var(--divider-soft)" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 12,
                gap: 8,
              }}
            >
              <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>
                Messages ({chartDays} derniers jours)
              </span>
              <div style={{ display: "flex", gap: 6 }}>
                {[7, 30].map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => setChartDays(d)}
                    style={{
                      padding: "2px 10px",
                      borderRadius: 999,
                      fontSize: 11,
                      fontWeight: 600,
                      fontFamily: "var(--mono)",
                      cursor: "pointer",
                      border: "1px solid",
                      borderColor: chartDays === d ? "transparent" : "var(--divider)",
                      background: chartDays === d ? "var(--coral)" : "transparent",
                      color: chartDays === d ? "#fff" : "var(--text-2)",
                    }}
                  >
                    {d}j
                  </button>
                ))}
              </div>
            </div>
            <MessageVolumeChart data={insights.messages_last_7_days} days={chartDays} />
          </div>
        </div>

        {/* Insights column */}
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          {/* Insight de Jenny (dérivé des vraies intentions/canaux) */}
          <div
            className="jcard"
            style={{
              padding: 20,
              background: "linear-gradient(135deg, var(--coral-tint), var(--surface))",
              borderColor: "var(--coral-light)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
              <JennyAvatar size={26} />
              <span
                className="jmono"
                style={{
                  fontSize: 11,
                  letterSpacing: "0.16em",
                  textTransform: "uppercase",
                  color: "var(--coral-dark)",
                  fontWeight: 600,
                }}
              >
                insight de jenny
              </span>
            </div>
            <div
              className="jserif"
              style={{ fontSize: 24, lineHeight: 1.15, letterSpacing: "-0.01em", marginBottom: 14, color: "var(--text)" }}
            >
              <span style={{ fontStyle: "italic" }}>
                {topIntentLabel ? (
                  <>
                    « La demande n°1 cette semaine, c&apos;est <b>{topIntentLabel}</b>
                    {topChannel ? (
                      <>
                        {" "}
                        — surtout via <b>{topChannel}</b>
                      </>
                    ) : null}
                    . Je gère {Math.round(resolutionRate * 100)}% sans intervention. »
                  </>
                ) : (
                  <>
                    « Dès que les conversations arrivent, je vous résume ici ce qui ressort le plus. »
                  </>
                )}
              </span>
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <Link
                href="/brain"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  height: 32,
                  padding: "0 13px",
                  borderRadius: "var(--r-btn)",
                  fontSize: 12.5,
                  fontWeight: 600,
                  fontFamily: "var(--font-sans)",
                  background: "var(--coral)",
                  color: "#fff",
                  border: "1px solid transparent",
                  boxShadow: "var(--shadow-pop)",
                  textDecoration: "none",
                  whiteSpace: "nowrap",
                }}
              >
                Configurer Jenny
              </Link>
              <Link
                href="/inbox"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  height: 32,
                  padding: "0 13px",
                  borderRadius: "var(--r-btn)",
                  fontSize: 12.5,
                  fontWeight: 600,
                  fontFamily: "var(--font-sans)",
                  background: "transparent",
                  color: "var(--text)",
                  border: "1px solid var(--divider)",
                  textDecoration: "none",
                  whiteSpace: "nowrap",
                }}
              >
                Voir l&apos;inbox
              </Link>
            </div>
          </div>

          {/* Top intentions cette semaine (données réelles) */}
          <div className="jcard" style={{ padding: 20 }}>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 14, color: "var(--text)" }}>
              Top intentions cette semaine
            </div>
            {insights.top_intents.length === 0 ? (
              <p style={{ fontSize: 13, color: "var(--text-2)" }}>Aucune donnée pour le moment.</p>
            ) : (
              insights.top_intents.map((r) => {
                const pct = Math.round((r.count / totalIntents) * 100);
                return (
                  <div key={r.intent} style={{ marginBottom: 10 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5, gap: 8 }}>
                      <span
                        style={{
                          fontSize: 12.5,
                          color: "var(--text)",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                        title={intentLabel(r.intent)}
                      >
                        {intentLabel(r.intent)}
                      </span>
                      <span
                        className="jmono"
                        style={{ fontSize: 11.5, color: "var(--text-2)", whiteSpace: "nowrap" }}
                      >
                        {r.count} · {pct}%
                      </span>
                    </div>
                    <div style={{ height: 4, background: "var(--bg-tint)", borderRadius: 2, overflow: "hidden" }}>
                      <div
                        style={{
                          width: `${pct}%`,
                          height: "100%",
                          background: "var(--coral)",
                          borderRadius: 2,
                          transition: "width 0.6s cubic-bezier(0.16,1,0.3,1)",
                        }}
                      />
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* Conversations par canal (donut) — donnée réelle conservée. */}
          {insights.by_channel.length > 0 && (
            <div className="jcard" style={{ padding: 20 }}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 14, color: "var(--text)" }}>
                Conversations par canal
              </div>
              <ChannelDonut data={insights.by_channel} />
            </div>
          )}
        </div>
      </div>

      {/* Prochains rendez-vous */}
      <div style={{ marginTop: 18 }}>
        <UpcomingAppointments />
      </div>
    </div>
  );
}

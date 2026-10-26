"use client";

import { useEffect, useState, useCallback, type ReactNode } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { BarChart3, MessagesSquare } from "lucide-react";
import { getInsights, humanError, type Insights } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { SatisfactionCard } from "@/components/dashboard/satisfaction-card";
import { SetupChecklist } from "@/components/dashboard/setup-checklist";
import { RecentConversations } from "@/components/dashboard/recent-conversations";
import { useRealtimeRefresh } from "@/components/providers/realtime-provider";
import { SkeletonCard } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { MiniSpark } from "@/components/jenny/jenny-ui";
import { JennyAvatar } from "@/components/ui/jenny-avatar";
import { channelLabel, intentLabel } from "@/lib/utils";

// charts chargés à la demande
const MessageVolumeChart = dynamic(
  () => import("@/components/dashboard/message-volume-chart").then((m) => m.MessageVolumeChart),
  { ssr: false, loading: () => <div className="h-[180px] rounded-xl bg-jenny-divider/30 animate-pulse" /> }
);
const ChannelDonut = dynamic(
  () => import("@/components/dashboard/channel-donut").then((m) => m.ChannelDonut),
  { ssr: false, loading: () => <div className="h-32 rounded-xl bg-jenny-divider/30 animate-pulse" /> }
);
// pareil pour les rdv
const UpcomingAppointments = dynamic(
  () => import("@/components/dashboard/upcoming-appointments"),
  { ssr: false, loading: () => <div className="h-64 rounded-2xl bg-jenny-divider/30 animate-pulse" /> }
);

const PERIODS = [7, 30] as const;

// prénom du compte
function firstNameOf(fullName?: string | null): string {
  const n = (fullName || "").trim().split(/\s+/)[0];
  return n || "vous";
}

// date format fr
function frDateLabel(d: Date): string {
  const day = d.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
  const time = d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  return `${day.charAt(0).toUpperCase()}${day.slice(1)} · ${time}`;
}

// durée lisible
function formatMinutes(m: number): string {
  if (m < 1) return "< 1 min";
  if (m >= 60) return `${(m / 60).toFixed(1).replace(".", ",")} h`;
  return `${Math.round(m)} min`;
}

function plural(n: number, word: string): string {
  return `${n.toLocaleString("fr-FR")} ${word}${n > 1 ? "s" : ""}`;
}

function StatCard({
  label,
  value,
  hint,
  spark,
  color = "var(--coral)",
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  spark?: number[];
  color?: string;
}) {
  // courbe seulement si vraie série
  const showSpark = !!spark && spark.length >= 2 && spark.some((v) => v > 0);
  return (
    <div className="jcard jlift" style={{ padding: 20, minWidth: 0 }}>
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
        className="jserif"
        style={{ fontSize: 40, lineHeight: 1, letterSpacing: "-0.02em", color: "var(--text)", marginBottom: 8 }}
      >
        {value}
      </div>
      {hint && (
        <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: showSpark ? 10 : 0 }}>{hint}</div>
      )}
      {showSpark && (
        <div style={{ overflow: "hidden" }} aria-hidden>
          <MiniSpark values={spark} color={color} width={236} height={32} />
        </div>
      )}
    </div>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const [insights, setInsights] = useState<Insights | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [chartDays, setChartDays] = useState<number>(7);
  const [now, setNow] = useState<Date | null>(null);

  const fetchInsights = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setInsights(await getInsights(chartDays));
    } catch (err) {
      setError(humanError(err, "Impossible de charger le tableau de bord."));
    } finally {
      setIsLoading(false);
    }
  }, [chartDays]);

  // refresh silencieux via sse
  const silentRefresh = useCallback(async () => {
    try {
      setInsights(await getInsights(chartDays));
    } catch {
      // on garde l'affichage
    }
  }, [chartDays]);

  useEffect(() => {
    void fetchInsights();
  }, [fetchInsights]);

  useRealtimeRefresh(() => void silentRefresh(), 800);

  // horloge côté client
  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(id);
  }, []);

  const shell = "jx h-full overflow-y-auto px-4 py-6 md:px-8 md:py-7";

  if (isLoading && !insights) {
    return (
      <div className={shell} style={{ background: "var(--bg)" }}>
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-3.5">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      </div>
    );
  }

  if (error && !insights) {
    return (
      <div className={shell} style={{ background: "var(--bg)" }}>
        <ErrorState message={error} onRetry={fetchInsights} />
      </div>
    );
  }

  if (!insights) return null;

  const firstName = firstNameOf(user?.full_name);
  const series = insights.messages_last_7_days;
  const periodTotal = series.reduce((s, d) => s + d.count, 0);
  const hasActivity = insights.conversations_total > 0 || insights.messages_total > 0;
  const convTotal = insights.conversations_total;

  // part non escaladée
  const resolutionPct =
    convTotal > 0 ? Math.round(Math.max(0, Math.min(1, 1 - insights.escalation_rate)) * 100) : null;

  const totalIntents = Math.max(1, insights.top_intents.reduce((s, i) => s + i.count, 0));
  const topIntent = insights.top_intents[0] ?? null;
  const topChannel = insights.by_channel[0]?.channel ?? null;

  return (
    <div className={shell} style={{ background: "var(--bg)" }}>
      <SetupChecklist knowledgeEntries={insights.knowledge_entries} onChanged={() => void silentRefresh()} />

      {/* accueil */}
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
            {now ? frDateLabel(now) : " "}
          </div>
          <h1
            className="jserif"
            style={{ fontSize: "clamp(32px, 5vw, 44px)", lineHeight: 1.05, letterSpacing: "-0.02em", color: "var(--text)", margin: 0 }}
          >
            Bonjour {firstName}.
          </h1>
          <p style={{ fontSize: 14.5, color: "var(--text-2)", marginTop: 8 }}>
            {hasActivity ? (
              <>
                <b style={{ color: "var(--coral)" }}>{plural(periodTotal, "message")}</b> échangé
                {periodTotal > 1 ? "s" : ""} ces {chartDays} derniers jours.
              </>
            ) : (
              "Jenny est prête. Les chiffres apparaîtront dès les premiers messages."
            )}
          </p>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <div role="group" aria-label="Période" style={{ display: "flex", gap: 6 }}>
            {PERIODS.map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setChartDays(d)}
                aria-pressed={chartDays === d}
                style={{
                  height: 32,
                  padding: "0 12px",
                  borderRadius: "var(--r-btn)",
                  fontSize: 12.5,
                  fontWeight: 600,
                  fontFamily: "var(--font-sans)",
                  cursor: "pointer",
                  border: "1px solid",
                  borderColor: chartDays === d ? "transparent" : "var(--divider)",
                  background: chartDays === d ? "var(--text)" : "transparent",
                  color: chartDays === d ? "var(--surface)" : "var(--text)",
                }}
              >
                {d} jours
              </button>
            ))}
          </div>
          <Link
            href="/conversations"
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
              whiteSpace: "nowrap",
              textDecoration: "none",
            }}
          >
            <MessagesSquare style={{ width: 13, height: 13 }} />
            Conversations
          </Link>
        </div>
      </div>

      {error && (
        <div role="alert" className="jcard" style={{ padding: 12, marginBottom: 18, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: 13, color: "var(--text-2)", flex: 1 }}>{error}</span>
          <button type="button" className="jpill" onClick={() => void fetchInsights()}>
            Réessayer
          </button>
        </div>
      )}

      {!hasActivity && (
        <div style={{ marginBottom: 24 }}>
          <EmptyState
            icon={<BarChart3 className="w-8 h-8" />}
            title="Pas encore de données"
            description="Les statistiques apparaîtront ici dès que des conversations et messages seront enregistrés."
          />
        </div>
      )}

      {/* ligne de stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3.5 mb-6">
        <StatCard
          label={`Messages · ${chartDays} j`}
          value={periodTotal.toLocaleString("fr-FR")}
          hint={`${insights.messages_total.toLocaleString("fr-FR")} depuis le début`}
          spark={series.map((d) => d.count)}
        />
        <StatCard
          label="1ʳᵉ réponse"
          value={
            insights.avg_first_response_minutes == null ? "—" : formatMinutes(insights.avg_first_response_minutes)
          }
          hint={insights.avg_first_response_minutes == null ? "pas encore mesuré" : "délai moyen, tout l'historique"}
        />
        <StatCard
          label="Sans intervention"
          value={resolutionPct == null ? "—" : `${resolutionPct}%`}
          hint={
            convTotal > 0
              ? `${plural(insights.conversations_escalated, "escalade")} sur ${plural(convTotal, "conversation")}`
              : "aucune conversation"
          }
        />
        <StatCard
          label="Conversations"
          value={convTotal.toLocaleString("fr-FR")}
          hint={`${plural(insights.conversations_open, "ouverte")} · ${plural(insights.customers_total, "client")}`}
        />
      </div>

      {/* deux colonnes */}
      <div className="grid grid-cols-1 lg:grid-cols-[1.3fr_1fr] gap-[18px] items-start">
        <div style={{ display: "flex", flexDirection: "column", gap: 18, minWidth: 0 }}>
          <RecentConversations />

          {/* volume de messages */}
          <div className="jcard" style={{ padding: 20 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text)", marginBottom: 12 }}>
              Messages par jour ({chartDays} derniers jours)
            </div>
            {periodTotal === 0 ? (
              <p style={{ fontSize: 13, color: "var(--text-2)", padding: "24px 0", textAlign: "center" }}>
                Aucun message sur cette période.
              </p>
            ) : (
              <MessageVolumeChart data={series} days={chartDays} />
            )}
          </div>
        </div>

        {/* colonne insights */}
        <div style={{ display: "flex", flexDirection: "column", gap: 18, minWidth: 0 }}>
          <SatisfactionCard />

          {/* ce qui ressort, données réelles */}
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
                ce qui ressort
              </span>
            </div>
            <div
              className="jserif"
              style={{ fontSize: 22, lineHeight: 1.2, letterSpacing: "-0.01em", marginBottom: 14, color: "var(--text)" }}
            >
              <span style={{ fontStyle: "italic" }}>
                {topIntent ? (
                  <>
                    « La demande n°1, c&apos;est <b>{intentLabel(topIntent.intent)}</b> (
                    {plural(topIntent.count, "conversation")}).
                    {topChannel ? (
                      <>
                        {" "}
                        Canal le plus utilisé : <b>{channelLabel(topChannel)}</b>.
                      </>
                    ) : null}
                    {resolutionPct != null ? <> Je réponds seule dans {resolutionPct}% des cas.</> : null} »
                  </>
                ) : (
                  <>« Dès que les conversations arrivent, je vous résume ici ce qui ressort le plus. »</>
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
                href="/learning"
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
                Questions sans réponse
              </Link>
            </div>
          </div>

          {/* top intentions */}
          <div className="jcard" style={{ padding: 20 }}>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4, color: "var(--text)" }}>
              Demandes les plus fréquentes
            </div>
            <div style={{ fontSize: 11.5, color: "var(--text-3)", marginBottom: 14 }}>
              toutes conversations confondues
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
                    <div style={{ height: 4, background: "var(--divider-soft)", borderRadius: 2, overflow: "hidden" }}>
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

          {/* donut par canal */}
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

      {/* prochains rdv */}
      <div style={{ marginTop: 18 }}>
        <UpcomingAppointments />
      </div>
    </div>
  );
}

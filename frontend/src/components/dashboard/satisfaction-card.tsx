"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ThumbsUp, ThumbsDown, Gauge, TrendingUp, GraduationCap } from "lucide-react";
import { getFeedbackMetrics, type FeedbackMetrics } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { AnimatedNumber } from "@/components/ui/animated-number";
import { truncate } from "@/lib/utils";

/**
 * Métriques de satisfaction des réponses de Jenny (issues des 👍/👎 laissés
 * par les utilisateurs). Auto-chargeante : à déposer sur n'importe quelle page.
 */
const PERIODS: { label: string; days: number }[] = [
  { label: "7 j", days: 7 },
  { label: "30 j", days: 30 },
  { label: "Tout", days: 0 },
];

export function SatisfactionCard({ className }: { className?: string }) {
  const [data, setData] = useState<FeedbackMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(0); // 0 = tout l'historique (par défaut)

  useEffect(() => {
    let alive = true;
    setLoading(true);
    getFeedbackMetrics(days)
      .then((m) => alive && setData(m))
      .catch(() => {}) // data reste null → état « indisponible »
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [days]);

  if (loading && !data) {
    return (
      <Card className={`p-6 ${className ?? ""}`}>
        <Skeleton className="h-4 w-48 mb-4" />
        <Skeleton className="h-12 w-32 mb-4" />
        <Skeleton className="h-4 w-full" />
      </Card>
    );
  }

  if (!data) {
    return (
      <Card className={`p-6 ${className ?? ""}`}>
        <div className="flex items-center gap-2" style={{ color: "var(--text-2)" }}>
          <Gauge style={{ width: 16, height: 16 }} />
          <span style={{ fontSize: 13 }}>Satisfaction des réponses indisponible.</span>
        </div>
      </Card>
    );
  }

  const { satisfaction_pct, positive, negative, total_rated, responses_total } = data;
  const coverage = responses_total > 0 ? Math.round((100 * total_rated) / responses_total) : 0;
  // Couleur de la jauge selon le niveau de satisfaction.
  const gaugeColor =
    total_rated === 0
      ? "var(--text-3)"
      : satisfaction_pct >= 75
        ? "var(--success)"
        : satisfaction_pct >= 50
          ? "var(--warning)"
          : "var(--error)";

  return (
    <Card className={`p-6 transition-opacity duration-200 ${loading ? "opacity-60" : ""} ${className ?? ""}`}>
      <div className="flex items-center justify-between gap-2 mb-4">
        <div className="flex items-center gap-2">
          <Gauge style={{ width: 16, height: 16, color: "var(--coral)" }} />
          <h3 style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text)" }}>
            Satisfaction des réponses
          </h3>
        </div>
        <div
          role="group"
          aria-label="Période"
          style={{ display: "inline-flex", gap: 2, background: "var(--bg)", border: "1px solid var(--divider)", borderRadius: 8, padding: 2 }}
        >
          {PERIODS.map((p) => {
            const active = p.days === days;
            return (
              <button
                key={p.days}
                type="button"
                onClick={() => setDays(p.days)}
                aria-pressed={active}
                className="jmono"
                style={{
                  fontSize: 10.5,
                  fontWeight: 600,
                  padding: "3px 8px",
                  borderRadius: 6,
                  border: "none",
                  cursor: "pointer",
                  color: active ? "#fff" : "var(--text-3)",
                  background: active ? "var(--coral)" : "transparent",
                  transition: "all .14s ease",
                }}
              >
                {p.label}
              </button>
            );
          })}
        </div>
      </div>

      {total_rated === 0 ? (
        <p style={{ fontSize: 13, color: "var(--text-2)", lineHeight: 1.6 }}>
          Aucune réponse évaluée pour l&apos;instant. Les 👍/👎 laissés sous les réponses de Jenny
          (dans le chat) apparaîtront ici.
        </p>
      ) : (
        <>
          {/* Score principal + barre */}
          <div className="flex items-end gap-2 mb-1">
            <span style={{ fontSize: 40, fontWeight: 700, lineHeight: 1, color: gaugeColor }}>
              <AnimatedNumber value={satisfaction_pct} format={(v) => v.toFixed(0)} />%
            </span>
            <span className="jmono" style={{ fontSize: 11, color: "var(--text-3)", paddingBottom: 6 }}>
              de réponses jugées utiles
            </span>
          </div>
          <div
            style={{
              height: 8,
              borderRadius: 999,
              background: "color-mix(in srgb, var(--error) 22%, transparent)",
              overflow: "hidden",
              marginBottom: 12,
            }}
          >
            <div
              style={{
                width: `${satisfaction_pct}%`,
                height: "100%",
                background: gaugeColor,
                borderRadius: 999,
                transition: "width .6s ease",
              }}
            />
          </div>

          {/* Tendance récente (7 derniers jours) — signal de fraîcheur. */}
          {(data.last_7_days.positive > 0 || data.last_7_days.negative > 0) && (
            <div
              className="flex items-center gap-1.5"
              style={{ fontSize: 11.5, color: "var(--text-3)", marginBottom: 16 }}
            >
              <TrendingUp style={{ width: 13, height: 13, color: "var(--text-3)" }} />
              <span>Cette semaine :</span>
              <span style={{ color: "var(--success)", fontWeight: 600 }}>
                {data.last_7_days.positive} 👍
              </span>
              <span style={{ color: "var(--error)", fontWeight: 600 }}>
                {data.last_7_days.negative} 👎
              </span>
            </div>
          )}

          {/* Détail 👍 / 👎 / couverture */}
          <div className="grid grid-cols-3 gap-3">
            <Stat icon={<ThumbsUp style={{ width: 14, height: 14, color: "var(--success)" }} />} value={positive} label="Utiles" />
            <Stat icon={<ThumbsDown style={{ width: 14, height: 14, color: "var(--error)" }} />} value={negative} label="À revoir" />
            <Stat
              icon={<Gauge style={{ width: 14, height: 14, color: "var(--text-2)" }} />}
              value={coverage}
              suffix="%"
              label="Évaluées"
              hint={`${total_rated}/${responses_total}`}
            />
          </div>

          {/* Derniers retours négatifs = pistes d'amélioration concrètes.
              On montre l'échange (question → réponse) pour savoir QUOI corriger. */}
          {data.recent_comments.length > 0 && (
            <div style={{ marginTop: 16, borderTop: "1px solid var(--divider)", paddingTop: 12 }}>
              <div
                className="jmono"
                style={{ fontSize: 10.5, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text-3)", marginBottom: 8 }}
              >
                Réponses à améliorer — derniers 👎
              </div>
              <ul style={{ display: "flex", flexDirection: "column", gap: 10, margin: 0, padding: 0, listStyle: "none" }}>
                {data.recent_comments.slice(0, 3).map((c, i) => (
                  <li
                    key={i}
                    style={{
                      fontSize: 12.5,
                      lineHeight: 1.5,
                      background: "var(--bg)",
                      border: "1px solid var(--divider)",
                      borderRadius: 10,
                      padding: "9px 11px",
                    }}
                  >
                    {c.question && (
                      <div style={{ color: "var(--text-3)", marginBottom: 3 }}>
                        <b style={{ color: "var(--text-2)" }}>Client :</b> {truncate(c.question, 120)}
                      </div>
                    )}
                    {c.answer && (
                      <div style={{ color: "var(--text-2)" }}>
                        <b style={{ color: "var(--coral)" }}>Jenny :</b> {truncate(c.answer, 140)}
                      </div>
                    )}
                    {c.comment && (
                      <div style={{ color: "var(--error)", marginTop: 4, fontSize: 12 }}>
                        ↳ {c.comment}
                      </div>
                    )}
                    {/* Boucle d'amélioration : transformer un 👎 en connaissance.
                        Le lien pré-remplit la Base de connaissances avec la
                        question du client pour que le gérant apprenne la bonne
                        réponse à Jenny en un clic. */}
                    {c.question && (
                      <Link
                        href={`/knowledge?teach=${encodeURIComponent(c.question)}`}
                        className="inline-flex items-center gap-1"
                        style={{
                          marginTop: 7,
                          fontSize: 11.5,
                          fontWeight: 600,
                          color: "var(--coral)",
                          textDecoration: "none",
                        }}
                      >
                        <GraduationCap style={{ width: 13, height: 13 }} />
                        Apprendre la réponse à Jenny →
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Ce qui marche : derniers 👍 — les réponses réussies à reproduire. */}
          {data.recent_positive.length > 0 && (
            <div style={{ marginTop: 16, borderTop: "1px solid var(--divider)", paddingTop: 12 }}>
              <div
                className="jmono"
                style={{ fontSize: 10.5, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text-3)", marginBottom: 8 }}
              >
                Ce qui marche — derniers 👍
              </div>
              <ul style={{ display: "flex", flexDirection: "column", gap: 10, margin: 0, padding: 0, listStyle: "none" }}>
                {data.recent_positive.slice(0, 3).map((c, i) => (
                  <li
                    key={i}
                    style={{
                      fontSize: 12.5,
                      lineHeight: 1.5,
                      background: "color-mix(in srgb, var(--success) 6%, var(--bg))",
                      border: "1px solid color-mix(in srgb, var(--success) 22%, var(--divider))",
                      borderRadius: 10,
                      padding: "9px 11px",
                    }}
                  >
                    {c.question && (
                      <div style={{ color: "var(--text-3)", marginBottom: 3 }}>
                        <b style={{ color: "var(--text-2)" }}>Client :</b> {truncate(c.question, 120)}
                      </div>
                    )}
                    {c.answer && (
                      <div style={{ color: "var(--text-2)" }}>
                        <b style={{ color: "var(--success)" }}>Jenny :</b> {truncate(c.answer, 140)}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function Stat({
  icon,
  value,
  label,
  suffix,
  hint,
}: {
  icon: React.ReactNode;
  value: number;
  label: string;
  suffix?: string;
  hint?: string;
}) {
  return (
    <div
      style={{
        background: "var(--bg)",
        border: "1px solid var(--divider)",
        borderRadius: 12,
        padding: "10px 12px",
      }}
    >
      <div className="flex items-center gap-1.5 mb-1">{icon}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: "var(--text)" }}>
        <AnimatedNumber value={value} format={(v) => v.toFixed(0)} />
        {suffix}
      </div>
      <div style={{ fontSize: 11, color: "var(--text-3)" }}>
        {label}
        {hint ? ` · ${hint}` : ""}
      </div>
    </div>
  );
}

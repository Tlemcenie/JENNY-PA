"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Cell,
} from "recharts";
import type { ValueType, NameType } from "recharts/types/component/DefaultTooltipContent";
import { Cpu, Activity, Terminal, AlertTriangle, Check, X } from "lucide-react";
import {
  getNanoGptTraining,
  getModelComparison,
  type NanoGptTraining,
  type ModelComparison,
  type ModelComparisonResult,
  ApiError,
} from "@/lib/api";

/**
 * Page « Modèle maison » — laboratoire du GPT entraîné from scratch.
 *
 * Tout le contenu provient des endpoints réels `GET /api/v1/nanogpt/training`
 * et `GET /api/v1/nanogpt/comparison` (eux-mêmes lus sur disque par le backend,
 * écrits par `nanogpt.train` et `scripts.compare_models`). Aucune donnée n'est
 * inventée : si rien n'a tourné, on affiche un état vide expliquant la commande.
 *
 * Cadre honnête assumé : le modèle maison est volontairement plus faible que
 * Groq/Ollama. L'intérêt est de montrer la méthode (corpus → tokenizer → boucle
 * d'entraînement → courbe de loss) et la comparaison chiffrée, pas de gagner.
 *
 * Mise en page : on ne rend que la zone de contenu (sidebar + topbar viennent
 * de `(dashboard)/layout.tsx`). Racine `.jx` pour hériter du design handoff.
 */

// Couleur slate (val_loss + libellés sobres), alignée sur la DA analytics.
const SLATE = "#7284A8";

// ── Formatage chiffré (FR : espace fine + virgule décimale) ───────────────
function formatParams(n: number): string {
  if (!n) return "—";
  if (n >= 1_000_000) {
    const millions = n / 1_000_000;
    // 12 281 856 → « 12,3 M » ; 4 200 000 → « 4,2 M »
    return `${millions.toFixed(1).replace(".", ",")} M`;
  }
  if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(".", ",")} k`;
  return String(n);
}

function formatInt(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("fr-FR");
}

function formatLoss(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toFixed(3).replace(".", ",");
}

function formatLatency(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2).replace(".", ",")} s`;
  return `${Math.round(ms)} ms`;
}

function formatScore(pct: number | null | undefined): string {
  if (pct === null || pct === undefined) return "—";
  return `${pct.toFixed(1).replace(".", ",")} %`;
}

// Recharts (v3) type la valeur d'un tooltip comme `ValueType | undefined`
// (number | string | tableau) ; on la ramène à un nombre pour nos formateurs.
function toNumber(v: ValueType | undefined): number {
  if (Array.isArray(v)) return Number(v[0] ?? 0);
  return Number(v ?? 0);
}

// ── Petite puce d'info (jmono) façon stat-chip ────────────────────────────
function StatChip({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div
      className="jcard"
      style={{
        padding: "10px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 2,
        minWidth: 110,
      }}
    >
      <span
        className="jmono"
        style={{
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--text-2)",
        }}
      >
        {label}
      </span>
      <span
        className="jmono"
        style={{ fontSize: 15, fontWeight: 600, color: "var(--text)" }}
      >
        {value}
      </span>
    </div>
  );
}

// ── Pavé de code copiable (état vide / pédagogie) ─────────────────────────
function CodeBlock({ lines }: { lines: string[] }) {
  return (
    <pre
      className="jmono"
      style={{
        background: "var(--bg-tint)",
        border: "1px solid var(--divider)",
        borderRadius: 10,
        padding: "12px 14px",
        fontSize: 12.5,
        lineHeight: 1.7,
        color: "var(--text)",
        overflowX: "auto",
        margin: 0,
      }}
    >
      {lines.map((l, i) => (
        <div key={i}>
          <span style={{ color: SLATE, userSelect: "none" }}>$ </span>
          {l}
        </div>
      ))}
    </pre>
  );
}

// Tooltip recharts harmonisé avec la DA (cf. message-volume-chart).
const chartTooltipStyle = {
  background: "var(--surface)",
  border: "1px solid var(--divider)",
  borderRadius: "0.75rem",
  fontSize: "0.8125rem",
  color: "var(--text)",
  boxShadow: "0 8px 24px rgba(0,0,0,0.12)",
} as const;

// ── Carte courbe d'entraînement ───────────────────────────────────────────
function TrainingCard({ training }: { training: NanoGptTraining }) {
  const { points, state } = training;
  const hasCurve = points.length > 0 && state !== "absent";

  const curveData = points.map((p) => ({
    step: p.step,
    train_loss: Number(p.train_loss.toFixed(4)),
    val_loss: Number(p.val_loss.toFixed(4)),
  }));

  const stateBadge =
    state === "running"
      ? { cls: "jbadge--warn", label: "ENTRAÎNEMENT EN COURS" }
      : state === "done"
        ? { cls: "jbadge--mint", label: "ENTRAÎNEMENT TERMINÉ" }
        : { cls: "jbadge--slate", label: "PAS ENCORE LANCÉ" };

  return (
    <section className="jcard" style={{ padding: 24, marginBottom: 24 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 18,
          flexWrap: "wrap",
        }}
      >
        <Activity style={{ width: 18, height: 18, color: "var(--coral)" }} />
        <h2
          className="jserif"
          style={{ fontSize: 19, color: "var(--text)", margin: 0 }}
        >
          Courbe d&apos;entraînement
        </h2>
        <span className={`jbadge ${stateBadge.cls}`} style={{ marginLeft: "auto" }}>
          {state === "running" && (
            <span className="relative flex w-1.5 h-1.5">
              <span className="absolute inline-flex h-full w-full rounded-full bg-current opacity-60 animate-ping" />
              <span className="relative inline-flex w-1.5 h-1.5 rounded-full bg-current" />
            </span>
          )}
          {stateBadge.label}
        </span>
      </div>

      {/* Chips de stats (faits du dernier run) */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 10,
          marginBottom: 20,
        }}
      >
        <StatChip label="Paramètres" value={formatParams(training.params)} />
        <StatChip label="Vocabulaire" value={formatInt(training.vocab_size)} />
        <StatChip
          label="Device"
          value={(training.device || "—").toUpperCase()}
        />
        <StatChip label="Meilleure val_loss" value={formatLoss(training.best_val_loss)} />
        <StatChip label="Tokens vus" value={formatInt(training.total_tokens)} />
        <StatChip
          label="Étapes"
          value={
            training.max_steps
              ? `${formatInt(training.step)} / ${formatInt(training.max_steps)}`
              : formatInt(training.step)
          }
        />
        {training.model && (
          <StatChip
            label="Architecture"
            value={`${training.model.n_layer}×${training.model.n_head} · ${training.model.n_embd}d`}
          />
        )}
      </div>

      {hasCurve ? (
        <>
          <div style={{ width: "100%", height: 320 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={curveData}
                margin={{ top: 8, right: 12, left: -8, bottom: 4 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  vertical={false}
                  stroke="var(--divider)"
                />
                <XAxis
                  dataKey="step"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  tick={{ fontSize: 10, fill: "var(--text-2)" }}
                  tickLine={false}
                  axisLine={false}
                  label={{
                    value: "étape",
                    position: "insideBottomRight",
                    offset: -2,
                    fontSize: 10,
                    fill: "var(--text-2)",
                  }}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: "var(--text-2)" }}
                  tickLine={false}
                  axisLine={false}
                  width={36}
                  domain={["auto", "auto"]}
                />
                <Tooltip
                  contentStyle={chartTooltipStyle}
                  labelStyle={{ color: "var(--text-2)" }}
                  labelFormatter={(v) => `Étape ${v}`}
                  formatter={(value: ValueType | undefined, name: NameType | undefined) => [
                    formatLoss(toNumber(value)),
                    name === "train_loss" ? "Perte (train)" : "Perte (val)",
                  ]}
                />
                <Line
                  type="monotone"
                  dataKey="train_loss"
                  name="train_loss"
                  stroke="var(--coral)"
                  strokeWidth={2.2}
                  dot={false}
                  isAnimationActive
                />
                <Line
                  type="monotone"
                  dataKey="val_loss"
                  name="val_loss"
                  stroke={SLATE}
                  strokeWidth={2.2}
                  strokeDasharray="5 4"
                  dot={false}
                  isAnimationActive
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          {/* Légende */}
          <div
            style={{
              display: "flex",
              gap: 18,
              marginTop: 10,
              fontSize: 12,
              color: "var(--text-2)",
            }}
          >
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <span
                style={{
                  width: 16,
                  height: 3,
                  borderRadius: 2,
                  background: "var(--coral)",
                  display: "inline-block",
                }}
              />
              Perte (train)
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <span
                style={{
                  width: 16,
                  height: 0,
                  borderTop: `3px dashed ${SLATE}`,
                  display: "inline-block",
                }}
              />
              Perte (validation)
            </span>
          </div>
        </>
      ) : (
        <div
          style={{
            border: "1px dashed var(--divider)",
            borderRadius: 12,
            padding: "22px 20px",
            display: "flex",
            flexDirection: "column",
            gap: 12,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Terminal style={{ width: 17, height: 17, color: SLATE }} />
            <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text)" }}>
              Aucun entraînement pour l&apos;instant
            </span>
          </div>
          <p style={{ fontSize: 13, color: "var(--text-2)", margin: 0, maxWidth: 560 }}>
            Lance d&apos;abord la préparation du corpus + tokenizer, puis la boucle
            d&apos;entraînement. La courbe de perte apparaîtra ici en temps réel.
          </p>
          <CodeBlock
            lines={[
              ".venv/bin/python -m nanogpt.data",
              ".venv/bin/python -m nanogpt.train",
            ]}
          />
        </div>
      )}
    </section>
  );
}

// ── Une ligne de modèle dans la comparaison ───────────────────────────────
function ModelRow({ r }: { r: ModelComparisonResult }) {
  const isNano = r.key === "nanogpt" || r.provider === "nanogpt";
  return (
    <div
      className="jcard"
      style={{
        padding: 18,
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 180 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 15, fontWeight: 600, color: "var(--text)" }}>
              {r.label}
            </span>
            {r.available ? (
              <span className="jbadge jbadge--mint">CONNECTÉ</span>
            ) : (
              <span className="jbadge jbadge--slate">INDISPONIBLE</span>
            )}
          </div>
          <span
            className="jmono"
            style={{ fontSize: 11.5, color: "var(--text-2)" }}
          >
            {r.provider} · {r.model}
          </span>
        </div>

        {/* Efficacité + perf */}
        <div style={{ display: "flex", gap: 22 }}>
          <div style={{ textAlign: "right" }}>
            <div
              className="jmono"
              style={{
                fontSize: 18,
                fontWeight: 700,
                color: r.available ? "var(--text)" : "var(--text-2)",
                lineHeight: 1.1,
              }}
            >
              {formatScore(r.score_pct)}
            </div>
            <div style={{ fontSize: 10.5, color: "var(--text-2)" }}>
              efficacité
              {r.checks_total != null && r.checks_passed != null && (
                <> · {r.checks_passed}/{r.checks_total}</>
              )}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div
              className="jmono"
              style={{
                fontSize: 18,
                fontWeight: 700,
                color: r.available ? "var(--text)" : "var(--text-2)",
                lineHeight: 1.1,
              }}
            >
              {formatLatency(r.avg_latency_ms)}
            </div>
            <div style={{ fontSize: 10.5, color: "var(--text-2)" }}>latence moy.</div>
          </div>
        </div>
      </div>

      {/* Note (ex. indisponibilité) */}
      {r.note && (
        <div
          style={{
            fontSize: 12,
            color: "var(--text-2)",
            background: "var(--bg-tint)",
            borderRadius: 8,
            padding: "7px 10px",
          }}
        >
          {r.note}
        </div>
      )}

      {/* Cadre honnête pour le modèle maison */}
      {isNano && r.available && (
        <div
          style={{
            display: "flex",
            gap: 8,
            alignItems: "flex-start",
            fontSize: 12,
            color: "var(--text-2)",
            lineHeight: 1.5,
          }}
        >
          <AlertTriangle
            style={{ width: 14, height: 14, color: SLATE, flexShrink: 0, marginTop: 2 }}
          />
          <span>
            Score faible attendu : ce modèle est entraîné <i>from scratch</i> sur un
            petit corpus, sans fine-tune. On le compare pour la transparence, pas
            pour le déployer.
          </span>
        </div>
      )}

      {/* Échantillons q→a (si fournis par l'API) */}
      {r.samples && r.samples.length > 0 && (
        <div
          className="jmono"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
            background: "var(--bg-tint)",
            border: "1px solid var(--divider)",
            borderRadius: 10,
            padding: "10px 12px",
            fontSize: 11.5,
          }}
        >
          {r.samples.slice(0, 2).map((s, i) => (
            <div key={i} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <span style={{ color: "var(--text-2)" }}>Q : {s.q}</span>
              <span style={{ color: "var(--text)", display: "flex", gap: 6, alignItems: "flex-start" }}>
                <span
                  style={{
                    color: s.ok ? "var(--success)" : "var(--error)",
                    flexShrink: 0,
                  }}
                >
                  {s.ok ? <Check size={13} /> : <X size={13} />}
                </span>
                <span>R : {s.a}</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Carte comparaison 3 modèles ───────────────────────────────────────────
function ComparisonCard({ comparison }: { comparison: ModelComparison }) {
  const results = comparison.results;
  const hasData = results.length > 0;

  // Données pour les barres (un point par modèle, libellé court).
  const barData = results.map((r) => ({
    name: r.label.split("—")[0].trim() || r.label,
    score: r.score_pct ?? 0,
    latency: r.avg_latency_ms ?? 0,
    available: r.available,
    isNano: r.key === "nanogpt" || r.provider === "nanogpt",
  }));

  const scoreColor = (d: (typeof barData)[number]) =>
    !d.available ? SLATE : d.isNano ? SLATE : "var(--coral)";

  return (
    <section className="jcard" style={{ padding: 24 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 6,
          flexWrap: "wrap",
        }}
      >
        <Cpu style={{ width: 18, height: 18, color: "var(--coral)" }} />
        <h2 className="jserif" style={{ fontSize: 19, color: "var(--text)", margin: 0 }}>
          Comparaison des 3 modèles
        </h2>
        {comparison.prompts > 0 && (
          <span className="jbadge jbadge--coral" style={{ marginLeft: "auto" }}>
            {comparison.prompts} PROMPTS
          </span>
        )}
      </div>
      <p style={{ fontSize: 13, color: "var(--text-2)", marginTop: 0, marginBottom: 20, maxWidth: 620 }}>
        Même jeu de questions coiffeur posé aux trois moteurs. Le modèle maison
        sert de point bas assumé : il montre l&apos;écart réel face à un LLM
        généraliste hébergé.
      </p>

      {!hasData ? (
        <div
          style={{
            border: "1px dashed var(--divider)",
            borderRadius: 12,
            padding: "22px 20px",
            display: "flex",
            flexDirection: "column",
            gap: 12,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Terminal style={{ width: 17, height: 17, color: SLATE }} />
            <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text)" }}>
              Comparaison non encore générée
            </span>
          </div>
          <p style={{ fontSize: 13, color: "var(--text-2)", margin: 0, maxWidth: 560 }}>
            Lance le banc de comparaison pour mesurer Groq, Ollama et le modèle
            maison sur les mêmes prompts.
          </p>
          <CodeBlock lines={[".venv/bin/python scripts/compare_models.py"]} />
        </div>
      ) : (
        <>
          {/* Lignes détaillées par modèle */}
          <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 24 }}>
            {results.map((r) => (
              <ModelRow key={r.key} r={r} />
            ))}
          </div>

          {/* Deux mini-graphes côte à côte */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
              gap: 18,
            }}
          >
            {/* Efficacité */}
            <div>
              <div
                className="jmono"
                style={{
                  fontSize: 10.5,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  color: "var(--text-2)",
                  marginBottom: 8,
                }}
              >
                Efficacité (%)
              </div>
              <div style={{ width: "100%", height: 200 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={barData} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--divider)" />
                    <XAxis
                      dataKey="name"
                      tick={{ fontSize: 10, fill: "var(--text-2)" }}
                      tickLine={false}
                      axisLine={false}
                      interval={0}
                    />
                    <YAxis
                      tick={{ fontSize: 10, fill: "var(--text-2)" }}
                      tickLine={false}
                      axisLine={false}
                      domain={[0, 100]}
                      width={30}
                    />
                    <Tooltip
                      cursor={{ fill: "var(--coral)", opacity: 0.06 }}
                      contentStyle={chartTooltipStyle}
                      formatter={(value: ValueType | undefined) => [formatScore(toNumber(value)), "Efficacité"]}
                    />
                    <Bar dataKey="score" radius={[4, 4, 0, 0]} maxBarSize={64}>
                      {barData.map((d, i) => (
                        <Cell key={i} fill={scoreColor(d)} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Latence */}
            <div>
              <div
                className="jmono"
                style={{
                  fontSize: 10.5,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  color: "var(--text-2)",
                  marginBottom: 8,
                }}
              >
                Latence moyenne (ms)
              </div>
              <div style={{ width: "100%", height: 200 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={barData} margin={{ top: 8, right: 8, left: -6, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--divider)" />
                    <XAxis
                      dataKey="name"
                      tick={{ fontSize: 10, fill: "var(--text-2)" }}
                      tickLine={false}
                      axisLine={false}
                      interval={0}
                    />
                    <YAxis
                      tick={{ fontSize: 10, fill: "var(--text-2)" }}
                      tickLine={false}
                      axisLine={false}
                      width={48}
                      allowDecimals={false}
                    />
                    <Tooltip
                      cursor={{ fill: SLATE, opacity: 0.06 }}
                      contentStyle={chartTooltipStyle}
                      formatter={(value: ValueType | undefined) => [formatLatency(toNumber(value)), "Latence"]}
                    />
                    <Bar dataKey="latency" radius={[4, 4, 0, 0]} maxBarSize={64} fill={SLATE} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

// ── Squelette de chargement ───────────────────────────────────────────────
function LabSkeleton() {
  return (
    <div className="jx h-full overflow-y-auto" style={{ background: "var(--bg)", padding: "28px 32px" }}>
      <div style={{ maxWidth: 960, margin: "0 auto" }}>
        <div
          style={{
            height: 14,
            width: 130,
            background: "var(--bg-tint)",
            borderRadius: 6,
            marginBottom: 14,
          }}
        />
        <div
          style={{
            height: 40,
            width: 300,
            background: "var(--bg-tint)",
            borderRadius: 8,
            marginBottom: 28,
          }}
        />
        <div
          className="jcard"
          style={{ height: 420, marginBottom: 24, background: "var(--bg-tint)" }}
        />
        <div className="jcard" style={{ height: 360, background: "var(--bg-tint)" }} />
      </div>
    </div>
  );
}

export default function LabPage() {
  const [training, setTraining] = useState<NanoGptTraining | null>(null);
  const [comparison, setComparison] = useState<ModelComparison | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // On garde l'état « running » dans une ref pour piloter le polling sans
  // recréer l'intervalle à chaque rafraîchissement.
  const isRunningRef = useRef(false);

  const fetchTraining = useCallback(async () => {
    const t = await getNanoGptTraining();
    isRunningRef.current = t.state === "running";
    setTraining(t);
    return t;
  }, []);

  const fetchAll = useCallback(async () => {
    setError(null);
    try {
      const [, c] = await Promise.all([fetchTraining(), getModelComparison()]);
      setComparison(c);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          `Erreur ${err.status} : ${
            (err.data as { detail?: string })?.detail || err.statusText
          }`
        );
      } else {
        setError(
          "Impossible de charger le modèle maison. Vérifiez que le backend est démarré."
        );
      }
    } finally {
      setIsLoading(false);
    }
  }, [fetchTraining]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  // Polling de la courbe pendant un entraînement en cours (toutes les 5 s).
  // L'intervalle vit en permanence mais ne refait un appel que si l'état
  // courant est « running » — on s'arrête naturellement quand c'est terminé.
  useEffect(() => {
    const id = setInterval(() => {
      if (isRunningRef.current) {
        fetchTraining().catch(() => {});
      }
    }, 5000);
    return () => clearInterval(id);
  }, [fetchTraining]);

  if (isLoading && !training) return <LabSkeleton />;

  if (error) {
    return (
      <div className="jx h-full overflow-y-auto" style={{ background: "var(--bg)", padding: "28px 32px" }}>
        <div style={{ maxWidth: 960, margin: "0 auto" }}>
          <div
            className="jcard"
            style={{
              padding: 22,
              display: "flex",
              alignItems: "center",
              gap: 14,
            }}
          >
            <AlertTriangle style={{ width: 22, height: 22, color: "var(--error)" }} />
            <div style={{ flex: 1 }}>
              <p style={{ fontSize: 14, color: "var(--text)", margin: 0 }}>{error}</p>
            </div>
            <button
              onClick={() => {
                setIsLoading(true);
                fetchAll();
              }}
              className="jpill"
              style={{ flexShrink: 0 }}
            >
              Réessayer
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="jx h-full overflow-y-auto" style={{ background: "var(--bg)", padding: "28px 32px" }}>
      <div style={{ maxWidth: 960, margin: "0 auto" }}>
        {/* ── En-tête éditorial ── */}
        <header style={{ marginBottom: 28 }}>
          <div
            className="jmono"
            style={{
              fontSize: 11,
              letterSpacing: "0.22em",
              textTransform: "uppercase",
              color: "var(--coral)",
              marginBottom: 10,
            }}
          >
            — Laboratoire —
          </div>
          <h1
            className="jserif"
            style={{
              fontSize: "clamp(30px, 5vw, 44px)",
              lineHeight: 1.05,
              color: "var(--text)",
              margin: 0,
            }}
          >
            Le modèle <i>maison.</i>
          </h1>
          <p
            style={{
              fontSize: 14.5,
              color: "var(--text-2)",
              marginTop: 12,
              maxWidth: 640,
              lineHeight: 1.6,
            }}
          >
            Un petit GPT entraîné <b>from scratch</b> (aucun fine-tune) sur un corpus
            français, avec son propre tokenizer. Il est <b>volontairement plus faible</b>{" "}
            que Groq ou Ollama : l&apos;objectif n&apos;est pas la performance, mais de
            montrer la méthode de bout en bout — corpus, boucle d&apos;entraînement,
            courbe de perte — et de la comparer honnêtement aux modèles de production.
          </p>
        </header>

        {training && <TrainingCard training={training} />}
        {comparison && <ComparisonCard comparison={comparison} />}
      </div>
    </div>
  );
}

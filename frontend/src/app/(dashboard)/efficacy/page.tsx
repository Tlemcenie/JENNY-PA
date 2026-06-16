"use client";

import { useEffect, useState, useCallback, type ReactNode } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  Gauge,
  Sparkles,
  MessageSquare,
  Users,
  GraduationCap,
  HelpCircle,
  ArrowRight,
  Check,
  Cpu,
} from "lucide-react";
import { getJennyMetrics, type JennyMetrics, ApiError } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { AnimatedNumber } from "@/components/ui/animated-number";
import {
  fadeInUp,
  staggerContainer,
  staggerItem,
  easeOutExpo,
  springSnappy,
} from "@/lib/motion";

// ── Libellés FR lisibles pour les critères d'évaluation du banc d'essai ──
// Toute clé inconnue est rendue telle quelle (humanisée) plutôt qu'ignorée,
// afin de ne jamais masquer un critère renvoyé par le back.
const CRITERION_LABELS: Record<string, string> = {
  persona_humaine: "Persona humaine",
  langue: "Bonne langue",
  clarification: "Clarification",
  lacune_detectee: "Lacunes détectées",
  info_cle_presente: "Réponses fondées (grounding)",
  interdits_absents: "Formules interdites évitées",
};

function criterionLabel(key: string): string {
  if (CRITERION_LABELS[key]) return CRITERION_LABELS[key];
  // Repli : « ma_cle_technique » → « Ma cle technique »
  const spaced = key.replace(/_/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

// Couleur d'une barre selon le pourcentage de réussite (seuils DA).
function barColor(pct: number): string {
  if (pct >= 90) return "var(--color-jenny-success)";
  if (pct >= 70) return "var(--color-jenny-coral)";
  return "var(--color-jenny-error)";
}

// ── Eyebrow mono (cf. DA dashboard / analytics) ──
function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <div className="font-mono text-[11px] tracking-[0.22em] uppercase text-jenny-coral mb-2">
      {children}
    </div>
  );
}

// ── Carte de volume (style StatCard de la DA) ──
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
          {sub && (
            <p className="text-[11px] text-jenny-text-secondary/70 mt-1.5 leading-snug">{sub}</p>
          )}
        </div>
      </Card>
    </motion.div>
  );
}

// ── Squelette de chargement ──
function EfficacySkeleton() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto p-6 space-y-6">
        <div className="space-y-2">
          <Skeleton className="h-3 w-32" />
          <Skeleton className="h-10 w-72" />
        </div>
        <Card className="p-6">
          <Skeleton className="h-4 w-40 mb-4" />
          <Skeleton className="h-16 w-44 mb-2" />
          <Skeleton className="h-4 w-56 mb-6" />
          <div className="space-y-3.5">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i}>
                <Skeleton className="h-3 w-40 mb-2" />
                <Skeleton className="h-2 w-full" />
              </div>
            ))}
          </div>
        </Card>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i} className="p-5">
              <Skeleton className="h-10 w-10 rounded-xl mb-3" />
              <Skeleton className="h-7 w-20 mb-1.5" />
              <Skeleton className="h-3 w-24" />
            </Card>
          ))}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Skeleton className="h-40 w-full rounded-2xl" />
          <Skeleton className="h-40 w-full rounded-2xl" />
        </div>
      </div>
    </div>
  );
}

export default function EfficacyPage() {
  const [metrics, setMetrics] = useState<JennyMetrics | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchMetrics = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setMetrics(await getJennyMetrics());
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          `Erreur ${err.status}: ${
            (err.data as { detail?: string })?.detail || err.statusText
          }`
        );
      } else {
        setError(
          "Impossible de charger l'efficacité de Jenny. Vérifiez que le backend est démarré."
        );
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMetrics();
  }, [fetchMetrics]);

  if (isLoading && !metrics) return <EfficacySkeleton />;

  if (error) {
    return (
      <div className="h-full overflow-y-auto">
        <div className="max-w-5xl mx-auto p-6">
          <ErrorState message={error} onRetry={fetchMetrics} />
        </div>
      </div>
    );
  }

  if (!metrics) return null;

  const evalSummary = metrics.last_eval;
  // Critères triés du plus faible au plus élevé : on met en avant ce qui
  // mérite l'attention du commerçant en haut de liste.
  const criteria = evalSummary
    ? Object.entries(evalSummary.by_criterion).sort((a, b) => a[1].pct - b[1].pct)
    : [];

  const gaps = metrics.gaps;
  const openQuestions = metrics.top_open_questions;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto p-6 space-y-6">
        {/* ── En-tête ── */}
        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: easeOutExpo }}
        >
          <Eyebrow>— Efficacité —</Eyebrow>
          <h1 className="font-display text-[clamp(28px,4vw,36px)] leading-[1] tracking-[-0.02em] text-jenny-text">
            Jenny, en <span className="italic text-jenny-coral">chiffres.</span>
          </h1>
          <p className="text-sm text-jenny-text-secondary mt-1">
            Évaluation de Jenny côté client — banc d&apos;essai automatique sur des
            conversations types.
          </p>
          <Link
            href="/lab"
            className="group mt-3 inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-jenny-coral hover:text-jenny-coral-dark transition-colors"
          >
            <Cpu className="w-3.5 h-3.5" />
            Comparer les 3 modèles
            <ArrowRight className="w-3.5 h-3.5 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </motion.div>

        {/* ── Score d'efficacité (banc d'essai) ── */}
        <motion.div variants={fadeInUp} initial="hidden" animate="show">
          {evalSummary ? (
            <Card className="p-6">
              <div className="flex flex-wrap items-end gap-x-8 gap-y-4 mb-6">
                <div>
                  <div className="flex items-center gap-2 font-mono text-[11px] tracking-[0.18em] uppercase text-jenny-text-secondary font-semibold mb-3">
                    <Gauge className="w-4 h-4 text-jenny-coral" />
                    Score d&apos;efficacité
                  </div>
                  <div className="font-display text-[clamp(48px,9vw,68px)] leading-[0.95] tracking-[-0.02em] text-jenny-text tabular-nums">
                    <AnimatedNumber
                      value={evalSummary.score_pct}
                      format={(n) => `${Math.round(n)}%`}
                    />
                  </div>
                  <p className="text-[13px] text-jenny-text-secondary mt-2">
                    <b className="text-jenny-text tabular-nums">
                      {evalSummary.checks_passed}/{evalSummary.checks_total}
                    </b>{" "}
                    vérifications sur{" "}
                    <b className="text-jenny-text tabular-nums">{evalSummary.scenarios}</b>{" "}
                    scénario{evalSummary.scenarios > 1 ? "s" : ""}
                  </p>
                </div>
              </div>

              {criteria.length > 0 && (
                <div className="flex flex-col gap-3.5 pt-5 border-t border-jenny-divider/70">
                  {criteria.map(([key, c], i) => {
                    const color = barColor(c.pct);
                    return (
                      <div key={key}>
                        <div className="flex items-baseline justify-between gap-3 mb-1.5">
                          <span className="text-[13px] text-jenny-text">
                            {criterionLabel(key)}
                          </span>
                          <span className="font-mono text-[11.5px] font-semibold tabular-nums text-jenny-text-secondary">
                            <span style={{ color }}>{Math.round(c.pct)}%</span>
                            <span className="text-jenny-text-secondary/60">
                              {" "}
                              · {c.pass}/{c.total}
                            </span>
                          </span>
                        </div>
                        <div className="h-2 rounded-full bg-jenny-bg-tint overflow-hidden">
                          <motion.div
                            className="h-full rounded-full"
                            style={{ background: color, transformOrigin: "left" }}
                            initial={{ scaleX: 0 }}
                            animate={{ scaleX: Math.max(0, Math.min(100, c.pct)) / 100 }}
                            transition={{
                              duration: 0.6,
                              ease: easeOutExpo,
                              delay: 0.15 + i * 0.06,
                            }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </Card>
          ) : (
            <Card className="p-6 flex flex-wrap items-center gap-5">
              <div className="w-12 h-12 rounded-[14px] bg-jenny-coral/10 text-jenny-coral flex items-center justify-center shrink-0">
                <Gauge className="w-[22px] h-[22px]" />
              </div>
              <div className="flex-1 min-w-[240px]">
                <h2 className="font-display text-[20px] leading-tight text-jenny-text mb-1">
                  Lance le banc d&apos;essai pour mesurer Jenny
                </h2>
                <p className="text-[13px] text-jenny-text-secondary leading-relaxed">
                  Aucune évaluation n&apos;a encore été enregistrée. Une fois le banc
                  d&apos;essai exécuté, le score d&apos;efficacité et le détail par critère
                  s&apos;afficheront ici.
                </p>
              </div>
            </Card>
          )}
        </motion.div>

        {/* ── Cartes de volume ── */}
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="grid grid-cols-1 sm:grid-cols-3 gap-3"
        >
          <StatCard
            icon={<MessageSquare className="w-5 h-5" />}
            tint="#FF7F6A"
            label="Conversations"
            value={<AnimatedNumber value={metrics.conversations} />}
          />
          <StatCard
            icon={<Sparkles className="w-5 h-5" />}
            tint="#3B82F6"
            label="Messages"
            value={<AnimatedNumber value={metrics.messages} />}
          />
          <StatCard
            icon={<Users className="w-5 h-5" />}
            tint="#8B5CF6"
            label="Clients"
            value={<AnimatedNumber value={metrics.customers} />}
          />
        </motion.div>

        {/* ── Apprentissage + Questions sans réponse ── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {/* (a) Apprentissage */}
          <motion.div variants={fadeInUp} initial="hidden" animate="show">
            <Card className="p-6 h-full flex flex-col">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-9 h-9 rounded-xl bg-jenny-coral/10 text-jenny-coral flex items-center justify-center">
                  <GraduationCap className="w-[18px] h-[18px]" />
                </div>
                <h2 className="font-semibold text-jenny-text text-sm">Apprentissage</h2>
              </div>

              <div className="grid grid-cols-3 gap-3 mb-4">
                <div>
                  <div className="font-display text-[1.5rem] font-bold text-jenny-text tabular-nums leading-none">
                    <AnimatedNumber value={gaps.open} />
                  </div>
                  <div className="text-[11px] text-jenny-text-secondary mt-1 leading-snug">
                    Lacunes ouvertes
                  </div>
                </div>
                <div>
                  <div className="font-display text-[1.5rem] font-bold text-jenny-text tabular-nums leading-none">
                    <AnimatedNumber value={gaps.answered} />
                  </div>
                  <div className="text-[11px] text-jenny-text-secondary mt-1 leading-snug">
                    Répondues
                  </div>
                </div>
                <div>
                  <div className="font-display text-[1.5rem] font-bold text-jenny-text tabular-nums leading-none">
                    <AnimatedNumber value={gaps.saved_to_kb} />
                  </div>
                  <div className="text-[11px] text-jenny-text-secondary mt-1 leading-snug">
                    Apprises
                  </div>
                </div>
              </div>

              <div className="mt-auto pt-4 border-t border-jenny-divider/70 flex items-center justify-between gap-3">
                <span className="text-[12.5px] text-jenny-text-secondary leading-snug">
                  <b className="text-jenny-text tabular-nums">{metrics.learned_answers}</b>{" "}
                  réponse{metrics.learned_answers > 1 ? "s" : ""} apprise
                  {metrics.learned_answers > 1 ? "s" : ""}
                </span>
                <Link
                  href="/learning"
                  className="group inline-flex items-center gap-1 text-[12.5px] font-semibold text-jenny-coral hover:text-jenny-coral-dark transition-colors shrink-0"
                >
                  Apprentissage
                  <ArrowRight className="w-3.5 h-3.5 transition-transform group-hover:translate-x-0.5" />
                </Link>
              </div>
            </Card>
          </motion.div>

          {/* (b) Questions fréquentes sans réponse */}
          <motion.div variants={fadeInUp} initial="hidden" animate="show">
            <Card className="p-6 h-full flex flex-col">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-9 h-9 rounded-xl bg-jenny-coral/10 text-jenny-coral flex items-center justify-center">
                  <HelpCircle className="w-[18px] h-[18px]" />
                </div>
                <h2 className="font-semibold text-jenny-text text-sm">
                  Questions fréquentes sans réponse
                </h2>
              </div>

              {openQuestions.length === 0 ? (
                <div className="flex-1 flex items-center gap-2 text-[13px] text-jenny-text-secondary">
                  <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-jenny-success/15 text-jenny-success shrink-0">
                    <Check className="w-3.5 h-3.5" />
                  </span>
                  Aucune question en attente
                </div>
              ) : (
                <ul className="space-y-2.5">
                  {openQuestions.map((q, i) => (
                    <li key={`${i}-${q}`} className="flex items-start gap-2.5">
                      <span className="mt-[7px] w-1.5 h-1.5 rounded-full bg-jenny-coral shrink-0" />
                      <span className="text-[13px] text-jenny-text leading-relaxed">{q}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </motion.div>
        </div>
      </div>
    </div>
  );
}

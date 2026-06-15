"use client";

import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Lightbulb,
  Sparkles,
  Send,
  Check,
  X,
  Trash,
  Inbox,
  CheckCheck,
  Clock,
  BookOpen,
  MessageCircleQuestion,
  AlertCircle,
} from "lucide-react";
import {
  listKnowledgeGaps,
  knowledgeGapStats,
  knowledgeGapRecap,
  answerKnowledgeGap,
  dismissKnowledgeGap,
  type KnowledgeGap,
  type GapStats,
  type GapRecap,
  ApiError,
} from "@/lib/api";
import { channelLabel, intentLabel, formatRelativeTime, cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SkeletonCard } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { useToast } from "@/components/ui/toast";
import { staggerContainer, staggerItem, fadeInUp, springSnappy } from "@/lib/motion";

// ── Filtre de statut (onglets) ──
type StatusFilter = "open" | "answered" | "dismissed";

const FILTERS: { id: StatusFilter; label: string }[] = [
  { id: "open", label: "En attente" },
  { id: "answered", label: "Répondues" },
  { id: "dismissed", label: "Ignorées" },
];

// Cartes de stats du bandeau (pastilles colorées).
const STAT_CARDS: {
  key: keyof Pick<GapStats, "open" | "answered" | "saved_to_kb">;
  label: string;
  icon: typeof Inbox;
  dot: string;
  tint: string;
}[] = [
  { key: "open", label: "En attente", icon: Inbox, dot: "bg-jenny-warning", tint: "#F59E0B" },
  { key: "answered", label: "Répondues", icon: CheckCheck, dot: "bg-jenny-success", tint: "#10B981" },
  { key: "saved_to_kb", label: "Apprises", icon: BookOpen, dot: "bg-jenny-coral", tint: "#FF7F6A" },
];

export default function LearningPage() {
  const toast = useToast();

  const [filter, setFilter] = useState<StatusFilter>("open");
  const [gaps, setGaps] = useState<KnowledgeGap[]>([]);
  const [stats, setStats] = useState<GapStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Récapitulatif (carte dépliable).
  const [recap, setRecap] = useState<GapRecap | null>(null);
  const [recapOpen, setRecapOpen] = useState(false);
  const [recapLoading, setRecapLoading] = useState(false);

  // État du formulaire de réponse, par lacune.
  const [answeringId, setAnsweringId] = useState<string | null>(null);
  const [answerDraft, setAnswerDraft] = useState("");
  const [saveToKb, setSaveToKb] = useState(true);
  const [submittingId, setSubmittingId] = useState<string | null>(null);
  const [dismissingId, setDismissingId] = useState<string | null>(null);
  // Avertissement discret si la KB n'était pas dispo au moment de l'ajout.
  const [kbWarningId, setKbWarningId] = useState<string | null>(null);

  // ── Chargement des lacunes (selon le filtre) + stats ──
  const fetchData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [gapsData, statsData] = await Promise.all([
        listKnowledgeGaps(filter),
        knowledgeGapStats(),
      ]);
      setGaps(gapsData.gaps || []);
      setStats(statsData);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`Erreur ${err.status}: ${(err.data as { detail?: string })?.detail || err.statusText}`);
      } else {
        setError("Impossible de charger les lacunes d'apprentissage.");
      }
    } finally {
      setIsLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Recharge uniquement les stats (après une action), sans skeleton.
  const refreshStats = useCallback(async () => {
    try {
      setStats(await knowledgeGapStats());
    } catch {
      // silencieux : un échec de stats ne doit pas perturber l'écran.
    }
  }, []);

  // ── Récapitulatif à présenter au propriétaire ──
  const toggleRecap = async () => {
    if (recapOpen) {
      setRecapOpen(false);
      return;
    }
    setRecapOpen(true);
    if (recap) return; // déjà chargé.
    setRecapLoading(true);
    try {
      setRecap(await knowledgeGapRecap());
    } catch {
      toast.error("Impossible de générer le récapitulatif.");
      setRecapOpen(false);
    } finally {
      setRecapLoading(false);
    }
  };

  // ── Ouvre / ferme le champ de réponse d'une carte ──
  const openAnswer = (gap: KnowledgeGap) => {
    setAnsweringId(gap.id);
    setAnswerDraft(gap.answer || "");
    setSaveToKb(true);
    setKbWarningId(null);
  };

  const closeAnswer = () => {
    setAnsweringId(null);
    setAnswerDraft("");
  };

  // ── Enregistre une réponse (et l'ajoute à la KB si demandé) ──
  const submitAnswer = async (gap: KnowledgeGap) => {
    const answer = answerDraft.trim();
    if (!answer) return;
    setSubmittingId(gap.id);
    setKbWarningId(null);
    try {
      const res = await answerKnowledgeGap(gap.id, answer, saveToKb);
      // KB indisponible alors que la case était cochée → avertissement discret.
      if (saveToKb && !res.saved_to_kb) {
        setKbWarningId(gap.id);
        toast.success("Réponse enregistrée.");
      } else if (res.saved_to_kb) {
        toast.success("Réponse enregistrée et ajoutée à la base.");
      } else {
        toast.success("Réponse enregistrée.");
      }
      // Sur l'onglet « En attente », la lacune répondue quitte la liste.
      if (filter === "open") {
        setGaps((prev) => prev.filter((g) => g.id !== gap.id));
      } else {
        setGaps((prev) => prev.map((g) => (g.id === gap.id ? res.gap : g)));
      }
      closeAnswer();
      void refreshStats();
      // Le récap reflète l'état des lacunes ouvertes → on l'invalide.
      setRecap(null);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? (err.data as { detail?: string })?.detail || "Échec de l'enregistrement."
          : "Impossible d'enregistrer la réponse.";
      toast.error(msg);
    } finally {
      setSubmittingId(null);
    }
  };

  // ── Ignore une lacune (confirmation légère) ──
  const handleDismiss = async (gap: KnowledgeGap) => {
    if (!window.confirm("Ignorer cette question ? Jenny ne la signalera plus.")) return;
    setDismissingId(gap.id);
    try {
      await dismissKnowledgeGap(gap.id);
      setGaps((prev) => prev.filter((g) => g.id !== gap.id));
      toast.success("Question ignorée.");
      void refreshStats();
      setRecap(null);
    } catch {
      toast.error("Impossible d'ignorer la question.");
    } finally {
      setDismissingId(null);
    }
  };

  const emptyCopy: Record<StatusFilter, { title: string; description: string }> = {
    open: {
      title: "Jenny a répondu à tout 🎉",
      description:
        "Aucune question en attente. Quand un client posera une question à laquelle Jenny ne sait pas répondre, elle apparaîtra ici.",
    },
    answered: {
      title: "Aucune réponse pour l'instant",
      description: "Les questions auxquelles vous aurez répondu s'afficheront ici.",
    },
    dismissed: {
      title: "Aucune question ignorée",
      description: "Les questions que vous choisissez d'ignorer apparaîtront ici.",
    },
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto p-6 space-y-6">
        {/* ── En-tête ── */}
        <motion.div variants={fadeInUp} initial="hidden" animate="show">
          <div className="font-mono text-[11px] tracking-[0.22em] uppercase text-jenny-coral mb-2">
            — apprentissage —
          </div>
          <h2 className="font-display text-[clamp(28px,4vw,36px)] leading-[1] tracking-[-0.02em] text-jenny-text">
            Ce que Jenny doit <span className="italic text-jenny-coral">apprendre.</span>
          </h2>
          <p className="text-sm text-jenny-text-secondary mt-0.5">
            Répondez aux questions de clients que Jenny n&apos;a pas su traiter. Vos réponses
            enrichissent sa base de connaissances — elle saura répondre la prochaine fois.
          </p>
        </motion.div>

        {/* ── Bandeau de stats ── */}
        {stats && (
          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="show"
            className="grid grid-cols-1 sm:grid-cols-3 gap-3"
          >
            {STAT_CARDS.map((s) => {
              const Icon = s.icon;
              return (
                <motion.div key={s.key} variants={staggerItem} whileHover={{ y: -3 }} transition={springSnappy}>
                  <Card className="p-4 h-full hover:shadow-md hover:shadow-black/[0.04] hover:border-jenny-coral/20">
                    <div className="flex items-center gap-2 text-jenny-text-secondary mb-1">
                      <span className={cn("w-2 h-2 rounded-full", s.dot)} />
                      <Icon className="w-4 h-4" />
                      <span className="text-xs">{s.label}</span>
                    </div>
                    <p className="font-display text-2xl font-bold text-jenny-text tabular-nums">
                      {stats[s.key]}
                    </p>
                  </Card>
                </motion.div>
              );
            })}
          </motion.div>
        )}

        {/* ── Récapitulatif ── */}
        <motion.div variants={fadeInUp} initial="hidden" animate="show" className="space-y-3">
          <Button variant="secondary" onClick={toggleRecap} isLoading={recapLoading}>
            <Sparkles className="w-4 h-4" />
            {recapOpen ? "Masquer le récapitulatif" : "Voir le récapitulatif"}
          </Button>

          <AnimatePresence>
            {recapOpen && !recapLoading && recap && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="overflow-hidden"
              >
                <Card className="p-5">
                  <div className="flex items-center gap-2 mb-3">
                    <Sparkles className="w-4 h-4 text-jenny-coral" />
                    <h3 className="text-sm font-semibold text-jenny-text">
                      Récapitulatif des questions sans réponse
                    </h3>
                    <span className="ml-auto text-[11px] font-mono text-jenny-text-secondary">
                      {recap.total_open} en attente
                    </span>
                  </div>
                  {recap.recap_text.trim() ? (
                    <pre className="whitespace-pre-wrap break-words font-sans text-[13.5px] leading-[1.6] text-jenny-text-secondary">
                      {recap.recap_text}
                    </pre>
                  ) : (
                    <p className="text-sm text-jenny-text-secondary">
                      Rien à récapituler : aucune question en attente.
                    </p>
                  )}
                </Card>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>

        {/* ── Onglets de filtre ── */}
        <motion.div variants={fadeInUp} initial="hidden" animate="show">
          <div className="inline-flex items-center gap-1 p-1 rounded-xl bg-jenny-divider/40">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                onClick={() => setFilter(f.id)}
                className={cn(
                  "px-3.5 h-8 rounded-lg text-[13px] font-medium transition-all",
                  filter === f.id
                    ? "bg-jenny-surface text-jenny-text shadow-sm"
                    : "text-jenny-text-secondary hover:text-jenny-text"
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
        </motion.div>

        {/* ── Liste des lacunes ── */}
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        ) : error ? (
          <ErrorState message={error} onRetry={fetchData} />
        ) : gaps.length === 0 ? (
          <EmptyState
            icon={<MessageCircleQuestion className="w-8 h-8" />}
            title={emptyCopy[filter].title}
            description={emptyCopy[filter].description}
          />
        ) : (
          <div className="grid gap-3">
            <AnimatePresence initial={false}>
              {gaps.map((gap, i) => {
                const isAnswering = answeringId === gap.id;
                const isSubmitting = submittingId === gap.id;
                const isDismissing = dismissingId === gap.id;
                return (
                  <motion.div
                    key={gap.id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, x: -20 }}
                    transition={{ delay: i * 0.03 }}
                  >
                    <Card className="p-5">
                      <div className="flex items-start gap-4">
                        <div className="w-10 h-10 rounded-xl bg-jenny-mint flex items-center justify-center flex-shrink-0">
                          <Lightbulb className="w-5 h-5 text-jenny-coral" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-[14.5px] font-medium text-jenny-text leading-snug">
                            {gap.question}
                          </p>
                          <div className="flex flex-wrap items-center gap-2 mt-2">
                            {gap.channel && (
                              <Badge variant="channel" channel={gap.channel}>
                                {channelLabel(gap.channel)}
                              </Badge>
                            )}
                            {gap.intent && <Badge>{intentLabel(gap.intent)}</Badge>}
                            {gap.occurrences > 1 && (
                              <Badge variant="warning">posée {gap.occurrences} fois</Badge>
                            )}
                            {gap.saved_to_kb && (
                              <Badge variant="success">
                                <BookOpen className="w-3 h-3 mr-1" />
                                dans la base
                              </Badge>
                            )}
                            <span className="inline-flex items-center gap-1 text-[11px] text-jenny-text-secondary/70">
                              <Clock className="w-3 h-3" />
                              {formatRelativeTime(gap.last_seen_at || gap.created_at)}
                            </span>
                          </div>

                          {/* Réponse déjà enregistrée (onglets répondues/ignorées). */}
                          {!isAnswering && gap.answer && (
                            <div className="mt-3 p-3 rounded-xl bg-jenny-bg border border-jenny-divider">
                              <p className="text-[13px] text-jenny-text-secondary whitespace-pre-wrap break-words leading-[1.55]">
                                {gap.answer}
                              </p>
                            </div>
                          )}
                        </div>

                        {/* Actions (cachées pendant la saisie). */}
                        {filter === "open" && !isAnswering && (
                          <div className="flex items-center gap-1 flex-shrink-0">
                            <Button size="sm" onClick={() => openAnswer(gap)}>
                              <Send className="w-3.5 h-3.5" />
                              Répondre
                            </Button>
                            <button
                              onClick={() => handleDismiss(gap)}
                              disabled={isDismissing}
                              aria-label="Ignorer la question"
                              title="Ignorer"
                              className="p-2 rounded-lg text-jenny-text-secondary hover:text-jenny-error hover:bg-jenny-error/10 transition-all disabled:opacity-50"
                            >
                              <Trash className={cn("w-4 h-4", isDismissing && "animate-pulse")} />
                            </button>
                          </div>
                        )}
                      </div>

                      {/* ── Formulaire de réponse ── */}
                      <AnimatePresence>
                        {isAnswering && (
                          <motion.div
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: "auto" }}
                            exit={{ opacity: 0, height: 0 }}
                            className="overflow-hidden"
                          >
                            <div className="mt-4 pt-4 border-t border-jenny-divider/60 space-y-3">
                              <textarea
                                value={answerDraft}
                                onChange={(e) => setAnswerDraft(e.target.value)}
                                placeholder="Rédigez la réponse que Jenny donnera à cette question…"
                                rows={4}
                                autoFocus
                                className="w-full px-3.5 py-3 rounded-[10px] bg-jenny-bg border border-jenny-divider text-[13.5px] text-jenny-text leading-[1.5] placeholder:text-jenny-text-secondary/50 focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral transition-all resize-y min-h-[96px]"
                              />
                              <label className="flex items-center gap-2.5 cursor-pointer select-none w-fit">
                                <input
                                  type="checkbox"
                                  checked={saveToKb}
                                  onChange={(e) => setSaveToKb(e.target.checked)}
                                  className="w-4 h-4 rounded border-jenny-divider text-jenny-coral accent-jenny-coral focus:ring-2 focus:ring-jenny-coral/30 cursor-pointer"
                                />
                                <span className="inline-flex items-center gap-1.5 text-[13px] text-jenny-text">
                                  <BookOpen className="w-3.5 h-3.5 text-jenny-text-secondary" />
                                  Enregistrer dans la base de connaissances
                                </span>
                              </label>
                              <div className="flex items-center gap-2">
                                <Button
                                  size="sm"
                                  onClick={() => submitAnswer(gap)}
                                  isLoading={isSubmitting}
                                  disabled={!answerDraft.trim()}
                                >
                                  <Check className="w-3.5 h-3.5" />
                                  Enregistrer
                                </Button>
                                <Button size="sm" variant="ghost" onClick={closeAnswer} disabled={isSubmitting}>
                                  <X className="w-3.5 h-3.5" />
                                  Annuler
                                </Button>
                              </div>
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>

                      {/* ── Avertissement KB indisponible ── */}
                      {kbWarningId === gap.id && (
                        <div className="mt-3 p-2.5 rounded-xl bg-jenny-warning/10 text-jenny-warning text-[12.5px] flex items-start gap-2">
                          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-px" />
                          <span>
                            Réponse enregistrée. L&apos;ajout à la base se fera quand le service de
                            connaissances sera disponible.
                          </span>
                        </div>
                      )}
                    </Card>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </div>
        )}
      </div>
    </div>
  );
}

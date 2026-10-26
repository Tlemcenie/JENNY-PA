"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { motion } from "framer-motion";
import {
  CalendarClock,
  Crown,
  Hourglass,
  Megaphone,
  Moon,
  RefreshCw,
  Send,
  Sparkles,
  TrendingUp,
  UserPlus,
  UserX,
  Users,
  Wallet,
} from "lucide-react";
import { ApiError } from "@/lib/api";
import {
  getCampaignHistory,
  getGaps,
  listSegments,
  previewSegment,
  renderCampaignMessage,
  runGapFiller,
  sendCampaign,
  type Campaign,
  type CampaignHistory,
  type GapsOverview,
  type RenderedMessage,
  type Segment,
  type SegmentKey,
  type SegmentPreview,
} from "@/lib/api-campaigns";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { cn } from "@/lib/utils";
import { springSnappy, staggerContainer, staggerItem } from "@/lib/motion";

// icône + teinte par segment
const SEGMENT_STYLE: Record<SegmentKey, { icon: ReactNode; tint: string }> = {
  dormants: { icon: <Moon className="w-5 h-5" />, tint: "#7284A8" },
  no_shows: { icon: <UserX className="w-5 h-5" />, tint: "#F59E0B" },
  nouveaux: { icon: <UserPlus className="w-5 h-5" />, tint: "#10B981" },
  fideles: { icon: <Crown className="w-5 h-5" />, tint: "#FF7F6A" },
};

const MIN_LEN = 10;
const MAX_LEN = 600;

function errorText(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    const detail = (err.data as { detail?: unknown })?.detail;
    if (typeof detail === "string") return detail;
    return `Erreur ${err.status}`;
  }
  return fallback;
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n > 1 ? many : one}`;
}

function daysAgo(iso: string | null): string {
  if (!iso) return "jamais venue";
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (d <= 0) return "aujourd'hui";
  return d === 1 ? "hier" : `il y a ${d} j`;
}

function shortDate(iso: string): string {
  return new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" }).format(
    new Date(iso)
  );
}

// « demain à 10h30 » -> par jour
function groupByDay(gaps: { label: string }[]): [string, string[]][] {
  const out = new Map<string, string[]>();
  for (const g of gaps) {
    const [day, hour] = g.label.split(" à ");
    if (!out.has(day)) out.set(day, []);
    out.get(day)!.push(hour ?? g.label);
  }
  return [...out.entries()];
}

function euros(v: number): string {
  return new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(v);
}

// petit titre mono
function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <div className="font-mono text-[11px] tracking-[0.22em] uppercase text-jenny-coral mb-2">
      {children}
    </div>
  );
}

function Kpi({
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
    <motion.div variants={staggerItem} whileHover={{ y: -3 }} transition={springSnappy}>
      <Card className="p-5 h-full">
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center mb-3"
          style={{ backgroundColor: `${tint}1a`, color: tint }}
        >
          {icon}
        </div>
        <p className="font-display text-[1.5rem] font-bold text-jenny-text tabular-nums leading-tight">
          {value}
        </p>
        <p className="text-xs text-jenny-text-secondary mt-0.5">{label}</p>
        {sub && <p className="text-[11px] text-jenny-text-secondary/70 mt-1">{sub}</p>}
      </Card>
    </motion.div>
  );
}

// ── trous d'agenda ──

function GapsCard({
  data,
  loading,
  running,
  onRun,
}: {
  data: GapsOverview | null;
  loading: boolean;
  running: boolean;
  onRun: () => void;
}) {
  return (
    <Card className="p-5 md:p-6">
      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <CalendarClock className="w-4 h-4 text-jenny-coral" />
            <h2 className="font-semibold text-jenny-text">Trous d&apos;agenda — aujourd&apos;hui et demain</h2>
          </div>
          <p className="text-[13px] text-jenny-text-secondary leading-relaxed max-w-2xl">
            Jenny propose les places libres d&apos;abord à la liste d&apos;attente, puis aux
            clientes dont la relance est due. Automatique chaque matin et après une
            annulation · jamais plus d&apos;une offre par cliente et par semaine · rien
            entre 20h et 9h.
          </p>
        </div>
        <button
          onClick={onRun}
          disabled={running || loading || !data || data.planned.length === 0}
          className="shrink-0 inline-flex items-center justify-center gap-2 h-10 px-4 rounded-xl bg-jenny-coral text-white text-sm font-semibold hover:bg-jenny-coral-dark disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <Sparkles className={cn("w-4 h-4", running && "animate-pulse")} />
          {running ? "Envoi…" : "Remplir maintenant"}
        </button>
      </div>

      {loading || !data ? (
        <div className="mt-5 space-y-2">
          <Skeleton className="h-6 w-2/3" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : (
        <div className="mt-5 grid grid-cols-1 lg:grid-cols-2 gap-5">
          <div>
            <p className="text-xs font-medium text-jenny-text-secondary mb-2">
              {data.gaps.length === 0
                ? "Aucun créneau libre : l'agenda est plein."
                : `${plural(data.gaps.length, "créneau libre", "créneaux libres")} (30 min)`}
            </p>
            <div className="space-y-2">
              {groupByDay(data.gaps).map(([day, hours]) => (
                <div key={day} className="flex items-start gap-2">
                  <span className="w-20 shrink-0 text-[11px] font-semibold text-jenny-text capitalize pt-1">
                    {day}
                  </span>
                  <div className="flex flex-wrap gap-1">
                    {hours.slice(0, 12).map((h) => (
                      <span
                        key={h}
                        className="font-mono text-[11px] px-1.5 py-0.5 rounded-md bg-jenny-bg-tint text-jenny-text"
                      >
                        {h}
                      </span>
                    ))}
                    {hours.length > 12 && (
                      <span className="text-[11px] px-1 py-0.5 text-jenny-text-secondary">
                        +{hours.length - 12}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <p className="text-[11px] text-jenny-text-secondary mt-3">
              7 derniers jours : {plural(data.sent_7d, "offre envoyée", "offres envoyées")} ·{" "}
              <span className="text-jenny-success font-semibold">
                {plural(data.filled_7d, "place remplie", "places remplies")}
              </span>
              {data.failed_7d > 0 && ` · ${data.failed_7d} non distribuée(s)`}
            </p>
          </div>
          <div>
            <p className="text-xs font-medium text-jenny-text-secondary mb-2">
              {data.planned.length === 0
                ? `Personne à prévenir pour l'instant (${plural(data.candidates, "candidate", "candidates")}).`
                : "Jenny proposerait :"}
            </p>
            <ul className="space-y-1.5">
              {data.planned.map((p) => (
                <li
                  key={`${p.name}-${p.slot_start}`}
                  className="flex items-center justify-between gap-3 text-[13px] rounded-xl border border-jenny-divider px-3 py-2"
                >
                  <span className="min-w-0">
                    <span className="font-medium text-jenny-text truncate block">{p.name}</span>
                    <span className="text-[11px] text-jenny-text-secondary truncate block">
                      {p.service ?? "prestation habituelle"} · {p.duration_minutes} min
                    </span>
                  </span>
                  <span className="flex flex-col items-end gap-1 shrink-0">
                    <span className="font-mono text-[11px] text-jenny-text">{p.label}</span>
                    <span
                      className={cn(
                        "text-[10px] font-semibold rounded-full px-2 py-0.5",
                        p.source === "waitlist"
                          ? "bg-jenny-coral/10 text-jenny-coral"
                          : "bg-jenny-mint text-jenny-text"
                      )}
                    >
                      {p.source === "waitlist" ? "liste d'attente" : "relance due"}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
            {!data.in_send_hours && data.planned.length > 0 && (
              <p className="text-[11px] text-jenny-warning mt-2">
                Hors des heures d&apos;envoi automatique : le bouton envoie quand même.
              </p>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

// ── carte segment ──

function SegmentCard({
  seg,
  active,
  onClick,
}: {
  seg: Segment;
  active: boolean;
  onClick: () => void;
}) {
  const style = SEGMENT_STYLE[seg.key];
  return (
    <motion.button
      variants={staggerItem}
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "text-left bg-jenny-surface border rounded-2xl p-4 transition-all",
        active
          ? "border-jenny-coral shadow-md shadow-jenny-coral/10"
          : "border-jenny-divider hover:border-jenny-coral/40"
      )}
    >
      <div className="flex items-center justify-between">
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center"
          style={{ backgroundColor: `${style.tint}1a`, color: style.tint }}
        >
          {style.icon}
        </div>
        <span className="font-display text-2xl font-bold tabular-nums text-jenny-text">
          {seg.count}
        </span>
      </div>
      <p className="font-semibold text-jenny-text mt-3">{seg.label}</p>
      <p className="text-xs text-jenny-text-secondary mt-0.5 leading-snug">{seg.description}</p>
      <p className="text-[11px] text-jenny-text-secondary/80 mt-2">
        {seg.reachable} joignable{seg.reachable > 1 ? "s" : ""} ·{" "}
        <span className="text-jenny-text font-medium">
          {seg.eligible} contactable{seg.eligible > 1 ? "s" : ""}
        </span>{" "}
        cette semaine
      </p>
    </motion.button>
  );
}

// ── ligne d'historique ──

function HistoryRow({ c }: { c: Campaign }) {
  const pct = c.sent_count > 0 ? Math.round((100 * c.returned_count) / c.sent_count) : 0;
  return (
    <li className="py-4 first:pt-0 last:pb-0">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-jenny-text text-sm">{c.segment_label}</span>
            <span className="text-[11px] text-jenny-text-secondary">{shortDate(c.created_at)}</span>
            {c.status === "sending" ? (
              <span className="text-[10px] font-semibold rounded-full px-2 py-0.5 bg-jenny-warning/15 text-jenny-warning">
                envoi en cours
              </span>
            ) : c.window_open ? (
              <span className="text-[10px] font-semibold rounded-full px-2 py-0.5 bg-jenny-mint text-jenny-text">
                suivi jusqu&apos;au {shortDate(c.window_ends_at)}
              </span>
            ) : (
              <span className="text-[10px] font-semibold rounded-full px-2 py-0.5 bg-jenny-bg-tint text-jenny-text-secondary">
                suivi terminé
              </span>
            )}
          </div>
          <p className="text-[13px] text-jenny-text-secondary mt-1 line-clamp-2">{c.message}</p>
        </div>
        <div className="sm:text-right shrink-0">
          <p className="text-sm text-jenny-text">
            <span className="font-bold text-jenny-success tabular-nums">{c.returned_count}</span>{" "}
            cliente{c.returned_count > 1 ? "s" : ""} revenue{c.returned_count > 1 ? "s" : ""} sur{" "}
            <span className="font-semibold tabular-nums">{c.sent_count}</span> relancée
            {c.sent_count > 1 ? "s" : ""}
          </p>
          <p className="text-[11px] text-jenny-text-secondary mt-0.5">
            {c.revenue_eur > 0 && `${euros(c.revenue_eur)} de RDV · `}
            {c.skipped_count > 0 && `${c.skipped_count} non contactée(s)`}
          </p>
        </div>
      </div>
      <div className="h-1.5 rounded-full bg-jenny-bg-tint overflow-hidden mt-2.5">
        <motion.div
          className="h-full rounded-full bg-jenny-success"
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6 }}
        />
      </div>
    </li>
  );
}

export default function CampaignsPage() {
  const toast = useToast();
  const confirm = useConfirm();

  const [segments, setSegments] = useState<Segment[]>([]);
  const [history, setHistory] = useState<CampaignHistory | null>(null);
  const [gaps, setGaps] = useState<GapsOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [gapsLoading, setGapsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selected, setSelected] = useState<SegmentKey | null>(null);
  const [preview, setPreview] = useState<SegmentPreview | null>(null);
  const [message, setMessage] = useState("");
  const [rendered, setRendered] = useState<RenderedMessage | null>(null);
  const [sending, setSending] = useState(false);
  const [running, setRunning] = useState(false);
  const textRef = useRef<HTMLTextAreaElement>(null);

  const loadAll = useCallback(async () => {
    setError(null);
    try {
      const [segs, hist] = await Promise.all([listSegments(), getCampaignHistory()]);
      setSegments(segs);
      setHistory(hist);
    } catch (err) {
      setError(errorText(err, "Impossible de charger les relances."));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadGaps = useCallback(async () => {
    setGapsLoading(true);
    try {
      setGaps(await getGaps());
    } catch {
      setGaps(null);
    } finally {
      setGapsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
    loadGaps();
  }, [loadAll, loadGaps]);

  // suivi d'un envoi en cours
  const sendingNow = history?.campaigns.some((c) => c.status === "sending");
  useEffect(() => {
    if (!sendingNow) return;
    const t = setInterval(() => {
      getCampaignHistory()
        .then(setHistory)
        .catch(() => undefined);
    }, 3000);
    return () => clearInterval(t);
  }, [sendingNow]);

  // choix d'un segment
  const pick = useCallback(
    async (key: SegmentKey) => {
      setSelected(key);
      setPreview(null);
      const seg = segments.find((s) => s.key === key);
      setMessage(seg?.suggestion ?? "");
      try {
        setPreview(await previewSegment(key));
      } catch (err) {
        toast.error(errorText(err, "Aperçu indisponible."));
      }
    },
    [segments, toast]
  );

  // aperçu du texte final
  useEffect(() => {
    if (message.trim().length < MIN_LEN) {
      setRendered(null);
      return;
    }
    const first = preview?.sample.find((s) => s.eligible)?.name.split(" ")[0];
    const t = setTimeout(() => {
      renderCampaignMessage(message, first)
        .then(setRendered)
        .catch(() => setRendered(null));
    }, 350);
    return () => clearTimeout(t);
  }, [message, preview]);

  const insertPrenom = () => {
    const el = textRef.current;
    const tag = "{prenom}";
    if (!el) {
      setMessage((m) => m + tag);
      return;
    }
    const start = el.selectionStart ?? message.length;
    const end = el.selectionEnd ?? message.length;
    const next = message.slice(0, start) + tag + message.slice(end);
    setMessage(next.slice(0, MAX_LEN));
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(start + tag.length, start + tag.length);
    });
  };

  const current = useMemo(
    () => segments.find((s) => s.key === selected) ?? null,
    [segments, selected]
  );
  const canSend =
    !!current && current.eligible > 0 && message.trim().length >= MIN_LEN && !sending;

  const handleSend = async () => {
    if (!current) return;
    const ok = await confirm({
      title: `Relancer ${plural(current.eligible, "cliente", "clientes")} ?`,
      message:
        `Segment « ${current.label} ». Les clientes déjà sollicitées cette semaine, ` +
        "désinscrites (STOP) ou sans contact sont ignorées automatiquement.",
      confirmLabel: "Envoyer",
    });
    if (!ok) return;
    setSending(true);
    try {
      await sendCampaign(current.key, message);
      toast.success("C'est parti : Jenny envoie la relance.");
      setSelected(null);
      setPreview(null);
      setMessage("");
      await loadAll();
    } catch (err) {
      toast.error(errorText(err, "Envoi impossible."));
    } finally {
      setSending(false);
    }
  };

  const handleRun = async () => {
    const n = gaps?.planned.length ?? 0;
    const ok = await confirm({
      title: `Proposer ${plural(n, "place", "places")} maintenant ?`,
      message: "Chaque cliente reçoit un message avec le lien de réservation.",
      confirmLabel: "Proposer",
    });
    if (!ok) return;
    setRunning(true);
    try {
      const res = await runGapFiller();
      if (res.sent > 0) toast.success(`${plural(res.sent, "offre envoyée", "offres envoyées")}.`);
      else if (res.failed > 0) toast.warning("Aucun message n'a pu partir (canaux non configurés ?).");
      else toast.info("Rien à proposer pour le moment.");
      await loadGaps();
    } catch (err) {
      toast.error(errorText(err, "Remplissage impossible."));
    } finally {
      setRunning(false);
    }
  };

  const summary = history?.summary;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-6xl mx-auto p-4 md:p-6 space-y-6">
        {/* en-tête */}
        <div className="flex items-start justify-between gap-3">
          <div>
            <Eyebrow>— relances —</Eyebrow>
            <h1 className="font-display text-[clamp(28px,4vw,36px)] leading-[1] tracking-[-0.02em] text-jenny-text">
              Faites <span className="italic text-jenny-coral">revenir</span> vos clientes.
            </h1>
            <p className="text-sm text-jenny-text-secondary mt-1.5">
              Remplissez les trous d&apos;agenda et relancez les bonnes personnes, sans jamais
              les harceler.
            </p>
          </div>
          <button
            onClick={() => {
              loadAll();
              loadGaps();
            }}
            title="Rafraîchir"
            aria-label="Rafraîchir"
            className="p-2 rounded-lg text-jenny-text-secondary hover:text-jenny-coral hover:bg-jenny-coral/10 transition-colors"
          >
            <RefreshCw className={cn("w-4 h-4", (loading || gapsLoading) && "animate-spin")} />
          </button>
        </div>

        {error ? (
          <ErrorState message={error} onRetry={loadAll} />
        ) : (
          <>
            {/* chiffres clés */}
            <motion.div
              variants={staggerContainer}
              initial="hidden"
              animate="show"
              className="grid grid-cols-2 lg:grid-cols-4 gap-3"
            >
              <Kpi
                icon={<Megaphone className="w-4 h-4" />}
                label="clientes relancées"
                value={summary?.sent ?? (loading ? "…" : 0)}
                sub={summary ? plural(summary.campaigns, "campagne", "campagnes") : undefined}
                tint="#7284A8"
              />
              <Kpi
                icon={<TrendingUp className="w-4 h-4" />}
                label="revenues dans les 30 jours"
                value={summary?.returned ?? (loading ? "…" : 0)}
                sub={summary && summary.sent > 0 ? `${summary.return_rate_pct} % de retour` : undefined}
                tint="#10B981"
              />
              <Kpi
                icon={<Wallet className="w-4 h-4" />}
                label="de RDV ramenés"
                value={summary ? euros(summary.revenue_eur) : "…"}
                sub="estimé avec vos tarifs"
              />
              <Kpi
                icon={<Hourglass className="w-4 h-4" />}
                label="places remplies (7 j)"
                value={gaps ? gaps.filled_7d : "…"}
                sub={gaps ? `sur ${plural(gaps.sent_7d, "offre", "offres")}` : undefined}
                tint="#F59E0B"
              />
            </motion.div>

            {/* trous d'agenda */}
            <GapsCard data={gaps} loading={gapsLoading} running={running} onRun={handleRun} />

            {/* segments */}
            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <Users className="w-4 h-4 text-jenny-coral" />
                <h2 className="font-semibold text-jenny-text">Lancer une relance</h2>
              </div>
              {loading ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <Skeleton key={i} className="h-40 rounded-2xl" />
                  ))}
                </div>
              ) : (
                <motion.div
                  variants={staggerContainer}
                  initial="hidden"
                  animate="show"
                  className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3"
                >
                  {segments.map((s) => (
                    <SegmentCard
                      key={s.key}
                      seg={s}
                      active={selected === s.key}
                      onClick={() => pick(s.key)}
                    />
                  ))}
                </motion.div>
              )}

              {current && (
                <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                  <Card className="p-5 md:p-6">
                    <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
                      {/* rédaction */}
                      <div className="lg:col-span-3 space-y-3">
                        <div className="flex items-center justify-between gap-2">
                          <label htmlFor="campaign-msg" className="text-sm font-medium text-jenny-text">
                            Message pour « {current.label} »
                          </label>
                          <button
                            onClick={insertPrenom}
                            className="font-mono text-[11px] px-2 py-1 rounded-lg bg-jenny-coral/10 text-jenny-coral hover:bg-jenny-coral/20 transition-colors"
                          >
                            + {"{prenom}"}
                          </button>
                        </div>
                        <textarea
                          id="campaign-msg"
                          ref={textRef}
                          value={message}
                          maxLength={MAX_LEN}
                          onChange={(e) => setMessage(e.target.value)}
                          rows={5}
                          className="w-full p-3 rounded-xl bg-jenny-bg border border-jenny-divider text-sm text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:ring-2 focus:ring-jenny-coral/30 focus:border-jenny-coral transition-all resize-y"
                          placeholder="Bonjour {prenom}, …"
                        />
                        <div className="flex items-center justify-between text-[11px] text-jenny-text-secondary">
                          <span>
                            {message.length}/{MAX_LEN}
                            {rendered && ` · ≈ ${plural(rendered.sms_parts, "SMS", "SMS")} par cliente`}
                          </span>
                          <span>Signature et « STOP » ajoutés automatiquement</span>
                        </div>
                        {rendered?.unicode && (
                          <p className="text-[11px] text-jenny-warning">
                            Caractères spéciaux (ç, ê, emoji…) : le SMS est découpé plus tôt et
                            coûte plus cher.
                          </p>
                        )}
                        {rendered && (
                          <div className="rounded-2xl bg-jenny-bg-tint p-3">
                            <p className="text-[11px] font-medium text-jenny-text-secondary mb-1.5">
                              Ce que reçoit la cliente
                            </p>
                            <p className="text-[13px] text-jenny-text whitespace-pre-line leading-relaxed bg-jenny-surface rounded-xl rounded-tl-sm px-3 py-2 border border-jenny-divider">
                              {rendered.text}
                            </p>
                          </div>
                        )}
                        <button
                          onClick={handleSend}
                          disabled={!canSend}
                          className="inline-flex items-center gap-2 h-10 px-4 rounded-xl bg-jenny-coral text-white text-sm font-semibold hover:bg-jenny-coral-dark disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                          <Send className="w-4 h-4" />
                          {sending
                            ? "Envoi…"
                            : current.eligible > 0
                              ? `Envoyer à ${plural(current.eligible, "cliente", "clientes")}`
                              : "Personne à contacter cette semaine"}
                        </button>
                      </div>

                      {/* échantillon */}
                      <div className="lg:col-span-2">
                        <p className="text-sm font-medium text-jenny-text mb-2">
                          {plural(current.count, "personne", "personnes")} dans ce segment
                        </p>
                        {!preview ? (
                          <div className="space-y-2">
                            {Array.from({ length: 4 }).map((_, i) => (
                              <Skeleton key={i} className="h-10 w-full" />
                            ))}
                          </div>
                        ) : preview.sample.length === 0 ? (
                          <p className="text-[13px] text-jenny-text-secondary">
                            Personne pour l&apos;instant : bonne nouvelle !
                          </p>
                        ) : (
                          <ul className="space-y-1.5">
                            {preview.sample.map((s) => (
                              <li
                                key={s.id}
                                className="flex items-center justify-between gap-2 text-[13px] rounded-xl border border-jenny-divider px-3 py-2"
                              >
                                <span className="min-w-0">
                                  <span className="font-medium text-jenny-text truncate block">
                                    {s.name}
                                  </span>
                                  <span className="text-[11px] text-jenny-text-secondary">
                                    {plural(s.visits, "visite", "visites")} · {daysAgo(s.last_visit_at)}
                                    {s.no_shows > 0 && ` · ${s.no_shows} manqué(s)`}
                                  </span>
                                </span>
                                {!s.reachable ? (
                                  <span className="shrink-0 text-[10px] rounded-full px-2 py-0.5 bg-jenny-bg-tint text-jenny-text-secondary">
                                    injoignable
                                  </span>
                                ) : !s.eligible ? (
                                  <span className="shrink-0 text-[10px] rounded-full px-2 py-0.5 bg-jenny-warning/15 text-jenny-warning">
                                    déjà sollicitée
                                  </span>
                                ) : (
                                  <span className="shrink-0 text-[10px] rounded-full px-2 py-0.5 bg-jenny-mint text-jenny-text">
                                    ok
                                  </span>
                                )}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </div>
                  </Card>
                </motion.div>
              )}
            </section>

            {/* historique */}
            <section className="space-y-3">
              <h2 className="font-semibold text-jenny-text">Historique et résultats</h2>
              {loading ? (
                <Skeleton className="h-32 rounded-2xl" />
              ) : !history || history.campaigns.length === 0 ? (
                <Card className="p-2">
                  <EmptyState
                    icon={<Megaphone className="w-7 h-7" />}
                    title="Aucune relance pour l'instant"
                    description="Choisissez un segment ci-dessus. Jenny compte ensuite les clientes revenues dans les 30 jours."
                  />
                </Card>
              ) : (
                <Card className="p-5 md:p-6">
                  <ul className="divide-y divide-jenny-divider">
                    {history.campaigns.map((c) => (
                      <HistoryRow key={c.id} c={c} />
                    ))}
                  </ul>
                </Card>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}

"use client";

import { useEffect, useState, useCallback, type ReactNode } from "react";
import { motion } from "framer-motion";
import {
  Calendar,
  TrendingUp,
  Scissors,
  Clock,
  Wallet,
  Users,
  Trophy,
  UserPlus,
  Hourglass,
  CreditCard,
  Star,
  UserX,
} from "lucide-react";
import { getSalonStats, type SalonStats, ApiError } from "@/lib/api";
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

// Plages de temps proposées au commerçant (en jours).
const RANGES: { days: number; label: string }[] = [
  { days: 30, label: "30 jours" },
  { days: 90, label: "90 jours" },
  { days: 365, label: "1 an" },
];

// Met une majuscule sur la première lettre (jour de la semaine renvoyé par le back).
function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ── Eyebrow mono (cf. DA dashboard / analytics) ──
function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <div className="font-mono text-[11px] tracking-[0.22em] uppercase text-jenny-coral mb-2">
      {children}
    </div>
  );
}

// ── Carte KPI (style StatCard de la DA efficacité) ──
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

// ── Barre horizontale (name + count), mise à l'échelle sur le max ──
function MetricBar({
  label,
  value,
  max,
  index,
  display,
}: {
  label: string;
  value: number;
  max: number;
  index: number;
  display?: string;
}) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 mb-1.5">
        <span className="text-[13px] text-jenny-text truncate">{label}</span>
        <span className="font-mono text-[11.5px] font-semibold tabular-nums text-jenny-text-secondary shrink-0">
          {display ?? value}
        </span>
      </div>
      <div className="h-2 rounded-full bg-jenny-bg-tint overflow-hidden">
        <motion.div
          className="h-full rounded-full bg-jenny-coral"
          style={{ transformOrigin: "left" }}
          initial={{ scaleX: 0 }}
          animate={{ scaleX: pct / 100 }}
          transition={{ duration: 0.6, ease: easeOutExpo, delay: 0.15 + index * 0.06 }}
        />
      </div>
    </div>
  );
}

// ── Squelette de chargement (miroir de la page efficacité) ──
function StatsSkeleton() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto p-6 space-y-6">
        <div className="space-y-2">
          <Skeleton className="h-3 w-32" />
          <Skeleton className="h-10 w-72" />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i} className="p-5">
              <Skeleton className="h-10 w-10 rounded-xl mb-3" />
              <Skeleton className="h-7 w-20 mb-1.5" />
              <Skeleton className="h-3 w-24" />
            </Card>
          ))}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Skeleton className="h-56 w-full rounded-2xl" />
          <Skeleton className="h-56 w-full rounded-2xl" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Skeleton className="h-40 w-full rounded-2xl" />
          <Skeleton className="h-40 w-full rounded-2xl" />
        </div>
      </div>
    </div>
  );
}

export default function StatsPage() {
  const [stats, setStats] = useState<SalonStats | null>(null);
  const [rangeDays, setRangeDays] = useState(30);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStats = useCallback(async (days: number) => {
    setIsLoading(true);
    setError(null);
    try {
      setStats(await getSalonStats(days));
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          `Erreur ${err.status}: ${
            (err.data as { detail?: string })?.detail || err.statusText
          }`
        );
      } else {
        setError(
          "Impossible de charger les statistiques du salon. Vérifiez que le backend est démarré."
        );
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStats(rangeDays);
  }, [fetchStats, rangeDays]);

  if (isLoading && !stats) return <StatsSkeleton />;

  if (error) {
    return (
      <div className="h-full overflow-y-auto">
        <div className="max-w-5xl mx-auto p-6">
          <ErrorState message={error} onRetry={() => fetchStats(rangeDays)} />
        </div>
      </div>
    );
  }

  if (!stats) return null;

  const maxPrestation = stats.top_prestations.reduce((m, p) => Math.max(m, p.count), 0);
  const maxHour = stats.peak_hours.reduce((m, h) => Math.max(m, h.count), 0);
  const sortedHours = [...stats.peak_hours].sort((a, b) => a.hour - b.hour);

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto p-6 space-y-6">
        {/* ── En-tête + sélecteur de plage ── */}
        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: easeOutExpo }}
          className="flex flex-wrap items-start justify-between gap-4"
        >
          <div>
            <Eyebrow>— Statistiques —</Eyebrow>
            <h1 className="font-display text-[clamp(28px,4vw,36px)] leading-[1] tracking-[-0.02em] text-jenny-text">
              Votre salon en <span className="italic text-jenny-coral">chiffres.</span>
            </h1>
            <p className="text-sm text-jenny-text-secondary mt-1">
              L&apos;activité réelle de votre salon, mesurée sur la période choisie.
            </p>
          </div>

          {/* Sélecteur de plage (30 / 90 / 365 jours) */}
          <div className="flex items-center gap-1 p-1 rounded-xl bg-jenny-bg-tint border border-jenny-divider">
            {RANGES.map((r) => {
              const active = r.days === rangeDays;
              return (
                <button
                  key={r.days}
                  onClick={() => setRangeDays(r.days)}
                  className={
                    active
                      ? "px-3 py-1.5 rounded-lg text-[12.5px] font-semibold bg-jenny-coral text-white transition-colors"
                      : "px-3 py-1.5 rounded-lg text-[12.5px] font-medium text-jenny-text-secondary hover:text-jenny-text transition-colors"
                  }
                >
                  {r.label}
                </button>
              );
            })}
          </div>
        </motion.div>

        {/* ── Cartes KPI ── */}
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="grid grid-cols-2 sm:grid-cols-3 gap-3"
        >
          <StatCard
            icon={<Calendar className="w-5 h-5" />}
            tint="#FF7F6A"
            label="RDV à venir"
            value={<AnimatedNumber value={stats.upcoming} />}
          />
          <StatCard
            icon={<TrendingUp className="w-5 h-5" />}
            tint="#22C55E"
            label="Taux de remplissage"
            value={
              <AnimatedNumber
                value={stats.fill_rate_pct}
                format={(n) => `${Math.round(n)}%`}
              />
            }
          />
          <StatCard
            icon={<Clock className="w-5 h-5" />}
            tint="#F59E0B"
            label="Taux d'annulation"
            value={
              <AnimatedNumber
                value={stats.cancellation_rate_pct}
                format={(n) => `${Math.round(n)}%`}
              />
            }
          />
          <StatCard
            icon={<Wallet className="w-5 h-5" />}
            tint="#3B82F6"
            label="CA estimé à venir"
            value={
              <AnimatedNumber
                value={stats.revenue_upcoming_eur}
                format={(n) => `${Math.round(n).toLocaleString("fr-FR")} €`}
              />
            }
          />
          <StatCard
            icon={<Trophy className="w-5 h-5" />}
            tint="#8B5CF6"
            label="Clients fidèles"
            value={<AnimatedNumber value={stats.loyal_clients} />}
            sub={`${stats.clients_total} client${stats.clients_total > 1 ? "s" : ""} au total`}
          />
          <StatCard
            icon={<UserPlus className="w-5 h-5" />}
            tint="#EC4899"
            label="Nouveaux clients"
            value={<AnimatedNumber value={stats.new_clients} />}
          />
          <StatCard
            icon={<Star className="w-5 h-5" />}
            tint="#FACC15"
            label="Note moyenne"
            value={
              stats.average_rating === null ? (
                <span className="text-[0.95rem] font-semibold text-jenny-text-secondary">
                  Pas encore d&apos;avis
                </span>
              ) : (
                <AnimatedNumber
                  value={stats.average_rating}
                  format={(n) => `${n.toFixed(1)}/5`}
                />
              )
            }
            sub={
              stats.average_rating === null
                ? undefined
                : `${stats.reviews_count} avis`
            }
          />
          <StatCard
            icon={<UserX className="w-5 h-5" />}
            tint="#EF4444"
            label="Absences (no-show)"
            value={<AnimatedNumber value={stats.no_show} />}
          />
        </motion.div>

        {/* ── Prestations populaires + Heures de pointe ── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {/* (a) Prestations populaires */}
          <motion.div variants={fadeInUp} initial="hidden" animate="show">
            <Card className="p-6 h-full flex flex-col">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-9 h-9 rounded-xl bg-jenny-coral/10 text-jenny-coral flex items-center justify-center">
                  <Scissors className="w-[18px] h-[18px]" />
                </div>
                <h2 className="font-semibold text-jenny-text text-sm">Prestations populaires</h2>
              </div>

              {stats.top_prestations.length === 0 ? (
                <div className="flex-1 flex items-center text-[13px] text-jenny-text-secondary">
                  Pas encore de données
                </div>
              ) : (
                <div className="flex flex-col gap-3.5">
                  {stats.top_prestations.map((p, i) => (
                    <MetricBar
                      key={`${i}-${p.name}`}
                      label={p.name}
                      value={p.count}
                      max={maxPrestation}
                      index={i}
                    />
                  ))}
                </div>
              )}
            </Card>
          </motion.div>

          {/* (b) Heures de pointe */}
          <motion.div variants={fadeInUp} initial="hidden" animate="show">
            <Card className="p-6 h-full flex flex-col">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-9 h-9 rounded-xl bg-jenny-coral/10 text-jenny-coral flex items-center justify-center">
                  <Clock className="w-[18px] h-[18px]" />
                </div>
                <h2 className="font-semibold text-jenny-text text-sm">Heures de pointe</h2>
              </div>

              {sortedHours.length === 0 ? (
                <div className="flex-1 flex items-center text-[13px] text-jenny-text-secondary">
                  Pas encore de données
                </div>
              ) : (
                <div className="flex flex-col gap-3.5">
                  {sortedHours.map((h, i) => (
                    <MetricBar
                      key={h.hour}
                      label={`${h.hour}h`}
                      value={h.count}
                      max={maxHour}
                      index={i}
                    />
                  ))}
                </div>
              )}

              {stats.busiest_day && (
                <div className="mt-auto pt-4 border-t border-jenny-divider/70 flex items-center gap-2">
                  <Calendar className="w-4 h-4 text-jenny-coral shrink-0" />
                  <span className="text-[12.5px] text-jenny-text-secondary leading-snug">
                    Jour le plus chargé&nbsp;:{" "}
                    <b className="text-jenny-text">{capitalize(stats.busiest_day)}</b>
                  </span>
                </div>
              )}
            </Card>
          </motion.div>
        </div>

        {/* ── Acomptes + Liste d'attente ── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {/* (a) Acomptes */}
          <motion.div variants={fadeInUp} initial="hidden" animate="show">
            <Card className="p-6 h-full flex flex-col">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-9 h-9 rounded-xl bg-jenny-coral/10 text-jenny-coral flex items-center justify-center">
                  <CreditCard className="w-[18px] h-[18px]" />
                </div>
                <h2 className="font-semibold text-jenny-text text-sm">Acomptes</h2>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <div className="font-display text-[1.5rem] font-bold text-jenny-text tabular-nums leading-none">
                    <AnimatedNumber value={stats.deposits.paid} />
                  </div>
                  <div className="text-[11px] text-jenny-text-secondary mt-1 leading-snug">
                    Payés
                  </div>
                </div>
                <div>
                  <div className="font-display text-[1.5rem] font-bold text-jenny-text tabular-nums leading-none">
                    <AnimatedNumber value={stats.deposits.pending} />
                  </div>
                  <div className="text-[11px] text-jenny-text-secondary mt-1 leading-snug">
                    En attente
                  </div>
                </div>
                <div>
                  <div className="font-display text-[1.5rem] font-bold text-jenny-text tabular-nums leading-none">
                    <AnimatedNumber
                      value={stats.deposits.collected_eur}
                      format={(n) => `${Math.round(n).toLocaleString("fr-FR")} €`}
                    />
                  </div>
                  <div className="text-[11px] text-jenny-text-secondary mt-1 leading-snug">
                    Encaissés
                  </div>
                </div>
              </div>

              {!stats.deposits.enabled && (
                <p className="mt-4 pt-4 border-t border-jenny-divider/70 text-[12px] text-jenny-text-secondary/80 leading-snug">
                  Acompte non activé — activez-le dans les réglages pour réduire les no-shows.
                </p>
              )}
            </Card>
          </motion.div>

          {/* (b) Liste d'attente */}
          <motion.div variants={fadeInUp} initial="hidden" animate="show">
            <Card className="p-6 h-full flex flex-col">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-9 h-9 rounded-xl bg-jenny-coral/10 text-jenny-coral flex items-center justify-center">
                  <Hourglass className="w-[18px] h-[18px]" />
                </div>
                <h2 className="font-semibold text-jenny-text text-sm">Liste d&apos;attente</h2>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <div className="font-display text-[1.5rem] font-bold text-jenny-text tabular-nums leading-none">
                    <AnimatedNumber value={stats.waitlist.waiting} />
                  </div>
                  <div className="text-[11px] text-jenny-text-secondary mt-1 leading-snug">
                    En attente
                  </div>
                </div>
                <div>
                  <div className="font-display text-[1.5rem] font-bold text-jenny-text tabular-nums leading-none">
                    <AnimatedNumber value={stats.waitlist.notified} />
                  </div>
                  <div className="text-[11px] text-jenny-text-secondary mt-1 leading-snug">
                    Prévenus
                  </div>
                </div>
              </div>

              <div className="mt-auto pt-4 flex items-center gap-2 text-[12.5px] text-jenny-text-secondary leading-snug">
                <Users className="w-4 h-4 text-jenny-coral shrink-0" />
                Vos clients en attente d&apos;un créneau, prévenus dès qu&apos;une place se libère.
              </div>
            </Card>
          </motion.div>
        </div>
      </div>
    </div>
  );
}

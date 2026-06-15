"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { format } from "date-fns";
import { fr } from "date-fns/locale";
import { CalendarClock, MapPin, ArrowRight, Radio } from "lucide-react";
import { listAppointments, type Appointment } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { easeOutExpo, staggerContainer, staggerItem } from "@/lib/motion";

// Pastille de statut — aligne les libellés/couleurs sur la page calendrier.
const STATUS_META: Record<string, { label: string; dot: string; text: string }> = {
  scheduled: { label: "Planifié", dot: "bg-jenny-coral", text: "text-jenny-coral" },
  confirmed: { label: "Confirmé", dot: "bg-jenny-success", text: "text-jenny-success" },
  cancelled: { label: "Annulé", dot: "bg-jenny-error", text: "text-jenny-error" },
  completed: { label: "Terminé", dot: "bg-jenny-slate", text: "text-jenny-slate" },
};

function statusMeta(status: string) {
  return (
    STATUS_META[status] ?? {
      label: status,
      dot: "bg-jenny-text-secondary",
      text: "text-jenny-text-secondary",
    }
  );
}

// "lun. 16 juin · 14:30" (locale fr, 1ʳᵉ lettre capitalisée).
function formatWhen(startAt: string): string {
  const d = new Date(startAt);
  const day = format(d, "EEE d MMM", { locale: fr });
  const time = format(d, "HH:mm", { locale: fr });
  return `${day.charAt(0).toUpperCase()}${day.slice(1)} · ${time}`;
}

// Libellé de canal lisible (repli sur la valeur brute).
const CHANNEL_LABEL: Record<string, string> = {
  whatsapp: "WhatsApp",
  instagram: "Instagram",
  email: "E-mail",
  twitter: "Twitter",
  messenger: "Messenger",
  sms: "SMS",
};

function channelLabel(channel: string): string {
  return CHANNEL_LABEL[channel] ?? channel.charAt(0).toUpperCase() + channel.slice(1);
}

export function UpcomingAppointments() {
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await listAppointments({
          start: new Date().toISOString(),
          limit: 5,
        });
        if (active) setAppointments(res.appointments);
      } catch {
        // Erreur silencieuse : un échec ne doit pas casser le dashboard.
        if (active) setHasError(true);
      } finally {
        if (active) setIsLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  return (
    <Card className="p-6">
      {/* En-tête */}
      <div className="flex items-start justify-between gap-3 mb-5">
        <div>
          <div className="font-mono text-[11px] tracking-[0.22em] uppercase text-jenny-coral mb-1.5">
            — Agenda —
          </div>
          <h3 className="font-display text-[1.35rem] leading-none tracking-[-0.01em] text-jenny-text">
            Prochains rendez-vous
          </h3>
        </div>
        <Link
          href="/calendar"
          className="group inline-flex items-center gap-1 text-[13px] font-semibold text-jenny-coral hover:text-jenny-coral-dark transition-colors shrink-0 mt-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-jenny-coral/30 rounded-md"
        >
          Voir l&apos;agenda
          <ArrowRight className="w-3.5 h-3.5 transition-transform group-hover:translate-x-0.5" />
        </Link>
      </div>

      {/* Chargement */}
      {isLoading ? (
        <div className="space-y-2.5">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="flex items-center gap-3 rounded-xl border border-jenny-divider p-3"
            >
              <Skeleton className="w-9 h-9 rounded-xl shrink-0" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-3.5 w-2/5" />
                <Skeleton className="h-3 w-3/5" />
              </div>
              <Skeleton className="h-5 w-16 rounded-full" />
            </div>
          ))}
        </div>
      ) : hasError ? (
        // Erreur discrète
        <p className="text-[13px] text-jenny-text-secondary py-2">
          Impossible de charger les rendez-vous pour le moment.
        </p>
      ) : appointments.length === 0 ? (
        // État vide élégant
        <div className="flex flex-col items-center justify-center text-center py-8 px-4">
          <div className="w-14 h-14 rounded-2xl bg-jenny-coral-tint dark:bg-jenny-coral/10 text-jenny-coral flex items-center justify-center mb-3">
            <CalendarClock className="w-7 h-7" />
          </div>
          <p className="font-semibold text-jenny-text">Aucun rendez-vous à venir</p>
          <p className="text-[13px] text-jenny-text-secondary max-w-xs mt-1">
            Vos prochains créneaux planifiés apparaîtront ici.
          </p>
          <Link
            href="/calendar"
            className="mt-4 inline-flex items-center gap-1.5 h-9 px-4 rounded-xl bg-jenny-coral text-white text-[13px] font-semibold hover:bg-jenny-coral-dark active:scale-[0.98] transition-all"
          >
            <CalendarClock className="w-4 h-4" />
            Planifier un rendez-vous
          </Link>
        </div>
      ) : (
        // Liste des 5 prochains RDV
        <motion.ul
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="space-y-2"
        >
          {appointments.map((appt) => {
            const meta = statusMeta(appt.status);
            const cancelled = appt.status === "cancelled";
            const place = appt.location?.trim();
            const channel = appt.channel?.trim();
            return (
              <motion.li key={appt.id} variants={staggerItem}>
                <Link
                  href="/calendar"
                  className="group flex items-center gap-3 rounded-xl border border-jenny-divider bg-jenny-surface p-3 hover:border-jenny-coral/30 hover:bg-jenny-bg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-jenny-coral/30"
                >
                  {/* Vignette date */}
                  <span className="w-9 h-9 rounded-xl bg-jenny-coral/10 text-jenny-coral flex items-center justify-center shrink-0">
                    <CalendarClock className="w-4 h-4" />
                  </span>

                  {/* Titre + méta */}
                  <div className="min-w-0 flex-1">
                    <p
                      className={cn(
                        "text-[13.5px] font-semibold text-jenny-text truncate leading-tight",
                        cancelled && "line-through opacity-60"
                      )}
                      title={appt.title}
                    >
                      {appt.title}
                    </p>
                    <div className="mt-0.5 flex items-center gap-2 text-[12px] text-jenny-text-secondary">
                      <span className="tabular-nums shrink-0">{formatWhen(appt.start_at)}</span>
                      {place ? (
                        <span className="flex items-center gap-1 min-w-0">
                          <span aria-hidden className="text-jenny-text-secondary/40">
                            ·
                          </span>
                          <MapPin className="w-3 h-3 shrink-0" />
                          <span className="truncate">{place}</span>
                        </span>
                      ) : channel ? (
                        <span className="flex items-center gap-1 min-w-0">
                          <span aria-hidden className="text-jenny-text-secondary/40">
                            ·
                          </span>
                          <Radio className="w-3 h-3 shrink-0" />
                          <span className="truncate">{channelLabel(channel)}</span>
                        </span>
                      ) : null}
                    </div>
                  </div>

                  {/* Pastille de statut */}
                  <span
                    className={cn(
                      "inline-flex items-center gap-1.5 shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold",
                      "bg-jenny-divider/40",
                      meta.text
                    )}
                  >
                    <span className={cn("w-1.5 h-1.5 rounded-full", meta.dot)} />
                    {meta.label}
                  </span>
                </Link>
              </motion.li>
            );
          })}
        </motion.ul>
      )}
    </Card>
  );
}

// Variante exportée par défaut pour le chargement via next/dynamic.
export default function UpcomingAppointmentsDynamic() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: easeOutExpo }}
    >
      <UpcomingAppointments />
    </motion.div>
  );
}

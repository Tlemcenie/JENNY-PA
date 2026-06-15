"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CalendarPlus, Clock, MapPin, Type as TypeIcon, X } from "lucide-react";
import { createAppointment, ApiError, type Appointment } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { useFocusTrap } from "@/lib/use-focus-trap";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { easeOutExpo } from "@/lib/motion";

// Contexte optionnel : pré-remplit le formulaire et relie le RDV au client /
// à la conversation d'origine (planification depuis la fiche 360 ou le chat).
export interface ScheduleContext {
  customerId?: string | null;
  conversationId?: string | null;
  customerName?: string | null;
  defaultChannel?: string | null;
}

interface ScheduleAppointmentDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated?: (appt: Appointment) => void;
  context?: ScheduleContext;
}

// Durées proposées (minutes) — couvre les rendez-vous courants.
const DURATIONS: { value: number; label: string }[] = [
  { value: 30, label: "30 min" },
  { value: 60, label: "1 h" },
  { value: 90, label: "1 h 30" },
];

// "YYYY-MM-DD" en heure locale (valeur d'input date).
function toDateValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

// Heure pleine suivante, formatée "HH:mm" (valeur d'input time par défaut).
function nextHour(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  const h = (date.getHours() + 1) % 24;
  return `${pad(h)}:00`;
}

function extractError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    return (err.data as { detail?: string })?.detail || `Erreur ${err.status}`;
  }
  return fallback;
}

export function ScheduleAppointmentDialog({
  open,
  onClose,
  onCreated,
  context,
}: ScheduleAppointmentDialogProps) {
  const toast = useToast();
  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(open, dialogRef);

  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [startTime, setStartTime] = useState("09:00");
  const [duration, setDuration] = useState(60);
  const [location, setLocation] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const customerName = context?.customerName?.trim() || "";

  // À chaque ouverture : réinitialise le formulaire avec des valeurs sensées,
  // pré-remplit le titre si un client est fourni.
  useEffect(() => {
    if (!open) return;
    const now = new Date();
    setTitle(customerName ? `Rendez-vous avec ${customerName}` : "");
    setDate(toDateValue(now));
    setStartTime(nextHour(now));
    setDuration(60);
    setLocation("");
    setError(null);
    setSaving(false);
  }, [open, customerName]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (saving) return;

    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      setError("Le titre est obligatoire.");
      return;
    }
    const start = new Date(`${date}T${startTime}`);
    if (Number.isNaN(start.getTime())) {
      setError("Date ou heure invalide.");
      return;
    }
    const end = new Date(start.getTime() + duration * 60_000);

    setSaving(true);
    setError(null);
    try {
      const appt = await createAppointment({
        title: trimmedTitle,
        start_at: start.toISOString(),
        end_at: end.toISOString(),
        location: location.trim() || null,
        customer_id: context?.customerId ?? undefined,
        conversation_id: context?.conversationId ?? undefined,
        channel: context?.defaultChannel ?? "manual",
      });
      toast.success("Rendez-vous planifié");
      onCreated?.(appt);
      onClose();
    } catch (err) {
      setError(extractError(err, "Échec de la planification du rendez-vous."));
    } finally {
      setSaving(false);
    }
  };

  const inputClass =
    "w-full h-10 px-3 text-sm rounded-xl bg-jenny-bg border border-jenny-divider text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral transition-all";

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Voile sombre */}
          <motion.div
            className="fixed inset-0 z-[80] bg-black/40 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={() => !saving && onClose()}
          />
          {/* Modale glass centrée */}
          <motion.div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-label="Planifier un rendez-vous"
            className="fixed left-1/2 top-1/2 z-[81] w-[min(94vw,440px)] -translate-x-1/2 -translate-y-1/2 bg-jenny-surface/95 backdrop-blur-xl border border-jenny-divider rounded-2xl shadow-2xl"
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 8 }}
            transition={{ duration: 0.2, ease: easeOutExpo }}
            onKeyDown={(e) => {
              if (e.key === "Escape" && !saving) onClose();
            }}
          >
            {/* En-tête */}
            <div className="flex items-start justify-between gap-3 p-5 border-b border-jenny-divider">
              <div className="flex items-center gap-3 min-w-0">
                <span className="w-10 h-10 rounded-xl bg-jenny-coral/12 text-jenny-coral flex items-center justify-center shrink-0">
                  <CalendarPlus className="w-5 h-5" />
                </span>
                <div className="min-w-0">
                  <h2 className="font-semibold text-jenny-text">Planifier un rendez-vous</h2>
                  {customerName ? (
                    <p className="text-xs text-jenny-text-secondary truncate">
                      Avec {customerName}
                    </p>
                  ) : (
                    <p className="text-xs text-jenny-text-secondary">Nouveau créneau</p>
                  )}
                </div>
              </div>
              <button
                type="button"
                onClick={() => !saving && onClose()}
                aria-label="Fermer"
                className="p-1.5 rounded-lg text-jenny-text-secondary hover:text-jenny-text hover:bg-jenny-divider/40 transition-colors shrink-0"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Formulaire */}
            <form onSubmit={submit} className="p-5 space-y-4">
              {/* Titre */}
              <div className="space-y-1.5">
                <label
                  htmlFor="appt-title"
                  className="flex items-center gap-1.5 text-[0.8125rem] font-semibold text-jenny-text"
                >
                  <TypeIcon className="w-3.5 h-3.5 text-jenny-text-secondary" />
                  Titre
                </label>
                <input
                  id="appt-title"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Objet du rendez-vous"
                  autoFocus
                  className={inputClass}
                />
              </div>

              {/* Date + heure */}
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <label
                    htmlFor="appt-date"
                    className="text-[0.8125rem] font-semibold text-jenny-text"
                  >
                    Date
                  </label>
                  <input
                    id="appt-date"
                    type="date"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                    className={inputClass}
                  />
                </div>
                <div className="space-y-1.5">
                  <label
                    htmlFor="appt-start"
                    className="flex items-center gap-1.5 text-[0.8125rem] font-semibold text-jenny-text"
                  >
                    <Clock className="w-3.5 h-3.5 text-jenny-text-secondary" />
                    Début
                  </label>
                  <input
                    id="appt-start"
                    type="time"
                    value={startTime}
                    onChange={(e) => setStartTime(e.target.value)}
                    className={inputClass}
                  />
                </div>
              </div>

              {/* Durée */}
              <div className="space-y-1.5">
                <label
                  htmlFor="appt-duration"
                  className="text-[0.8125rem] font-semibold text-jenny-text"
                >
                  Durée
                </label>
                <div className="flex gap-2">
                  {DURATIONS.map((d) => (
                    <button
                      key={d.value}
                      type="button"
                      onClick={() => setDuration(d.value)}
                      className={cn(
                        "flex-1 h-10 rounded-xl text-sm font-medium transition-all",
                        duration === d.value
                          ? "bg-jenny-coral text-white shadow-sm shadow-jenny-coral/20"
                          : "bg-jenny-bg border border-jenny-divider text-jenny-text-secondary hover:border-jenny-coral/40 hover:text-jenny-text"
                      )}
                    >
                      {d.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Lieu (optionnel) */}
              <div className="space-y-1.5">
                <label
                  htmlFor="appt-location"
                  className="flex items-center gap-1.5 text-[0.8125rem] font-semibold text-jenny-text"
                >
                  <MapPin className="w-3.5 h-3.5 text-jenny-text-secondary" />
                  Lieu
                  <span className="font-normal text-jenny-text-secondary/70">(optionnel)</span>
                </label>
                <input
                  id="appt-location"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  placeholder="Adresse, lien visio…"
                  className={inputClass}
                />
              </div>

              {error && (
                <p className="text-[0.8125rem] text-jenny-error leading-snug">{error}</p>
              )}

              {/* Actions */}
              <div className="flex justify-end gap-2 pt-1">
                <Button type="button" variant="secondary" size="md" onClick={onClose} disabled={saving}>
                  Annuler
                </Button>
                <Button type="submit" size="md" isLoading={saving}>
                  <CalendarPlus className="w-4 h-4" />
                  Planifier
                </Button>
              </div>
            </form>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

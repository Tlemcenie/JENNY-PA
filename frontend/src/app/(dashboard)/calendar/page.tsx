"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  addMonths,
  addWeeks,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameMonth,
  isToday,
  startOfMonth,
  startOfWeek,
} from "date-fns";
import { fr } from "date-fns/locale";
import {
  Calendar,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock,
  Download,
  MapPin,
  MessageSquare,
  Plus,
  Star,
  Trash,
  UserX,
  X,
} from "lucide-react";
import {
  createAppointment,
  createReview,
  deleteAppointment,
  exportAppointmentsIcs,
  listAppointments,
  updateAppointment,
  ApiError,
  type Appointment,
} from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { useFocusTrap } from "@/lib/use-focus-trap";
import { cn } from "@/lib/utils";
import { easeOutExpo, fadeInUp } from "@/lib/motion";

// ── Constantes d'affichage ────────────────────────────────────────────────

// Vue semaine : plage horaire visible (heures pleines).
const DAY_START_HOUR = 7;
const DAY_END_HOUR = 21;
const HOUR_PX = 52; // hauteur d'une heure dans la grille semaine
const WEEKDAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];

type CalendarView = "month" | "week";

// Couleur d'un rendez-vous : annulé → rouge, sinon couleur du canal, repli corail.
// On renvoie des variables CSS (qui basculent clair/sombre automatiquement).
function appointmentColor(appt: Appointment): string {
  if (appt.status === "cancelled") return "var(--color-jenny-error)";
  switch (appt.channel) {
    case "whatsapp":
      return "var(--color-jenny-whatsapp)";
    case "instagram":
      return "var(--color-jenny-instagram)";
    case "email":
      return "var(--color-jenny-email)";
    case "twitter":
      return "var(--color-jenny-twitter)";
    default:
      return "var(--color-jenny-coral)";
  }
}

const STATUS_META: Record<string, { label: string; className: string }> = {
  scheduled: { label: "Planifié", className: "bg-jenny-coral/12 text-jenny-coral" },
  confirmed: { label: "Confirmé", className: "bg-jenny-success/12 text-jenny-success" },
  cancelled: { label: "Annulé", className: "bg-jenny-error/12 text-jenny-error" },
  completed: { label: "Terminé", className: "bg-jenny-slate/15 text-jenny-slate" },
  no_show: { label: "Absent", className: "bg-jenny-warning/12 text-jenny-warning" },
};

function statusMeta(status: string) {
  return STATUS_META[status] ?? { label: status, className: "bg-jenny-divider/60 text-jenny-text-secondary" };
}

// Capitalise la 1ʳᵉ lettre (les libellés date-fns `fr` sont en minuscules).
function cap(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

// Format "YYYY-MM-DD" en heure locale (clé d'index par jour + valeur d'input date).
function toDateValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function extractError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    return (err.data as { detail?: string })?.detail || `Erreur ${err.status}`;
  }
  return fallback;
}

// ── Formulaire de création ────────────────────────────────────────────────

interface CreateForm {
  title: string;
  date: string; // YYYY-MM-DD
  startTime: string; // HH:mm
  endTime: string; // HH:mm
  location: string;
  description: string;
}

function emptyForm(day: Date): CreateForm {
  return {
    title: "",
    date: toDateValue(day),
    startTime: "09:00",
    endTime: "10:00",
    location: "",
    description: "",
  };
}

// ── Page ──────────────────────────────────────────────────────────────────

export default function CalendarPage() {
  const toast = useToast();

  const [view, setView] = useState<CalendarView>("month");
  const [cursor, setCursor] = useState<Date>(() => new Date()); // ancre du mois / de la semaine
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  // Modale de création
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState<CreateForm>(() => emptyForm(new Date()));
  const [saving, setSaving] = useState(false);
  const createRef = useRef<HTMLDivElement>(null);
  useFocusTrap(createOpen, createRef);

  // Modale de détail
  const [selected, setSelected] = useState<Appointment | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const detailRef = useRef<HTMLDivElement>(null);
  useFocusTrap(selected !== null, detailRef);

  // ── Plage visible (selon la vue) ──
  const range = useMemo(() => {
    if (view === "week") {
      const start = startOfWeek(cursor, { weekStartsOn: 1 });
      const end = endOfWeek(cursor, { weekStartsOn: 1 });
      return { start, end };
    }
    // Mois : on englobe les jours débordants pour remplir la grille 7 colonnes.
    const monthStart = startOfMonth(cursor);
    const monthEnd = endOfMonth(cursor);
    return {
      start: startOfWeek(monthStart, { weekStartsOn: 1 }),
      end: endOfWeek(monthEnd, { weekStartsOn: 1 }),
    };
  }, [cursor, view]);

  const fetchAppointments = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      // Marges d'une journée pour capter les RDV chevauchant les bords de plage.
      const start = new Date(range.start);
      start.setHours(0, 0, 0, 0);
      const end = new Date(range.end);
      end.setHours(23, 59, 59, 999);
      const res = await listAppointments({
        start: start.toISOString(),
        end: end.toISOString(),
        limit: 500,
      });
      setAppointments(res.appointments);
    } catch (err) {
      setError(
        extractError(err, "Impossible de charger l'agenda. Vérifiez que le backend est démarré.")
      );
    } finally {
      setIsLoading(false);
    }
  }, [range.start, range.end]);

  useEffect(() => {
    fetchAppointments();
  }, [fetchAppointments]);

  // ── Jours de la grille + index RDV par jour ──
  const days = useMemo(
    () => eachDayOfInterval({ start: range.start, end: range.end }),
    [range.start, range.end]
  );

  const byDay = useMemo(() => {
    const map = new Map<string, Appointment[]>();
    for (const appt of appointments) {
      const key = toDateValue(new Date(appt.start_at));
      const list = map.get(key);
      if (list) list.push(appt);
      else map.set(key, [appt]);
    }
    // Tri chronologique à l'intérieur de chaque jour.
    for (const list of map.values()) {
      list.sort((a, b) => +new Date(a.start_at) - +new Date(b.start_at));
    }
    return map;
  }, [appointments]);

  const dayAppointments = useCallback(
    (day: Date) => byDay.get(toDateValue(day)) ?? [],
    [byDay]
  );

  // ── Export .ics ──
  const handleExportIcs = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      await exportAppointmentsIcs();
    } catch (err) {
      toast.error(extractError(err, "Échec de l'export de l'agenda."));
    } finally {
      setExporting(false);
    }
  };

  // ── Navigation ──
  const goToday = () => setCursor(new Date());
  const goPrev = () => setCursor((c) => (view === "week" ? addWeeks(c, -1) : addMonths(c, -1)));
  const goNext = () => setCursor((c) => (view === "week" ? addWeeks(c, 1) : addMonths(c, 1)));

  const periodLabel = useMemo(() => {
    if (view === "week") {
      const start = startOfWeek(cursor, { weekStartsOn: 1 });
      const end = endOfWeek(cursor, { weekStartsOn: 1 });
      const sameMonth = isSameMonth(start, end);
      const left = format(start, sameMonth ? "d" : "d MMM", { locale: fr });
      const right = format(end, "d MMM yyyy", { locale: fr });
      return `${left} – ${right}`;
    }
    return cap(format(cursor, "MMMM yyyy", { locale: fr }));
  }, [cursor, view]);

  // ── Ouverture des modales ──
  const openCreate = (day?: Date) => {
    setForm(emptyForm(day ?? new Date()));
    setCreateOpen(true);
  };

  const closeCreate = () => {
    if (saving) return;
    setCreateOpen(false);
  };

  const submitCreate = async (e: FormEvent) => {
    e.preventDefault();
    if (!form.title.trim()) {
      toast.error("Le titre est obligatoire.");
      return;
    }
    const startAt = new Date(`${form.date}T${form.startTime}`);
    const endAt = new Date(`${form.date}T${form.endTime}`);
    if (Number.isNaN(startAt.getTime()) || Number.isNaN(endAt.getTime())) {
      toast.error("Date ou heure invalide.");
      return;
    }
    if (endAt <= startAt) {
      toast.error("L'heure de fin doit suivre l'heure de début.");
      return;
    }
    setSaving(true);
    try {
      await createAppointment({
        title: form.title.trim(),
        start_at: startAt.toISOString(),
        end_at: endAt.toISOString(),
        location: form.location.trim() || null,
        description: form.description.trim() || null,
      });
      toast.success("Rendez-vous créé.");
      setCreateOpen(false);
      await fetchAppointments();
    } catch (err) {
      toast.error(extractError(err, "Échec de la création du rendez-vous."));
    } finally {
      setSaving(false);
    }
  };

  const changeStatus = async (status: "confirmed" | "cancelled") => {
    if (!selected) return;
    setActionBusy(true);
    try {
      const updated = await updateAppointment(selected.id, { status });
      setSelected(updated);
      toast.success(status === "confirmed" ? "Rendez-vous confirmé." : "Rendez-vous annulé.");
      await fetchAppointments();
    } catch (err) {
      toast.error(extractError(err, "Échec de la mise à jour."));
    } finally {
      setActionBusy(false);
    }
  };

  // Marquer un client absent (no-show) : RDV passé non honoré.
  const markNoShow = async () => {
    if (!selected) return;
    setActionBusy(true);
    try {
      const updated = await updateAppointment(selected.id, { status: "no_show" });
      setSelected(updated);
      toast.success("Client marqué absent.");
      await fetchAppointments();
    } catch (err) {
      toast.error(extractError(err, "Échec de la mise à jour."));
    } finally {
      setActionBusy(false);
    }
  };

  // Notes techniques privées (formule couleur, allergies…), visibles par l'équipe.
  const saveNotes = async (staff_notes: string) => {
    if (!selected) return;
    setActionBusy(true);
    try {
      const updated = await updateAppointment(selected.id, { staff_notes });
      setSelected(updated);
      toast.success("Notes enregistrées.");
      await fetchAppointments();
    } catch (err) {
      toast.error(extractError(err, "Échec de l'enregistrement des notes."));
    } finally {
      setActionBusy(false);
    }
  };

  // Avis client laissé par l'équipe après un RDV passé.
  const submitReview = async (rating: number, comment: string) => {
    if (!selected) return;
    setActionBusy(true);
    try {
      await createReview({
        rating,
        comment: comment.trim() || undefined,
        customer_id: selected.customer_id ?? undefined,
        appointment_id: selected.id,
      });
      toast.success("Avis enregistré.");
    } catch (err) {
      toast.error(extractError(err, "Échec de l'enregistrement de l'avis."));
    } finally {
      setActionBusy(false);
    }
  };

  const removeAppointment = async () => {
    if (!selected) return;
    setActionBusy(true);
    try {
      await deleteAppointment(selected.id);
      toast.success("Rendez-vous supprimé.");
      setSelected(null);
      await fetchAppointments();
    } catch (err) {
      toast.error(extractError(err, "Échec de la suppression."));
    } finally {
      setActionBusy(false);
    }
  };

  const totalVisible = appointments.length;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-6xl mx-auto p-6 md:p-8 space-y-5">
        {/* ── En-tête ── */}
        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: easeOutExpo }}
          className="flex flex-wrap items-end gap-4"
        >
          <div>
            <div className="font-mono text-[11px] tracking-[0.22em] uppercase text-jenny-coral mb-2">
              — planning —
            </div>
            <h1 className="font-display text-[clamp(30px,5vw,42px)] leading-[1] tracking-[-0.02em] text-jenny-text">
              Votre <span className="italic text-jenny-coral">agenda.</span>
            </h1>
            <p className="text-sm text-jenny-text-secondary mt-1">
              Tous vos rendez-vous, au même endroit.
            </p>
          </div>

          <div className="ml-auto flex flex-wrap items-center gap-2">
            {/* Bascule mois / semaine */}
            <div className="flex items-center rounded-xl border border-jenny-divider bg-jenny-surface p-0.5">
              {(["month", "week"] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setView(v)}
                  aria-pressed={view === v}
                  className={cn(
                    "px-3 py-1.5 rounded-lg text-[12.5px] font-semibold transition-colors",
                    view === v
                      ? "bg-jenny-coral text-white"
                      : "text-jenny-text-secondary hover:text-jenny-text"
                  )}
                >
                  {v === "month" ? "Mois" : "Semaine"}
                </button>
              ))}
            </div>

            <button
              type="button"
              onClick={handleExportIcs}
              disabled={exporting}
              aria-label="Exporter l'agenda au format .ics"
              className="inline-flex items-center gap-1.5 h-9 px-4 rounded-xl border border-jenny-divider bg-jenny-surface text-[13px] font-semibold text-jenny-text hover:border-jenny-text-secondary/30 active:scale-[0.98] transition-all disabled:opacity-50 disabled:pointer-events-none"
            >
              {exporting ? (
                <svg className="animate-spin h-4 w-4 text-jenny-coral" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                <Download className="w-4 h-4 text-jenny-coral" />
              )}
              Exporter .ics
            </button>

            <button
              type="button"
              onClick={openCreate.bind(null, undefined)}
              className="inline-flex items-center gap-1.5 h-9 px-4 rounded-xl bg-jenny-coral text-white text-[13px] font-semibold shadow-sm shadow-jenny-coral/20 hover:bg-jenny-coral-dark active:scale-[0.98] transition-all"
            >
              <Plus className="w-4 h-4" />
              Nouveau rendez-vous
            </button>
          </div>
        </motion.div>

        {/* ── Barre de navigation ── */}
        <motion.div
          variants={fadeInUp}
          initial="hidden"
          animate="show"
          className="flex flex-wrap items-center gap-3"
        >
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={goPrev}
              aria-label="Période précédente"
              className="w-9 h-9 inline-flex items-center justify-center rounded-xl border border-jenny-divider bg-jenny-surface text-jenny-text-secondary hover:text-jenny-text hover:border-jenny-text-secondary/30 transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={goNext}
              aria-label="Période suivante"
              className="w-9 h-9 inline-flex items-center justify-center rounded-xl border border-jenny-divider bg-jenny-surface text-jenny-text-secondary hover:text-jenny-text hover:border-jenny-text-secondary/30 transition-colors"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>

          <h2 className="font-display text-[22px] leading-none tracking-[-0.01em] text-jenny-text min-w-0">
            {periodLabel}
          </h2>

          <button
            type="button"
            onClick={goToday}
            className="inline-flex items-center gap-1.5 h-9 px-3.5 rounded-xl border border-jenny-divider bg-jenny-surface text-[13px] font-semibold text-jenny-text hover:border-jenny-text-secondary/30 transition-colors"
          >
            <Calendar className="w-3.5 h-3.5 text-jenny-coral" />
            Aujourd&apos;hui
          </button>

          <span className="ml-auto font-mono text-[11px] uppercase tracking-[0.14em] text-jenny-text-secondary">
            {totalVisible} RDV
          </span>
        </motion.div>

        {/* ── Contenu principal ── */}
        {error ? (
          <ErrorBlock message={error} onRetry={fetchAppointments} />
        ) : isLoading ? (
          view === "month" ? (
            <MonthSkeleton />
          ) : (
            <WeekSkeleton />
          )
        ) : view === "month" ? (
          <MonthGrid
            days={days}
            cursor={cursor}
            dayAppointments={dayAppointments}
            onSelectAppointment={setSelected}
            onCreateDay={openCreate}
            isEmpty={totalVisible === 0}
            onCreateEmpty={() => openCreate()}
          />
        ) : (
          <WeekGrid
            cursor={cursor}
            dayAppointments={dayAppointments}
            onSelectAppointment={setSelected}
            onCreateDay={openCreate}
          />
        )}

        {/* ── Carte « Connecter Google Agenda » (présentationnel) ── */}
        <motion.div variants={fadeInUp} initial="hidden" animate="show">
          <GoogleConnectCard />
        </motion.div>
      </div>

      {/* ── Modale : création ── */}
      <AnimatePresence>
        {createOpen && (
          <Modal
            ref={createRef}
            label="Nouveau rendez-vous"
            onClose={closeCreate}
          >
            <div className="flex items-center justify-between gap-3 mb-5">
              <h2 className="font-display text-[24px] leading-none tracking-[-0.01em] text-jenny-text">
                Nouveau <span className="italic text-jenny-coral">rendez-vous.</span>
              </h2>
              <button
                type="button"
                onClick={closeCreate}
                aria-label="Fermer"
                className="w-8 h-8 inline-flex items-center justify-center rounded-lg text-jenny-text-secondary hover:bg-jenny-divider/40 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={submitCreate} className="space-y-4">
              <Field label="Titre" htmlFor="appt-title">
                <input
                  id="appt-title"
                  value={form.title}
                  onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                  placeholder="Ex : Appel de suivi avec Sophie"
                  required
                  className="h-11 px-3.5 rounded-xl bg-jenny-bg border border-jenny-divider text-[0.9rem] text-jenny-text placeholder:text-jenny-text-secondary/50 focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral transition-all"
                />
              </Field>

              <Field label="Date" htmlFor="appt-date">
                <input
                  id="appt-date"
                  type="date"
                  value={form.date}
                  onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))}
                  required
                  className="h-11 px-3.5 rounded-xl bg-jenny-bg border border-jenny-divider text-[0.9rem] text-jenny-text focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral transition-all"
                />
              </Field>

              <div className="grid grid-cols-2 gap-4">
                <Field label="Début" htmlFor="appt-start">
                  <input
                    id="appt-start"
                    type="time"
                    value={form.startTime}
                    onChange={(e) => setForm((f) => ({ ...f, startTime: e.target.value }))}
                    required
                    className="h-11 px-3.5 rounded-xl bg-jenny-bg border border-jenny-divider text-[0.9rem] text-jenny-text focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral transition-all"
                  />
                </Field>
                <Field label="Fin" htmlFor="appt-end">
                  <input
                    id="appt-end"
                    type="time"
                    value={form.endTime}
                    onChange={(e) => setForm((f) => ({ ...f, endTime: e.target.value }))}
                    required
                    className="h-11 px-3.5 rounded-xl bg-jenny-bg border border-jenny-divider text-[0.9rem] text-jenny-text focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral transition-all"
                  />
                </Field>
              </div>

              <Field label="Lieu (optionnel)" htmlFor="appt-location">
                <input
                  id="appt-location"
                  value={form.location}
                  onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))}
                  placeholder="Ex : Visioconférence, boutique…"
                  className="h-11 px-3.5 rounded-xl bg-jenny-bg border border-jenny-divider text-[0.9rem] text-jenny-text placeholder:text-jenny-text-secondary/50 focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral transition-all"
                />
              </Field>

              <Field label="Note (optionnel)" htmlFor="appt-description">
                <textarea
                  id="appt-description"
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  placeholder="Ajoutez un contexte…"
                  rows={3}
                  className="px-3.5 py-2.5 rounded-xl bg-jenny-bg border border-jenny-divider text-[0.9rem] text-jenny-text placeholder:text-jenny-text-secondary/50 focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral transition-all resize-none"
                />
              </Field>

              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={closeCreate}
                  className="h-10 px-4 rounded-xl text-[13px] font-semibold text-jenny-text-secondary hover:bg-jenny-divider/40 transition-colors"
                >
                  Annuler
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="inline-flex items-center gap-2 h-10 px-5 rounded-xl bg-jenny-coral text-white text-[13px] font-semibold shadow-sm shadow-jenny-coral/20 hover:bg-jenny-coral-dark active:scale-[0.98] transition-all disabled:opacity-50 disabled:pointer-events-none"
                >
                  {saving && (
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  )}
                  Créer
                </button>
              </div>
            </form>
          </Modal>
        )}
      </AnimatePresence>

      {/* ── Modale : détail ── */}
      <AnimatePresence>
        {selected && (
          <Modal
            ref={detailRef}
            label={selected.title}
            onClose={() => !actionBusy && setSelected(null)}
          >
            <DetailContent
              key={selected.id}
              appt={selected}
              busy={actionBusy}
              onClose={() => setSelected(null)}
              onConfirm={() => changeStatus("confirmed")}
              onCancel={() => changeStatus("cancelled")}
              onDelete={removeAppointment}
              onMarkNoShow={markNoShow}
              onSaveNotes={saveNotes}
              onSubmitReview={submitReview}
            />
          </Modal>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Vue MOIS ────────────────────────────────────────────────────────────────

function MonthGrid({
  days,
  cursor,
  dayAppointments,
  onSelectAppointment,
  onCreateDay,
  isEmpty,
  onCreateEmpty,
}: {
  days: Date[];
  cursor: Date;
  dayAppointments: (day: Date) => Appointment[];
  onSelectAppointment: (appt: Appointment) => void;
  onCreateDay: (day: Date) => void;
  isEmpty: boolean;
  onCreateEmpty: () => void;
}) {
  return (
    <motion.div
      variants={fadeInUp}
      initial="hidden"
      animate="show"
      className="rounded-2xl border border-jenny-divider bg-jenny-surface overflow-hidden"
    >
      {/* En-têtes de colonnes (jours de la semaine) */}
      <div className="grid grid-cols-7 border-b border-jenny-divider">
        {WEEKDAYS.map((d) => (
          <div
            key={d}
            className="px-2 py-2.5 text-center font-mono text-[11px] uppercase tracking-[0.12em] text-jenny-text-secondary"
          >
            {d}
          </div>
        ))}
      </div>

      {isEmpty && (
        <div className="flex flex-col items-center justify-center py-14 px-4 text-center border-b border-jenny-divider">
          <div className="w-14 h-14 rounded-2xl bg-jenny-coral-tint dark:bg-jenny-coral/10 text-jenny-coral flex items-center justify-center mb-3">
            <Calendar className="w-7 h-7" />
          </div>
          <h3 className="font-semibold text-jenny-text">Aucun rendez-vous ce mois-ci</h3>
          <p className="text-sm text-jenny-text-secondary max-w-xs mt-1">
            Cliquez sur un jour ou sur « Nouveau rendez-vous » pour planifier votre premier créneau.
          </p>
          <button
            type="button"
            onClick={onCreateEmpty}
            className="mt-4 inline-flex items-center gap-1.5 h-9 px-4 rounded-xl bg-jenny-coral text-white text-[13px] font-semibold hover:bg-jenny-coral-dark transition-colors"
          >
            <Plus className="w-4 h-4" />
            Nouveau rendez-vous
          </button>
        </div>
      )}

      {/* Grille des jours (lignes de 7) */}
      <div className="grid grid-cols-7 auto-rows-fr">
        {days.map((day) => {
          const inMonth = isSameMonth(day, cursor);
          const today = isToday(day);
          const appts = dayAppointments(day);
          const visible = appts.slice(0, 3);
          const overflow = appts.length - visible.length;

          return (
            <button
              key={day.toISOString()}
              type="button"
              onClick={() => onCreateDay(day)}
              className={cn(
                "group relative text-left min-h-[104px] p-1.5 border-b border-r border-jenny-divider last:border-r-0 transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-jenny-coral/40",
                inMonth ? "bg-jenny-surface hover:bg-jenny-bg" : "bg-jenny-bg/60 hover:bg-jenny-bg"
              )}
            >
              <div className="flex items-center justify-between px-0.5">
                <span
                  className={cn(
                    "inline-flex items-center justify-center w-6 h-6 rounded-full text-[12.5px] tabular-nums transition-colors",
                    today
                      ? "bg-jenny-coral text-white font-semibold ring-2 ring-jenny-coral/30 ring-offset-1 ring-offset-jenny-surface"
                      : inMonth
                        ? "text-jenny-text"
                        : "text-jenny-text-secondary/50"
                  )}
                >
                  {format(day, "d")}
                </span>
                <Plus className="w-3.5 h-3.5 text-jenny-text-secondary/0 group-hover:text-jenny-text-secondary/60 transition-colors" />
              </div>

              <div className="mt-1 space-y-1">
                {visible.map((appt) => (
                  <EventChip
                    key={appt.id}
                    appt={appt}
                    onClick={(e) => {
                      e.stopPropagation();
                      onSelectAppointment(appt);
                    }}
                  />
                ))}
                {overflow > 0 && (
                  <span className="block px-1.5 text-[11px] font-medium text-jenny-text-secondary">
                    +{overflow} autre{overflow > 1 ? "s" : ""}
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </motion.div>
  );
}

// Pastille d'événement (vue mois) — point de couleur + heure + titre.
function EventChip({
  appt,
  onClick,
}: {
  appt: Appointment;
  onClick: (e: React.MouseEvent) => void;
}) {
  const color = appointmentColor(appt);
  const cancelled = appt.status === "cancelled";
  return (
    <span
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          e.stopPropagation();
          onClick(e as unknown as React.MouseEvent);
        }
      }}
      title={appt.title}
      className={cn(
        "flex items-center gap-1.5 px-1.5 py-1 rounded-md text-[11.5px] leading-tight cursor-pointer transition-colors",
        "hover:brightness-[0.97]"
      )}
      style={{ backgroundColor: `color-mix(in srgb, ${color} 14%, transparent)` }}
    >
      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
      <span className="font-mono text-[10px] text-jenny-text-secondary shrink-0">
        {format(new Date(appt.start_at), "HH:mm")}
      </span>
      <span className={cn("truncate text-jenny-text", cancelled && "line-through opacity-60")}>
        {appt.title}
      </span>
    </span>
  );
}

// ── Vue SEMAINE ─────────────────────────────────────────────────────────────

function WeekGrid({
  cursor,
  dayAppointments,
  onSelectAppointment,
  onCreateDay,
}: {
  cursor: Date;
  dayAppointments: (day: Date) => Appointment[];
  onSelectAppointment: (appt: Appointment) => void;
  onCreateDay: (day: Date) => void;
}) {
  const weekDays = useMemo(() => {
    const start = startOfWeek(cursor, { weekStartsOn: 1 });
    return eachDayOfInterval({ start, end: endOfWeek(cursor, { weekStartsOn: 1 }) });
  }, [cursor]);

  const hours = useMemo(() => {
    const out: number[] = [];
    for (let h = DAY_START_HOUR; h <= DAY_END_HOUR; h++) out.push(h);
    return out;
  }, []);

  const gridHeight = (DAY_END_HOUR - DAY_START_HOUR) * HOUR_PX;

  return (
    <motion.div
      variants={fadeInUp}
      initial="hidden"
      animate="show"
      className="rounded-2xl border border-jenny-divider bg-jenny-surface overflow-hidden"
    >
      {/* En-tête : colonne gutter + 7 jours */}
      <div className="grid border-b border-jenny-divider" style={{ gridTemplateColumns: "56px repeat(7, 1fr)" }}>
        <div className="border-r border-jenny-divider" />
        {weekDays.map((day) => {
          const today = isToday(day);
          return (
            <div
              key={day.toISOString()}
              className="px-2 py-2 text-center border-r border-jenny-divider last:border-r-0"
            >
              <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-jenny-text-secondary">
                {format(day, "EEE", { locale: fr })}
              </div>
              <div
                className={cn(
                  "mt-1 inline-flex items-center justify-center w-7 h-7 rounded-full text-[13px] tabular-nums",
                  today ? "bg-jenny-coral text-white font-semibold" : "text-jenny-text"
                )}
              >
                {format(day, "d")}
              </div>
            </div>
          );
        })}
      </div>

      {/* Corps : gutter horaire + colonnes-jours positionnées */}
      <div className="overflow-x-auto">
        <div
          className="grid min-w-[640px]"
          style={{ gridTemplateColumns: "56px repeat(7, 1fr)" }}
        >
          {/* Gutter heures */}
          <div className="relative border-r border-jenny-divider" style={{ height: gridHeight }}>
            {hours.map((h) => (
              <div
                key={h}
                className="absolute right-1.5 -translate-y-1/2 font-mono text-[10px] text-jenny-text-secondary"
                style={{ top: (h - DAY_START_HOUR) * HOUR_PX }}
              >
                {h}h
              </div>
            ))}
          </div>

          {/* Colonnes jours */}
          {weekDays.map((day) => (
            <div
              key={day.toISOString()}
              className="relative border-r border-jenny-divider last:border-r-0"
              style={{ height: gridHeight }}
            >
              {/* Lignes horaires + zones cliquables */}
              {hours.map((h) => (
                <button
                  key={h}
                  type="button"
                  onClick={() => onCreateDay(day)}
                  aria-label={`Créer un rendez-vous le ${format(day, "d MMMM", { locale: fr })} à ${h}h`}
                  className="absolute left-0 right-0 border-t border-jenny-divider/70 hover:bg-jenny-bg focus:outline-none focus-visible:bg-jenny-bg transition-colors"
                  style={{ top: (h - DAY_START_HOUR) * HOUR_PX, height: HOUR_PX }}
                />
              ))}

              {/* Événements positionnés */}
              {dayAppointments(day).map((appt) => (
                <WeekEvent key={appt.id} appt={appt} onClick={() => onSelectAppointment(appt)} />
              ))}
            </div>
          ))}
        </div>
      </div>
    </motion.div>
  );
}

// Bloc d'événement positionné dans la vue semaine (top/height selon les heures).
function WeekEvent({ appt, onClick }: { appt: Appointment; onClick: () => void }) {
  const start = new Date(appt.start_at);
  const end = new Date(appt.end_at);
  const startMinutes = start.getHours() * 60 + start.getMinutes();
  const endMinutes = end.getHours() * 60 + end.getMinutes();
  const dayStartMin = DAY_START_HOUR * 60;
  const dayEndMin = DAY_END_HOUR * 60;

  // Bornage dans la plage visible.
  const clampedStart = Math.max(startMinutes, dayStartMin);
  const clampedEnd = Math.min(Math.max(endMinutes, clampedStart + 20), dayEndMin);
  const top = ((clampedStart - dayStartMin) / 60) * HOUR_PX;
  const height = Math.max(((clampedEnd - clampedStart) / 60) * HOUR_PX, 18);

  const color = appointmentColor(appt);
  const cancelled = appt.status === "cancelled";

  return (
    <button
      type="button"
      onClick={onClick}
      title={appt.title}
      className="absolute left-0.5 right-0.5 rounded-md px-1.5 py-1 text-left overflow-hidden hover:brightness-[0.97] focus:outline-none focus-visible:ring-2 focus-visible:ring-jenny-coral/40 transition-all"
      style={{
        top,
        height,
        backgroundColor: `color-mix(in srgb, ${color} 16%, transparent)`,
        borderLeft: `3px solid ${color}`,
      }}
    >
      <div className={cn("text-[11px] font-semibold text-jenny-text truncate leading-tight", cancelled && "line-through opacity-60")}>
        {appt.title}
      </div>
      {height > 30 && (
        <div className="font-mono text-[10px] text-jenny-text-secondary truncate">
          {format(start, "HH:mm")}–{format(end, "HH:mm")}
        </div>
      )}
    </button>
  );
}

// ── Modale générique (backdrop + carte centrée) ───────────────────────────

interface ModalProps {
  label: string;
  onClose: () => void;
  children: ReactNode;
  ref: React.Ref<HTMLDivElement>;
}

function Modal({ label, onClose, children, ref }: ModalProps) {
  return (
    <>
      <motion.div
        className="fixed inset-0 z-[80] bg-black/40 backdrop-blur-[2px]"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        onClick={onClose}
      />
      <motion.div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className="fixed left-1/2 top-1/2 z-[81] w-[min(94vw,460px)] max-h-[90vh] overflow-y-auto -translate-x-1/2 -translate-y-1/2 bg-jenny-surface border border-jenny-divider rounded-2xl shadow-2xl p-5"
        initial={{ opacity: 0, scale: 0.96, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, y: 8 }}
        transition={{ duration: 0.2, ease: easeOutExpo }}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
        }}
      >
        {children}
      </motion.div>
    </>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-[12.5px] font-semibold text-jenny-text">
        {label}
      </label>
      {children}
    </div>
  );
}

// ── Contenu de la modale de détail ──────────────────────────────────────────

function DetailContent({
  appt,
  busy,
  onClose,
  onConfirm,
  onCancel,
  onDelete,
  onMarkNoShow,
  onSaveNotes,
  onSubmitReview,
}: {
  appt: Appointment;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
  onCancel: () => void;
  onDelete: () => void;
  onMarkNoShow: () => void;
  onSaveNotes: (notes: string) => void;
  onSubmitReview: (rating: number, comment: string) => void;
}) {
  const start = new Date(appt.start_at);
  const end = new Date(appt.end_at);
  const meta = statusMeta(appt.status);
  const color = appointmentColor(appt);

  // Notes techniques — état local initialisé depuis le RDV. Le composant est
  // remonté par `key={appt.id}` au changement de RDV, donc pas d'effet de resync.
  const [notes, setNotes] = useState(appt.staff_notes ?? "");
  const notesDirty = notes.trim() !== (appt.staff_notes ?? "").trim();

  // Avis client (RDV passé).
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");

  // RDV passé = la fin est antérieure à maintenant. On fige « maintenant » à
  // l'ouverture de la modale (initialiseur paresseux : lecture stable, non impure).
  const [now] = useState(() => Date.now());
  const isPast = end.getTime() < now;
  const canMarkNoShow = isPast && appt.status !== "cancelled" && appt.status !== "no_show";
  const canReview = isPast && !!appt.customer_id;

  return (
    <div>
      <div className="flex items-start justify-between gap-3 mb-4">
        <div className="flex items-start gap-2.5 min-w-0">
          <span className="w-2.5 h-2.5 rounded-full mt-1.5 shrink-0" style={{ backgroundColor: color }} />
          <div className="min-w-0">
            <h2 className="font-display text-[22px] leading-tight tracking-[-0.01em] text-jenny-text break-words">
              {appt.title}
            </h2>
            <span
              className={cn(
                "inline-flex items-center mt-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold",
                meta.className
              )}
            >
              {meta.label}
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Fermer"
          className="w-8 h-8 inline-flex items-center justify-center rounded-lg text-jenny-text-secondary hover:bg-jenny-divider/40 transition-colors shrink-0"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="space-y-2.5 text-[13.5px] text-jenny-text">
        <div className="flex items-center gap-2.5">
          <Clock className="w-4 h-4 text-jenny-text-secondary shrink-0" />
          <span>
            {cap(format(start, "EEEE d MMMM yyyy", { locale: fr }))} · {format(start, "HH:mm")} –{" "}
            {format(end, "HH:mm")}
          </span>
        </div>
        {appt.location && (
          <div className="flex items-center gap-2.5">
            <MapPin className="w-4 h-4 text-jenny-text-secondary shrink-0" />
            <span className="break-words">{appt.location}</span>
          </div>
        )}
        {appt.customer_name && (
          <div className="flex items-center gap-2.5">
            <Calendar className="w-4 h-4 text-jenny-text-secondary shrink-0" />
            <span>Avec {appt.customer_name}</span>
          </div>
        )}
        {appt.description && (
          <p className="text-jenny-text-secondary leading-relaxed pt-1 whitespace-pre-wrap">
            {appt.description}
          </p>
        )}
      </div>

      {/* ── Notes techniques (privé) ── */}
      <div className="mt-5 pt-4 border-t border-jenny-divider/70">
        <label htmlFor="appt-staff-notes" className="text-[12.5px] font-semibold text-jenny-text">
          Notes techniques (privé)
        </label>
        <textarea
          id="appt-staff-notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          placeholder="Formule couleur, longueurs, préférences…"
          className="mt-1.5 w-full px-3.5 py-2.5 rounded-xl bg-jenny-bg border border-jenny-divider text-[0.9rem] text-jenny-text placeholder:text-jenny-text-secondary/50 focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral transition-all resize-none"
        />
        <div className="flex items-center justify-between gap-2 mt-1.5">
          <p className="text-[11.5px] text-jenny-text-secondary">
            Formule couleur, allergies… visible par l&apos;équipe uniquement.
          </p>
          <button
            type="button"
            onClick={() => onSaveNotes(notes)}
            disabled={busy || !notesDirty}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-jenny-coral/12 text-jenny-coral text-[12.5px] font-semibold hover:bg-jenny-coral/20 transition-colors disabled:opacity-50 disabled:pointer-events-none shrink-0"
          >
            <Check className="w-3.5 h-3.5" />
            Enregistrer
          </button>
        </div>
      </div>

      {/* ── Avis client (RDV passé avec client identifié) ── */}
      {canReview && (
        <div className="mt-4 pt-4 border-t border-jenny-divider/70">
          <div className="flex items-center gap-1.5 text-[12.5px] font-semibold text-jenny-text">
            <MessageSquare className="w-3.5 h-3.5 text-jenny-text-secondary" />
            Avis client
          </div>
          <div className="flex items-center gap-1 mt-2" role="radiogroup" aria-label="Note de 1 à 5">
            {[1, 2, 3, 4, 5].map((n) => (
              <button
                key={n}
                type="button"
                role="radio"
                aria-checked={rating === n}
                aria-label={`${n} étoile${n > 1 ? "s" : ""}`}
                onClick={() => setRating(n)}
                disabled={busy}
                className="p-0.5 rounded-md hover:scale-110 transition-transform disabled:pointer-events-none focus:outline-none focus-visible:ring-2 focus-visible:ring-jenny-coral/40"
              >
                <Star
                  className={cn(
                    "w-6 h-6 transition-colors",
                    n <= rating ? "text-jenny-warning" : "text-jenny-divider"
                  )}
                  fill={n <= rating ? "currentColor" : "none"}
                />
              </button>
            ))}
          </div>
          <input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Commentaire (optionnel)"
            className="mt-2.5 w-full h-10 px-3.5 rounded-xl bg-jenny-bg border border-jenny-divider text-[0.9rem] text-jenny-text placeholder:text-jenny-text-secondary/50 focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral transition-all"
          />
          <button
            type="button"
            onClick={() => onSubmitReview(rating, comment)}
            disabled={busy || rating === 0}
            className="mt-2.5 inline-flex items-center gap-1.5 h-9 px-3.5 rounded-xl bg-jenny-coral/12 text-jenny-coral text-[13px] font-semibold hover:bg-jenny-coral/20 transition-colors disabled:opacity-50 disabled:pointer-events-none"
          >
            <Star className="w-4 h-4" />
            Enregistrer l&apos;avis
          </button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 mt-5 pt-4 border-t border-jenny-divider/70">
        {appt.status !== "confirmed" && appt.status !== "cancelled" && (
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="inline-flex items-center gap-1.5 h-9 px-3.5 rounded-xl bg-jenny-success/12 text-jenny-success text-[13px] font-semibold hover:bg-jenny-success/20 transition-colors disabled:opacity-50 disabled:pointer-events-none"
          >
            <Check className="w-4 h-4" />
            Confirmer
          </button>
        )}
        {appt.status !== "cancelled" && (
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="inline-flex items-center gap-1.5 h-9 px-3.5 rounded-xl bg-jenny-warning/12 text-jenny-warning text-[13px] font-semibold hover:bg-jenny-warning/20 transition-colors disabled:opacity-50 disabled:pointer-events-none"
          >
            <X className="w-4 h-4" />
            Annuler le RDV
          </button>
        )}
        {canMarkNoShow && (
          <button
            type="button"
            onClick={onMarkNoShow}
            disabled={busy}
            className="inline-flex items-center gap-1.5 h-9 px-3.5 rounded-xl border border-jenny-warning/40 text-jenny-warning text-[13px] font-semibold hover:bg-jenny-warning/12 transition-colors disabled:opacity-50 disabled:pointer-events-none"
          >
            <UserX className="w-4 h-4" />
            Marquer absent
          </button>
        )}
        <button
          type="button"
          onClick={onDelete}
          disabled={busy}
          className="inline-flex items-center gap-1.5 h-9 px-3.5 rounded-xl bg-jenny-error/10 text-jenny-error text-[13px] font-semibold hover:bg-jenny-error/20 transition-colors disabled:opacity-50 disabled:pointer-events-none ml-auto"
        >
          <Trash className="w-4 h-4" />
          Supprimer
        </button>
      </div>
    </div>
  );
}

// ── Carte « Connecter Google Agenda » (présentationnel) ────────────────────

function GoogleConnectCard() {
  return (
    <div className="flex flex-wrap items-center gap-4 rounded-2xl border border-jenny-divider bg-jenny-surface p-4 md:p-5">
      <span className="w-11 h-11 rounded-xl bg-jenny-bg border border-jenny-divider flex items-center justify-center shrink-0">
        <GoogleGlyph />
      </span>
      <div className="min-w-0 flex-1">
        <div className="font-semibold text-jenny-text text-[14.5px]">Connecter Google Agenda</div>
        <p className="text-[13px] text-jenny-text-secondary mt-0.5">
          Synchronisez automatiquement vos rendez-vous avec votre agenda Google.
        </p>
      </div>
      <button
        type="button"
        className="inline-flex items-center gap-2 h-9 px-4 rounded-xl border border-jenny-divider bg-jenny-surface text-[13px] font-semibold text-jenny-text hover:border-jenny-text-secondary/30 transition-colors shrink-0"
      >
        <GoogleGlyph className="w-4 h-4" />
        Connecter
      </button>
    </div>
  );
}

// Logo Google « G » aux couleurs officielles (purement décoratif).
function GoogleGlyph({ className = "w-5 h-5" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M45.12 24.5c0-1.56-.14-3.06-.4-4.5H24v8.51h11.84c-.51 2.75-2.06 5.08-4.39 6.64v5.52h7.11c4.16-3.83 6.56-9.47 6.56-16.17z"
      />
      <path
        fill="#34A853"
        d="M24 46c5.94 0 10.92-1.97 14.56-5.33l-7.11-5.52c-1.97 1.32-4.49 2.1-7.45 2.1-5.73 0-10.58-3.87-12.31-9.07H4.34v5.7C7.96 41.07 15.4 46 24 46z"
      />
      <path
        fill="#FBBC05"
        d="M11.69 28.18c-.44-1.32-.69-2.73-.69-4.18s.25-2.86.69-4.18v-5.7H4.34A21.99 21.99 0 0 0 2 24c0 3.55.85 6.91 2.34 9.88l7.35-5.7z"
      />
      <path
        fill="#EA4335"
        d="M24 10.75c3.23 0 6.13 1.11 8.41 3.29l6.31-6.31C34.91 4.18 29.93 2 24 2 15.4 2 7.96 6.93 4.34 14.12l7.35 5.7c1.73-5.2 6.58-9.07 12.31-9.07z"
      />
    </svg>
  );
}

// ── États de chargement / erreur ────────────────────────────────────────────

function MonthSkeleton() {
  return (
    <div className="rounded-2xl border border-jenny-divider bg-jenny-surface overflow-hidden">
      <div className="grid grid-cols-7 border-b border-jenny-divider">
        {WEEKDAYS.map((d) => (
          <div key={d} className="px-2 py-2.5 text-center font-mono text-[11px] uppercase tracking-[0.12em] text-jenny-text-secondary">
            {d}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 auto-rows-fr">
        {Array.from({ length: 35 }).map((_, i) => (
          <div key={i} className="min-h-[104px] p-1.5 border-b border-r border-jenny-divider last:border-r-0">
            <div className="w-6 h-6 rounded-full animate-shimmer" />
            <div className="mt-2 h-4 rounded-md animate-shimmer" />
            {i % 3 === 0 && <div className="mt-1 h-4 rounded-md animate-shimmer" />}
          </div>
        ))}
      </div>
    </div>
  );
}

function WeekSkeleton() {
  return (
    <div className="rounded-2xl border border-jenny-divider bg-jenny-surface overflow-hidden">
      <div className="grid border-b border-jenny-divider" style={{ gridTemplateColumns: "56px repeat(7, 1fr)" }}>
        <div className="border-r border-jenny-divider" />
        {Array.from({ length: 7 }).map((_, i) => (
          <div key={i} className="px-2 py-3 flex flex-col items-center gap-1.5 border-r border-jenny-divider last:border-r-0">
            <div className="h-3 w-8 rounded animate-shimmer" />
            <div className="h-7 w-7 rounded-full animate-shimmer" />
          </div>
        ))}
      </div>
      <div className="p-3 space-y-2.5">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="h-9 rounded-md animate-shimmer" />
        ))}
      </div>
    </div>
  );
}

function ErrorBlock({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="rounded-2xl border border-jenny-divider bg-jenny-surface p-10 flex flex-col items-center text-center">
      <div className="w-14 h-14 rounded-2xl bg-jenny-error/10 text-jenny-error flex items-center justify-center mb-3">
        <X className="w-7 h-7" />
      </div>
      <h3 className="font-semibold text-jenny-text">Une erreur est survenue</h3>
      <p className="text-sm text-jenny-text-secondary max-w-sm mt-1">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 inline-flex items-center gap-1.5 h-9 px-4 rounded-xl bg-jenny-coral text-white text-[13px] font-semibold hover:bg-jenny-coral-dark transition-colors"
      >
        Réessayer
      </button>
    </div>
  );
}

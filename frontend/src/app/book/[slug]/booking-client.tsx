"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import Image from "next/image";
import { AnimatePresence, motion } from "framer-motion";
import { addDays, format, isSameDay, parseISO } from "date-fns";
import { fr } from "date-fns/locale";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  CalendarClock,
  Check,
  Clock,
  Loader2,
  MapPin,
} from "lucide-react";
import {
  ApiError,
  createBooking,
  getBookingInfo,
  getBookingSlots,
  type BookingBusinessInfo,
  type BookingConfirmation,
  type BookingSlot,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// ──────────────────────────────────────────────────────────────────────────
// Page publique de réservation — DA « Jenny Front »
//
// Plein écran nuit profonde, carte glass centrée. Flux en 4 temps :
//   1. chargement des infos business (404 → écran dédié) ;
//   2. choix d'une date (14 prochains jours) ;
//   3. choix d'un créneau (slots du jour) ;
//   4. formulaire + confirmation.
//
// Cette page est neutre : elle affiche le nom du BUSINESS, jamais « Jenny ».
// ──────────────────────────────────────────────────────────────────────────

const DURATION = 30; // minutes — durée de créneau (cf. spec back)
const DAYS_AHEAD = 14; // nombre de jours proposés dans le sélecteur

// Fond nuit profonde + halo corail (repris de la landing / login).
const PAGE_BG =
  "radial-gradient(ellipse at 70% -10%, rgba(255,127,106,0.20) 0%, transparent 52%), radial-gradient(ellipse at 0% 90%, rgba(114,132,168,0.12) 0%, transparent 50%), #0E0B14";

// Clé date locale "AAAA-MM-JJ" (jamais d'UTC : on raisonne en jour civil).
function toDateIso(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

// Majuscule initiale (les libellés date-fns `fr` sont en minuscules).
function cap(value: string): string {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

// Validation email volontairement simple (un @, un point après).
function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

type Phase = "loading" | "notfound" | "error" | "ready" | "confirmed";

// Une journée proposée dans le sélecteur de dates.
interface DayOption {
  date: Date;
  iso: string;
  weekday: string; // "lun."
  dayNum: string; // "16"
  month: string; // "juin"
}

export default function BookingClient({ slug }: { slug: string }) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [info, setInfo] = useState<BookingBusinessInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Date sélectionnée (clé ISO locale).
  const [selectedIso, setSelectedIso] = useState<string | null>(null);

  // Créneaux du jour sélectionné.
  const [slots, setSlots] = useState<BookingSlot[]>([]);
  const [slotsLoading, setSlotsLoading] = useState(false);
  const [slotsError, setSlotsError] = useState<string | null>(null);

  // Créneau choisi → ouvre le formulaire.
  const [chosenSlot, setChosenSlot] = useState<BookingSlot | null>(null);

  // Formulaire.
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [notes, setNotes] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Confirmation finale.
  const [confirmation, setConfirmation] = useState<BookingConfirmation | null>(null);

  // Les 14 prochains jours (à partir d'aujourd'hui inclus).
  const days = useMemo<DayOption[]>(() => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return Array.from({ length: DAYS_AHEAD }, (_, i) => {
      const date = addDays(today, i);
      return {
        date,
        iso: toDateIso(date),
        weekday: format(date, "EEE", { locale: fr }),
        dayNum: format(date, "d", { locale: fr }),
        month: format(date, "MMM", { locale: fr }),
      };
    });
  }, []);

  // ── 1. Chargement des infos business ──
  useEffect(() => {
    let active = true;
    setPhase("loading");
    getBookingInfo(slug)
      .then((data) => {
        if (!active) return;
        setInfo(data);
        setPhase("ready");
        // Par défaut : 1er jour proposé (aujourd'hui).
        setSelectedIso(toDateIso(new Date()));
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof ApiError && err.status === 404) {
          setPhase("notfound");
        } else {
          setLoadError(
            err instanceof ApiError
              ? "Le service de réservation est momentanément indisponible."
              : "Impossible de joindre le serveur. Réessayez dans un instant."
          );
          setPhase("error");
        }
      });
    return () => {
      active = false;
    };
  }, [slug]);

  // ── 3. Chargement des créneaux à chaque changement de date ──
  const loadSlots = useCallback(
    async (dateIso: string) => {
      setSlotsLoading(true);
      setSlotsError(null);
      try {
        const res = await getBookingSlots(slug, dateIso, DURATION);
        setSlots(res.slots);
      } catch (err) {
        setSlots([]);
        setSlotsError(
          err instanceof ApiError && err.status === 404
            ? "Page de réservation introuvable."
            : "Impossible de charger les créneaux. Réessayez."
        );
      } finally {
        setSlotsLoading(false);
      }
    },
    [slug]
  );

  useEffect(() => {
    if (phase !== "ready" || !selectedIso) return;
    void loadSlots(selectedIso);
  }, [phase, selectedIso, loadSlots]);

  // Changement de date → réinitialise le créneau choisi + le formulaire.
  const handleSelectDate = (iso: string) => {
    if (iso === selectedIso) return;
    setSelectedIso(iso);
    setChosenSlot(null);
    setFormError(null);
  };

  // ── 4. Soumission de la réservation ──
  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setFormError(null);

    if (!fullName.trim()) {
      setFormError("Merci d'indiquer votre nom complet.");
      return;
    }
    if (!isValidEmail(email)) {
      setFormError("Merci d'indiquer une adresse email valide.");
      return;
    }
    if (!chosenSlot) return;

    setSubmitting(true);
    try {
      const result = await createBooking(slug, {
        full_name: fullName.trim(),
        email: email.trim(),
        phone: phone.trim() || undefined,
        start_at: chosenSlot.start_at,
        duration: DURATION,
        notes: notes.trim() || undefined,
      });
      setConfirmation(result);
      setPhase("confirmed");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Le créneau vient d'être pris : on rafraîchit la grille et on y renvoie.
        setChosenSlot(null);
        setFormError(null);
        setSlotsError("Ce créneau vient d'être réservé. Choisissez-en un autre.");
        if (selectedIso) void loadSlots(selectedIso);
      } else if (err instanceof ApiError) {
        const detail = (err.data as { detail?: string } | undefined)?.detail;
        setFormError(detail || "La réservation a échoué. Réessayez dans un instant.");
      } else {
        setFormError("Impossible de joindre le serveur. Réessayez dans un instant.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const selectedDayLabel = useMemo(() => {
    if (!selectedIso) return "";
    const d = parseISO(selectedIso);
    return cap(format(d, "EEEE d MMMM", { locale: fr }));
  }, [selectedIso]);

  // ── Rendu ──
  return (
    <div
      className="min-h-full w-full overflow-y-auto text-[#F4F1ED]"
      style={{ background: PAGE_BG, fontFamily: "var(--font-sans)" }}
    >
      <div className="min-h-full flex flex-col items-center px-4 py-10 sm:py-14">
        {/* Mascotte + signature en en-tête */}
        <Header />

        <div className="w-full max-w-[540px]">
          <AnimatePresence mode="wait">
            {phase === "loading" && <LoadingCard key="loading" />}

            {phase === "notfound" && <NotFoundCard key="notfound" />}

            {phase === "error" && (
              <ErrorCard key="error" message={loadError ?? "Une erreur est survenue."} />
            )}

            {phase === "confirmed" && confirmation && (
              <ConfirmationCard key="confirmed" confirmation={confirmation} />
            )}

            {phase === "ready" && info && (
              <motion.div
                key="ready"
                initial={{ opacity: 0, y: 18 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -12 }}
                transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
                className="rounded-[24px] p-6 sm:p-8"
                style={{
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.09)",
                  boxShadow: "0 24px 60px rgba(0,0,0,0.35)",
                }}
              >
                {/* En-tête business */}
                <div className="font-mono text-[11px] tracking-[0.22em] uppercase text-jenny-coral mb-3">
                  — Réservation —
                </div>
                <h1 className="font-display font-normal text-[34px] sm:text-[42px] leading-[1.02] tracking-[-0.02em] mb-2">
                  {info.name}
                </h1>
                {info.description && (
                  <p className="text-[14.5px] leading-[1.55] text-[#F4F1ED]/60 mb-1">
                    {info.description}
                  </p>
                )}

                {!chosenSlot ? (
                  <>
                    {/* ── Étape 2 : choix de la date ── */}
                    <StepLabel index={1} total={2} text="Choisissez un jour" />
                    <DatePicker
                      days={days}
                      selectedIso={selectedIso}
                      onSelect={handleSelectDate}
                    />

                    {/* ── Étape 3 : choix du créneau ── */}
                    <StepLabel index={2} total={2} text={`Créneaux · ${selectedDayLabel}`} />
                    <SlotGrid
                      loading={slotsLoading}
                      error={slotsError}
                      slots={slots}
                      onPick={(slot) => {
                        setChosenSlot(slot);
                        setSlotsError(null);
                        setFormError(null);
                      }}
                    />
                  </>
                ) : (
                  /* ── Étape 4 : formulaire ── */
                  <BookingForm
                    businessName={info.name}
                    slot={chosenSlot}
                    fullName={fullName}
                    email={email}
                    phone={phone}
                    notes={notes}
                    error={formError}
                    submitting={submitting}
                    onChangeFullName={setFullName}
                    onChangeEmail={setEmail}
                    onChangePhone={setPhone}
                    onChangeNotes={setNotes}
                    onBack={() => {
                      setChosenSlot(null);
                      setFormError(null);
                    }}
                    onSubmit={handleSubmit}
                  />
                )}
              </motion.div>
            )}
          </AnimatePresence>

          {/* Pied de page neutre */}
          <p className="mt-7 text-center font-mono text-[11px] tracking-[0.12em] text-[#F4F1ED]/35">
            Réservation sécurisée · Propulsé par Jenny
          </p>
        </div>
      </div>
    </div>
  );
}

// ── En-tête : mascotte ──────────────────────────────────────────────────────

function Header() {
  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className="mb-7 flex flex-col items-center"
    >
      <span className="relative w-[60px] h-[60px] rounded-2xl overflow-hidden bg-jenny-coral block">
        <span
          className="absolute -inset-4"
          style={{
            background: "radial-gradient(circle, rgba(255,127,106,0.5) 0%, transparent 60%)",
            filter: "blur(14px)",
          }}
        />
        <Image
          src="/jenny.png"
          alt="Mascotte"
          width={60}
          height={60}
          priority
          className="relative object-cover w-full h-full"
        />
      </span>
    </motion.div>
  );
}

// ── Libellé d'étape (eyebrow mono) ──────────────────────────────────────────

function StepLabel({ index, total, text }: { index: number; total: number; text: string }) {
  return (
    <div className="mt-7 mb-3 flex items-center gap-2.5">
      <span className="font-mono text-[10px] tracking-[0.14em] uppercase text-jenny-coral/90 tabular-nums">
        {index}/{total}
      </span>
      <span className="text-[13px] font-semibold text-[#F4F1ED]/85">{text}</span>
    </div>
  );
}

// ── Sélecteur de date (chips des 14 prochains jours) ────────────────────────

function DatePicker({
  days,
  selectedIso,
  onSelect,
}: {
  days: DayOption[];
  selectedIso: string | null;
  onSelect: (iso: string) => void;
}) {
  const today = new Date();
  return (
    <div className="flex gap-2 overflow-x-auto pb-2 -mx-1 px-1 snap-x">
      {days.map((d) => {
        const active = d.iso === selectedIso;
        const isToday = isSameDay(d.date, today);
        return (
          <button
            key={d.iso}
            type="button"
            onClick={() => onSelect(d.iso)}
            aria-pressed={active}
            className={cn(
              "snap-start shrink-0 w-[60px] flex flex-col items-center gap-0.5 rounded-2xl py-2.5 transition-all duration-150",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-jenny-coral/40",
              active
                ? "bg-jenny-coral text-white shadow-md shadow-jenny-coral/25"
                : "text-[#F4F1ED]/75 hover:text-[#F4F1ED]"
            )}
            style={
              active
                ? undefined
                : { background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)" }
            }
          >
            <span
              className={cn(
                "font-mono text-[10px] uppercase tracking-[0.08em]",
                active ? "text-white/85" : "text-[#F4F1ED]/45"
              )}
            >
              {d.weekday.replace(".", "")}
            </span>
            <span className="text-[19px] font-semibold leading-none tabular-nums">{d.dayNum}</span>
            <span
              className={cn(
                "text-[10px] leading-none",
                active ? "text-white/80" : "text-[#F4F1ED]/40"
              )}
            >
              {isToday ? "auj." : d.month.replace(".", "")}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// ── Grille de créneaux ──────────────────────────────────────────────────────

function SlotGrid({
  loading,
  error,
  slots,
  onPick,
}: {
  loading: boolean;
  error: string | null;
  slots: BookingSlot[];
  onPick: (slot: BookingSlot) => void;
}) {
  if (loading) {
    return (
      <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="h-11 rounded-xl animate-pulse"
            style={{ background: "rgba(255,255,255,0.06)" }}
          />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="flex items-start gap-2.5 rounded-xl px-4 py-3 text-[13px] leading-relaxed text-jenny-coral"
        style={{ background: "rgba(255,127,106,0.10)", border: "1px solid rgba(255,127,106,0.22)" }}
      >
        <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
        <span>{error}</span>
      </div>
    );
  }

  if (slots.length === 0) {
    return (
      <div
        className="flex flex-col items-center text-center rounded-2xl px-5 py-8"
        style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
      >
        <span
          className="w-12 h-12 rounded-2xl flex items-center justify-center mb-3 text-jenny-coral"
          style={{ background: "rgba(255,127,106,0.12)" }}
        >
          <CalendarClock className="w-6 h-6" />
        </span>
        <p className="text-[14px] font-semibold text-[#F4F1ED]/90">Aucun créneau disponible ce jour</p>
        <p className="text-[13px] text-[#F4F1ED]/55 mt-1 max-w-[260px]">
          Choisissez une autre date ci-dessus pour voir les disponibilités.
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
      {slots.map((slot) => (
        <button
          key={slot.start_at}
          type="button"
          onClick={() => onPick(slot)}
          className={cn(
            "h-11 rounded-xl text-[14px] font-semibold tabular-nums transition-all duration-150",
            "text-[#F4F1ED]/90 hover:text-white hover:border-jenny-coral/60 hover:bg-jenny-coral/15",
            "active:scale-[0.97] focus:outline-none focus-visible:ring-2 focus-visible:ring-jenny-coral/40"
          )}
          style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.10)" }}
        >
          {slot.label}
        </button>
      ))}
    </div>
  );
}

// ── Formulaire de réservation ───────────────────────────────────────────────

function BookingForm({
  businessName,
  slot,
  fullName,
  email,
  phone,
  notes,
  error,
  submitting,
  onChangeFullName,
  onChangeEmail,
  onChangePhone,
  onChangeNotes,
  onBack,
  onSubmit,
}: {
  businessName: string;
  slot: BookingSlot;
  fullName: string;
  email: string;
  phone: string;
  notes: string;
  error: string | null;
  submitting: boolean;
  onChangeFullName: (v: string) => void;
  onChangeEmail: (v: string) => void;
  onChangePhone: (v: string) => void;
  onChangeNotes: (v: string) => void;
  onBack: () => void;
  onSubmit: (e: FormEvent) => void;
}) {
  const start = parseISO(slot.start_at);
  const inputClass =
    "w-full h-11 px-3.5 rounded-xl text-[14.5px] text-[#F4F1ED] placeholder:text-[#F4F1ED]/35 outline-none transition-all duration-150 focus:border-jenny-coral focus:ring-2 focus:ring-jenny-coral/25";
  const inputStyle = {
    background: "rgba(255,255,255,0.05)",
    border: "1px solid rgba(255,255,255,0.12)",
  } as const;

  return (
    <motion.div
      initial={{ opacity: 0, x: 16 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
    >
      {/* Récap du créneau sélectionné */}
      <button
        type="button"
        onClick={onBack}
        className="mt-7 group inline-flex items-center gap-2 text-[13px] font-medium text-[#F4F1ED]/55 hover:text-[#F4F1ED] transition-colors"
      >
        <ArrowLeft className="w-3.5 h-3.5 transition-transform group-hover:-translate-x-0.5" />
        Changer de créneau
      </button>

      <div
        className="mt-3 flex items-center gap-3 rounded-2xl px-4 py-3.5"
        style={{ background: "rgba(255,127,106,0.10)", border: "1px solid rgba(255,127,106,0.22)" }}
      >
        <span className="w-9 h-9 rounded-xl bg-jenny-coral/15 text-jenny-coral flex items-center justify-center shrink-0">
          <Clock className="w-5 h-5" />
        </span>
        <div className="min-w-0">
          <div className="text-[14px] font-semibold text-[#F4F1ED]">
            {cap(format(start, "EEEE d MMMM", { locale: fr }))} · {slot.label}
          </div>
          <div className="text-[12px] text-[#F4F1ED]/55 truncate">
            Avec {businessName} · {DURATION} min
          </div>
        </div>
      </div>

      <StepLabel index={2} total={2} text="Vos coordonnées" />

      <form onSubmit={onSubmit} className="flex flex-col gap-3.5">
        <div>
          <label
            htmlFor="bk-name"
            className="block font-mono text-[11px] font-semibold tracking-[0.06em] uppercase text-[#F4F1ED]/55 mb-1.5"
          >
            Nom complet *
          </label>
          <input
            id="bk-name"
            type="text"
            value={fullName}
            onChange={(e) => onChangeFullName(e.target.value)}
            placeholder="Sophie Martin"
            autoComplete="name"
            required
            className={inputClass}
            style={inputStyle}
          />
        </div>

        <div>
          <label
            htmlFor="bk-email"
            className="block font-mono text-[11px] font-semibold tracking-[0.06em] uppercase text-[#F4F1ED]/55 mb-1.5"
          >
            Email *
          </label>
          <input
            id="bk-email"
            type="email"
            value={email}
            onChange={(e) => onChangeEmail(e.target.value)}
            placeholder="sophie@exemple.com"
            autoComplete="email"
            required
            className={inputClass}
            style={inputStyle}
          />
        </div>

        <div>
          <label
            htmlFor="bk-phone"
            className="block font-mono text-[11px] font-semibold tracking-[0.06em] uppercase text-[#F4F1ED]/55 mb-1.5"
          >
            Téléphone <span className="text-[#F4F1ED]/35 normal-case font-normal tracking-normal">(optionnel)</span>
          </label>
          <input
            id="bk-phone"
            type="tel"
            value={phone}
            onChange={(e) => onChangePhone(e.target.value)}
            placeholder="06 12 34 56 78"
            autoComplete="tel"
            className={inputClass}
            style={inputStyle}
          />
        </div>

        <div>
          <label
            htmlFor="bk-notes"
            className="block font-mono text-[11px] font-semibold tracking-[0.06em] uppercase text-[#F4F1ED]/55 mb-1.5"
          >
            Note <span className="text-[#F4F1ED]/35 normal-case font-normal tracking-normal">(optionnel)</span>
          </label>
          <textarea
            id="bk-notes"
            value={notes}
            onChange={(e) => onChangeNotes(e.target.value)}
            placeholder="Précisez votre demande…"
            rows={3}
            className={cn(inputClass, "h-auto py-2.5 resize-none")}
            style={inputStyle}
          />
        </div>

        {error && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-start gap-2.5 rounded-xl px-3.5 py-3 text-[13px] leading-relaxed text-jenny-coral"
            style={{ background: "rgba(255,127,106,0.10)", border: "1px solid rgba(255,127,106,0.22)" }}
          >
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
            <span>{error}</span>
          </motion.div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full h-12 mt-1 rounded-xl bg-jenny-coral text-white text-[14.5px] font-semibold inline-flex items-center justify-center gap-2 transition-all duration-150 hover:bg-jenny-coral-dark active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none"
          style={{ boxShadow: "0 4px 14px rgba(255,127,106,0.25)" }}
        >
          {submitting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Réservation…
            </>
          ) : (
            <>
              Confirmer la réservation
              <ArrowRight className="w-4 h-4" />
            </>
          )}
        </button>
      </form>
    </motion.div>
  );
}

// ── Carte de confirmation ───────────────────────────────────────────────────

function ConfirmationCard({ confirmation }: { confirmation: BookingConfirmation }) {
  const start = parseISO(confirmation.start_at);
  const end = parseISO(confirmation.end_at);
  return (
    <motion.div
      key="confirmed"
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className="rounded-[24px] p-7 sm:p-9 text-center"
      style={{
        background: "rgba(255,255,255,0.04)",
        border: "1px solid rgba(255,255,255,0.09)",
        boxShadow: "0 24px 60px rgba(0,0,0,0.35)",
      }}
    >
      <motion.span
        initial={{ scale: 0.6, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ delay: 0.1, type: "spring", stiffness: 320, damping: 18 }}
        className="mx-auto mb-5 w-16 h-16 rounded-full bg-jenny-coral flex items-center justify-center"
        style={{ boxShadow: "0 10px 30px rgba(255,127,106,0.4)" }}
      >
        <Check className="w-8 h-8 text-white" strokeWidth={2.5} />
      </motion.span>

      <div className="font-mono text-[11px] tracking-[0.22em] uppercase text-jenny-coral mb-3">
        — Confirmé —
      </div>
      <h1 className="font-display font-normal text-[32px] sm:text-[40px] leading-[1.05] tracking-[-0.02em] mb-3">
        C&apos;est <span className="italic text-jenny-coral">réservé.</span>
      </h1>
      <p className="text-[14.5px] leading-[1.55] text-[#F4F1ED]/65 mb-6 max-w-[380px] mx-auto">
        {confirmation.message}
      </p>

      {/* Rappel date / heure */}
      <div
        className="rounded-2xl px-5 py-4 text-left flex items-center gap-3.5"
        style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.09)" }}
      >
        <span className="w-10 h-10 rounded-xl bg-jenny-coral/15 text-jenny-coral flex items-center justify-center shrink-0">
          <CalendarClock className="w-5 h-5" />
        </span>
        <div className="min-w-0">
          <div className="text-[15px] font-semibold text-[#F4F1ED]">
            {cap(format(start, "EEEE d MMMM yyyy", { locale: fr }))}
          </div>
          <div className="text-[13px] text-[#F4F1ED]/60 flex items-center gap-1.5 mt-0.5 tabular-nums">
            <Clock className="w-3.5 h-3.5" />
            {format(start, "HH:mm")} – {format(end, "HH:mm")}
          </div>
        </div>
      </div>

      <div className="mt-5 flex items-center justify-center gap-1.5 text-[13px] text-[#F4F1ED]/50">
        <MapPin className="w-3.5 h-3.5" />
        <span>Avec {confirmation.business_name}</span>
      </div>
    </motion.div>
  );
}

// ── Carte de chargement ─────────────────────────────────────────────────────

function LoadingCard() {
  return (
    <motion.div
      key="loading"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="rounded-[24px] p-7 sm:p-9 flex flex-col items-center"
      style={{
        background: "rgba(255,255,255,0.04)",
        border: "1px solid rgba(255,255,255,0.09)",
      }}
    >
      <Loader2 className="w-7 h-7 text-jenny-coral animate-spin mb-4" />
      <p className="text-[14px] text-[#F4F1ED]/60">Chargement des disponibilités…</p>
    </motion.div>
  );
}

// ── Carte « introuvable » (404) ─────────────────────────────────────────────

function NotFoundCard() {
  return (
    <motion.div
      key="notfound"
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
      className="rounded-[24px] p-7 sm:p-9 text-center"
      style={{
        background: "rgba(255,255,255,0.04)",
        border: "1px solid rgba(255,255,255,0.09)",
        boxShadow: "0 24px 60px rgba(0,0,0,0.35)",
      }}
    >
      <span
        className="mx-auto mb-5 w-14 h-14 rounded-2xl flex items-center justify-center text-jenny-coral"
        style={{ background: "rgba(255,127,106,0.12)" }}
      >
        <CalendarClock className="w-7 h-7" />
      </span>
      <div className="font-mono text-[11px] tracking-[0.22em] uppercase text-jenny-coral mb-3">
        — Introuvable —
      </div>
      <h1 className="font-display font-normal text-[30px] sm:text-[38px] leading-[1.05] tracking-[-0.02em] mb-3">
        Page de réservation <span className="italic text-jenny-coral">introuvable.</span>
      </h1>
      <p className="text-[14.5px] leading-[1.55] text-[#F4F1ED]/60 mb-6 max-w-[360px] mx-auto">
        Ce lien n&apos;existe pas ou n&apos;est plus actif. Vérifiez l&apos;adresse auprès de la
        personne qui vous l&apos;a transmis.
      </p>
      <Link
        href="/"
        className="inline-flex items-center gap-2 h-11 px-5 rounded-xl bg-jenny-coral text-white text-[14px] font-semibold hover:bg-jenny-coral-dark transition-colors"
        style={{ boxShadow: "0 4px 14px rgba(255,127,106,0.25)" }}
      >
        <ArrowLeft className="w-4 h-4" />
        Retour à l&apos;accueil
      </Link>
    </motion.div>
  );
}

// ── Carte d'erreur générique ────────────────────────────────────────────────

function ErrorCard({ message }: { message: string }) {
  return (
    <motion.div
      key="error"
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
      className="rounded-[24px] p-7 sm:p-9 text-center"
      style={{
        background: "rgba(255,255,255,0.04)",
        border: "1px solid rgba(255,255,255,0.09)",
        boxShadow: "0 24px 60px rgba(0,0,0,0.35)",
      }}
    >
      <span
        className="mx-auto mb-5 w-14 h-14 rounded-2xl flex items-center justify-center text-jenny-coral"
        style={{ background: "rgba(255,127,106,0.12)" }}
      >
        <AlertCircle className="w-7 h-7" />
      </span>
      <h1 className="font-display font-normal text-[30px] sm:text-[36px] leading-[1.05] tracking-[-0.02em] mb-3">
        Oups, un <span className="italic text-jenny-coral">contretemps.</span>
      </h1>
      <p className="text-[14.5px] leading-[1.55] text-[#F4F1ED]/60 max-w-[360px] mx-auto">
        {message}
      </p>
    </motion.div>
  );
}

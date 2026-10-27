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
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  CalendarDays,
  Check,
  Clock,
  Pencil,
  Plus,
  Power,
  Scissors,
  Trash,
  Users,
  X,
} from "lucide-react";
import {
  getBusiness,
  humanError,
  listPrestations,
  type BusinessHours,
  type Prestation,
} from "@/lib/api";
import {
  createStaff,
  deleteStaff,
  doesEverything,
  getStaffOccupancy,
  listStaff,
  updateStaff,
  type StaffHours,
  type StaffLoad,
  type StaffMember,
} from "@/lib/api-staff";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { useFocusTrap } from "@/lib/use-focus-trap";
import { cn } from "@/lib/utils";
import { easeOutExpo, fadeInUp, staggerContainer, staggerItem } from "@/lib/motion";

// jours dans l'ordre
const DAYS: { key: string; label: string }[] = [
  { key: "mon", label: "Lun" },
  { key: "tue", label: "Mar" },
  { key: "wed", label: "Mer" },
  { key: "thu", label: "Jeu" },
  { key: "fri", label: "Ven" },
  { key: "sat", label: "Sam" },
  { key: "sun", label: "Dim" },
];

// couleurs proposées
const SWATCHES = ["#e8735a", "#5b8def", "#43a882", "#b07ce8", "#e8b04a", "#3fb5c6", "#e86a9a", "#7c8796"];

const FALLBACK_HOURS: BusinessHours = {
  mon: ["09:00", "19:00"],
  tue: ["09:00", "19:00"],
  wed: ["09:00", "19:00"],
  thu: ["09:00", "19:00"],
  fri: ["09:00", "19:00"],
  sat: ["09:00", "18:00"],
  sun: null,
};

// résumé lisible des horaires
function hoursSummary(hours: StaffHours | null): string {
  if (!hours) return "Horaires du salon";
  const off = DAYS.filter((d) => d.key in hours && hours[d.key] === null).map((d) => d.label);
  const parts: string[] = [];
  // regroupe les jours qui se suivent
  let i = 0;
  while (i < DAYS.length) {
    const w = hours[DAYS[i].key];
    if (!w) {
      i++;
      continue;
    }
    let j = i;
    while (j + 1 < DAYS.length) {
      const n = hours[DAYS[j + 1].key];
      if (!n || n[0] !== w[0] || n[1] !== w[1]) break;
      j++;
    }
    const label = i === j ? DAYS[i].label : `${DAYS[i].label}–${DAYS[j].label}`;
    parts.push(`${label} ${w[0]}–${w[1]}`);
    i = j + 1;
  }
  if (off.length) parts.push(`repos ${off.join(", ")}`);
  return parts.join(" · ") || "Horaires du salon";
}

// formulaire

interface DayRow {
  on: boolean;
  start: string;
  end: string;
}

interface StaffForm {
  name: string;
  color: string;
  isActive: boolean;
  followSalon: boolean;
  days: Record<string, DayRow>;
  allServices: boolean; // sait tout faire
  prestationIds: string[];
  skillsTouched: boolean; // section modifiée ?
}

function daysFrom(hours: StaffHours | BusinessHours | null, salon: BusinessHours): Record<string, DayRow> {
  const out: Record<string, DayRow> = {};
  for (const d of DAYS) {
    const own = hours && d.key in hours ? hours[d.key] : salon[d.key];
    const base = salon[d.key] ?? ["09:00", "19:00"];
    out[d.key] = own
      ? { on: true, start: own[0], end: own[1] }
      : { on: false, start: base[0], end: base[1] };
  }
  return out;
}

function emptyForm(salon: BusinessHours, color: string): StaffForm {
  return {
    name: "",
    color,
    isActive: true,
    followSalon: true,
    days: daysFrom(null, salon),
    allServices: true,
    prestationIds: [],
    skillsTouched: false,
  };
}

function formFromStaff(m: StaffMember, salon: BusinessHours): StaffForm {
  return {
    name: m.display_name,
    color: m.color ?? SWATCHES[0],
    isActive: m.is_active,
    followSalon: m.working_hours === null,
    days: daysFrom(m.working_hours, salon),
    allServices: doesEverything(m),
    prestationIds: [...m.prestation_ids],
    skillsTouched: false,
  };
}

// page

export default function TeamPage() {
  const toast = useToast();
  const confirm = useConfirm();

  const [staff, setStaff] = useState<StaffMember[]>([]);
  const [prestations, setPrestations] = useState<Prestation[]>([]);
  // catalogue entier, inactives comprises
  const [catalogueSize, setCatalogueSize] = useState(0);
  const [load, setLoad] = useState<Record<string, StaffLoad>>({});
  const [salonHours, setSalonHours] = useState<BusinessHours>(FALLBACK_HOURS);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<StaffMember | null>(null);
  const [form, setForm] = useState<StaffForm>(() => emptyForm(FALLBACK_HOURS, SWATCHES[0]));
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const formRef = useRef<HTMLDivElement>(null);
  useFocusTrap(formOpen, formRef);

  const fetchAll = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [s, p, occ, biz] = await Promise.all([
        listStaff(),
        listPrestations(),
        getStaffOccupancy(7).catch(() => ({ days: 7, staff: [] as StaffLoad[] })),
        getBusiness().catch(() => null),
      ]);
      setStaff(s.staff);
      setPrestations(p.prestations.filter((x) => x.is_active));
      setCatalogueSize(p.prestations.length);
      setLoad(Object.fromEntries(occ.staff.map((l) => [l.staff_id, l])));
      if (biz?.business_hours) setSalonHours(biz.business_hours);
    } catch (err) {
      setError(humanError(err, "Impossible de charger l'équipe."));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const prestaName = useMemo(
    () => Object.fromEntries(prestations.map((p) => [p.id, p.name])),
    [prestations]
  );
  const activeCount = staff.filter((m) => m.is_active).length;

  // modales
  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm(salonHours, SWATCHES[staff.length % SWATCHES.length]));
    setFormOpen(true);
  };

  const openEdit = (m: StaffMember) => {
    setEditing(m);
    setForm(formFromStaff(m, salonHours));
    setFormOpen(true);
  };

  const closeForm = () => {
    if (!saving) setFormOpen(false);
  };

  const submitForm = async (e: FormEvent) => {
    e.preventDefault();
    const name = form.name.trim();
    if (!name) {
      toast.error("Le prénom est obligatoire.");
      return;
    }
    let working_hours: StaffHours | null = null;
    if (!form.followSalon) {
      working_hours = {};
      for (const d of DAYS) {
        const row = form.days[d.key];
        if (row.on && row.end <= row.start) {
          toast.error(`${d.label} : la fin doit suivre le début.`);
          return;
        }
        working_hours[d.key] = row.on ? [row.start, row.end] : null;
      }
    }
    // pas touchée : on garde, sauf catalogue vide
    const sendSkills = !editing || form.skillsTouched || catalogueSize === 0;
    // catalogue vraiment vide : fait tout
    const allServices = form.allServices || catalogueSize === 0;
    if (sendSkills && !allServices && !form.prestationIds.some((id) => prestaName[id])) {
      toast.error("Cochez au moins une prestation, ou « Toutes les prestations ».");
      return;
    }
    const payload = {
      display_name: name,
      color: form.color,
      is_active: form.isActive,
      working_hours,
      ...(sendSkills
        ? { all_services: allServices, prestation_ids: allServices ? [] : form.prestationIds }
        : {}),
    };
    setSaving(true);
    try {
      if (editing) {
        await updateStaff(editing.id, payload);
        toast.success(`${name} mis à jour.`);
      } else {
        await createStaff(payload);
        toast.success(`${name} rejoint l'équipe.`);
      }
      setFormOpen(false);
      await fetchAll();
    } catch (err) {
      toast.error(humanError(err, "Échec de l'enregistrement."));
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (m: StaffMember) => {
    setBusyId(m.id);
    try {
      await updateStaff(m.id, { is_active: !m.is_active });
      toast.success(m.is_active ? `${m.display_name} est en pause.` : `${m.display_name} est de retour.`);
      await fetchAll();
    } catch (err) {
      toast.error(humanError(err, "Échec de la mise à jour."));
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (m: StaffMember) => {
    const ok = await confirm({
      title: `Retirer ${m.display_name} ?`,
      message:
        m.upcoming_count > 0
          ? `${m.display_name} a ${m.upcoming_count} RDV à venir : il sera désactivé (historique gardé). Pensez à réattribuer ses RDV.`
          : `${m.display_name} sera retiré de l'équipe. S'il a un historique de RDV, il sera seulement désactivé.`,
      confirmLabel: "Retirer",
      danger: true,
    });
    if (!ok) return;
    setBusyId(m.id);
    try {
      const res = await deleteStaff(m.id);
      toast.success(
        res.status === "deleted" ? `${m.display_name} retiré.` : `${m.display_name} désactivé (RDV gardés).`
      );
      await fetchAll();
    } catch (err) {
      toast.error(humanError(err, "Échec de la suppression."));
    } finally {
      setBusyId(null);
    }
  };

  const togglePresta = (id: string) =>
    setForm((f) => ({
      ...f,
      skillsTouched: true,
      prestationIds: f.prestationIds.includes(id)
        ? f.prestationIds.filter((x) => x !== id)
        : [...f.prestationIds, id],
    }));

  const setDay = (key: string, patch: Partial<DayRow>) =>
    setForm((f) => ({ ...f, days: { ...f.days, [key]: { ...f.days[key], ...patch } } }));

  const fieldClass =
    "w-full h-11 px-3.5 rounded-xl bg-jenny-bg border border-jenny-divider text-[0.9rem] text-jenny-text " +
    "placeholder:text-jenny-text-secondary/50 focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral transition-all";
  const timeClass =
    "h-9 px-2 rounded-lg bg-jenny-bg border border-jenny-divider text-[0.85rem] text-jenny-text focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral disabled:opacity-40";

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto p-6 md:p-8 space-y-6">
        {/* en-tête */}
        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: easeOutExpo }}
          className="flex flex-wrap items-end gap-4"
        >
          <div>
            <div className="font-mono text-[11px] tracking-[0.22em] uppercase text-jenny-coral mb-2">
              — Équipe —
            </div>
            <h1 className="font-display text-[clamp(30px,5vw,42px)] leading-[1] tracking-[-0.02em] text-jenny-text">
              Vos <span className="italic text-jenny-coral">coiffeurs.</span>
            </h1>
            <p className="text-sm text-jenny-text-secondary mt-1">
              Chaque coiffeur a son fauteuil : Jenny réserve sur celui qui est libre et sait faire la prestation.
            </p>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {staff.length > 0 && (
              <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-jenny-text-secondary">
                {activeCount}/{staff.length} actif{activeCount > 1 ? "s" : ""}
              </span>
            )}
            <Link
              href="/calendar"
              className="inline-flex items-center gap-1.5 h-10 px-4 rounded-xl border border-jenny-divider bg-jenny-surface text-[13px] font-semibold text-jenny-text hover:border-jenny-text-secondary/30 transition-colors"
            >
              <CalendarDays className="w-4 h-4 text-jenny-coral" />
              Agenda
            </Link>
            <Button onClick={openCreate}>
              <Plus className="w-4 h-4" />
              Ajouter un coiffeur
            </Button>
          </div>
        </motion.div>

        {isLoading ? (
          <TeamSkeleton />
        ) : error ? (
          <ErrorBlock message={error} onRetry={fetchAll} />
        ) : staff.length === 0 ? (
          <EmptyTeam onCreate={openCreate} />
        ) : (
          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="show"
            className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-3"
          >
            <AnimatePresence mode="popLayout">
              {staff.map((m) => (
                <StaffCard
                  key={m.id}
                  member={m}
                  load={load[m.id]}
                  prestaName={prestaName}
                  emptyCatalogue={catalogueSize === 0}
                  busy={busyId === m.id}
                  onEdit={() => openEdit(m)}
                  onToggle={() => toggleActive(m)}
                  onDelete={() => remove(m)}
                />
              ))}
            </AnimatePresence>
          </motion.div>
        )}
      </div>

      {/* modale création / édition */}
      <AnimatePresence>
        {formOpen && (
          <Modal ref={formRef} label={editing ? "Modifier le coiffeur" : "Nouveau coiffeur"} onClose={closeForm}>
            <div className="flex items-center justify-between gap-3 mb-5">
              <h2 className="font-display text-[24px] leading-none tracking-[-0.01em] text-jenny-text">
                {editing ? (
                  <>
                    Modifier <span className="italic text-jenny-coral">{editing.display_name}.</span>
                  </>
                ) : (
                  <>
                    Nouveau <span className="italic text-jenny-coral">coiffeur.</span>
                  </>
                )}
              </h2>
              <button
                type="button"
                onClick={closeForm}
                aria-label="Fermer"
                className="w-8 h-8 inline-flex items-center justify-center rounded-lg text-jenny-text-secondary hover:bg-jenny-divider/40 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={submitForm} className="space-y-5">
              <Field label="Prénom" htmlFor="staff-name">
                <input
                  id="staff-name"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="Ex : Léa"
                  maxLength={120}
                  required
                  className={fieldClass}
                />
              </Field>

              {/* couleur agenda */}
              <div>
                <div className="text-[12.5px] font-semibold text-jenny-text mb-1.5">Couleur dans l&apos;agenda</div>
                <div className="flex flex-wrap items-center gap-2" role="radiogroup" aria-label="Couleur">
                  {SWATCHES.map((c) => (
                    <button
                      key={c}
                      type="button"
                      role="radio"
                      aria-checked={form.color === c}
                      aria-label={c}
                      onClick={() => setForm((f) => ({ ...f, color: c }))}
                      className={cn(
                        "w-7 h-7 rounded-full transition-transform hover:scale-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-jenny-coral/40",
                        form.color === c && "ring-2 ring-offset-2 ring-offset-jenny-surface ring-jenny-text"
                      )}
                      style={{ backgroundColor: c }}
                    />
                  ))}
                  <input
                    type="color"
                    value={form.color}
                    onChange={(e) => setForm((f) => ({ ...f, color: e.target.value }))}
                    aria-label="Couleur personnalisée"
                    className="w-8 h-8 rounded-lg border border-jenny-divider bg-transparent cursor-pointer"
                  />
                </div>
              </div>

              {/* prestations */}
              <div className="rounded-xl bg-jenny-bg border border-jenny-divider p-3.5">
                {prestations.length === 0 ? (
                  <>
                    <div className="text-[12.5px] font-semibold text-jenny-text mb-1">Prestations réalisées</div>
                    {catalogueSize === 0 ? (
                      <p className="text-[12.5px] text-jenny-text-secondary">
                        {editing && !doesEverything(editing)
                          ? "Aucune prestation dans le catalogue : en enregistrant, ce coiffeur fera tout."
                          : "Aucune prestation dans le catalogue : ce coiffeur fera tout."}{" "}
                        <Link href="/prestations" className="text-jenny-coral font-semibold hover:underline">
                          Créer le catalogue
                        </Link>
                      </p>
                    ) : (
                      <p className="text-[12.5px] text-jenny-text-secondary">
                        {editing
                          ? "Aucune prestation active pour l'instant : ses prestations restent inchangées."
                          : "Aucune prestation active pour l'instant : il pourra tout faire, à affiner quand le catalogue sera actif."}{" "}
                        <Link href="/prestations" className="text-jenny-coral font-semibold hover:underline">
                          Voir le catalogue
                        </Link>
                      </p>
                    )}
                  </>
                ) : (
                  <ToggleRow
                    label="Toutes les prestations"
                    hint={
                      form.allServices
                        ? "Jenny peut lui donner n'importe quel RDV."
                        : "Décoché : seulement les prestations cochées ci-dessous."
                    }
                    on={form.allServices}
                    onToggle={() =>
                      setForm((f) => ({ ...f, allServices: !f.allServices, skillsTouched: true }))
                    }
                  />
                )}
                {prestations.length > 0 && !form.allServices && (
                  <div className="mt-3 flex flex-wrap gap-1.5" role="group" aria-label="Prestations réalisées">
                    {prestations.map((p) => {
                      const on = form.prestationIds.includes(p.id);
                      return (
                        <button
                          key={p.id}
                          type="button"
                          aria-pressed={on}
                          onClick={() => togglePresta(p.id)}
                          className={cn(
                            "inline-flex items-center gap-1 h-8 px-3 rounded-full border text-[12.5px] font-medium transition-colors",
                            on
                              ? "bg-jenny-coral text-white border-jenny-coral"
                              : "bg-jenny-surface text-jenny-text border-jenny-divider hover:border-jenny-coral/40"
                          )}
                        >
                          {on && <Check className="w-3.5 h-3.5" />}
                          {p.name}
                        </button>
                      );
                    })}
                  </div>
                )}
                {prestations.length > 0 &&
                  !form.allServices &&
                  (!editing || form.skillsTouched) &&
                  !form.prestationIds.some((id) => prestaName[id]) && (
                    <p className="mt-2 text-[11.5px] text-jenny-warning">
                      Cochez au moins une prestation.
                    </p>
                  )}
              </div>

              {/* horaires */}
              <div className="rounded-xl bg-jenny-bg border border-jenny-divider p-3.5">
                <ToggleRow
                  label="Suit les horaires du salon"
                  hint="Décochez pour régler ses jours et heures."
                  on={form.followSalon}
                  onToggle={() => setForm((f) => ({ ...f, followSalon: !f.followSalon }))}
                />
                {!form.followSalon && (
                  <div className="mt-3 space-y-1.5">
                    {DAYS.map((d) => {
                      const row = form.days[d.key];
                      return (
                        <div key={d.key} className="flex items-center gap-2">
                          <label className="flex items-center gap-2 w-20 text-[12.5px] text-jenny-text cursor-pointer">
                            <input
                              type="checkbox"
                              checked={row.on}
                              onChange={() => setDay(d.key, { on: !row.on })}
                              className="accent-[var(--color-jenny-coral)]"
                            />
                            {d.label}
                          </label>
                          <input
                            type="time"
                            value={row.start}
                            disabled={!row.on}
                            onChange={(e) => setDay(d.key, { start: e.target.value })}
                            aria-label={`${d.label} début`}
                            className={timeClass}
                          />
                          <span className="text-jenny-text-secondary text-[12px]">→</span>
                          <input
                            type="time"
                            value={row.end}
                            disabled={!row.on}
                            onChange={(e) => setDay(d.key, { end: e.target.value })}
                            aria-label={`${d.label} fin`}
                            className={timeClass}
                          />
                          {!row.on && <span className="text-[11.5px] text-jenny-text-secondary">repos</span>}
                        </div>
                      );
                    })}
                    <p className="text-[11.5px] text-jenny-text-secondary pt-1">
                      Toujours limité aux heures d&apos;ouverture du salon.
                    </p>
                  </div>
                )}
              </div>

              <div className="rounded-xl bg-jenny-bg border border-jenny-divider px-3.5 py-3">
                <ToggleRow
                  label="Coiffeur actif"
                  hint="Inactif : Jenny ne lui donne plus de RDV."
                  on={form.isActive}
                  onToggle={() => setForm((f) => ({ ...f, isActive: !f.isActive }))}
                />
              </div>

              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={closeForm}
                  className="h-10 px-4 rounded-xl text-[13px] font-semibold text-jenny-text-secondary hover:bg-jenny-divider/40 transition-colors"
                >
                  Annuler
                </button>
                <Button type="submit" isLoading={saving}>
                  {editing ? <Check className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
                  {editing ? "Enregistrer" : "Ajouter"}
                </Button>
              </div>
            </form>
          </Modal>
        )}
      </AnimatePresence>
    </div>
  );
}

// carte coiffeur

function StaffCard({
  member,
  load,
  prestaName,
  emptyCatalogue,
  busy,
  onEdit,
  onToggle,
  onDelete,
}: {
  member: StaffMember;
  load?: StaffLoad;
  prestaName: Record<string, string>;
  emptyCatalogue: boolean;
  busy: boolean;
  onEdit: () => void;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const color = member.color ?? "var(--color-jenny-coral)";
  const skills = member.prestation_ids.map((id) => prestaName[id]).filter(Boolean);
  const rate = load ? Math.round(load.fill_rate * 100) : null;

  return (
    <motion.div
      layout
      variants={staggerItem}
      exit={{ opacity: 0, scale: 0.96 }}
      className={cn(
        "group relative flex flex-col rounded-2xl border bg-jenny-surface p-5 transition-all",
        "hover:shadow-md hover:shadow-black/[0.04] hover:border-jenny-coral/25",
        member.is_active ? "border-jenny-divider" : "border-jenny-divider/70 opacity-70"
      )}
    >
      <div className="flex items-start gap-3">
        <span
          className="w-11 h-11 rounded-full flex items-center justify-center shrink-0 text-white font-semibold text-[15px]"
          style={{ backgroundColor: color }}
          aria-hidden="true"
        >
          {member.display_name.charAt(0).toUpperCase()}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-[15px] text-jenny-text leading-snug break-words">
            {member.display_name}
          </h3>
          <span
            className={cn(
              "inline-flex items-center mt-1 px-2 py-0.5 rounded-full text-[11px] font-semibold",
              member.is_active ? "bg-jenny-success/12 text-jenny-success" : "bg-jenny-divider/60 text-jenny-text-secondary"
            )}
          >
            {member.is_active ? "Actif" : "En pause"}
          </span>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-1">
        {doesEverything(member) ? (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-jenny-coral/10 text-jenny-coral text-[11.5px] font-medium">
            <Scissors className="w-3 h-3" />
            Toutes les prestations
          </span>
        ) : skills.length === 0 ? (
          // prestations supprimées : à revoir
          <span
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-jenny-warning/12 text-jenny-warning text-[11.5px] font-medium"
            title={
              emptyCatalogue
                ? "Catalogue vide : ouvrez sa fiche et enregistrez, il fera tout."
                : "Ses prestations ont été supprimées ou désactivées : Jenny ne lui donne plus de RDV pour une prestation précise."
            }
          >
            <AlertTriangle className="w-3 h-3" />
            {emptyCatalogue ? "À revoir : catalogue vide" : "Aucune prestation, à compléter"}
          </span>
        ) : (
          skills.map((s) => (
            <span
              key={s}
              className="px-2 py-0.5 rounded-full bg-jenny-bg border border-jenny-divider text-[11.5px] text-jenny-text"
            >
              {s}
            </span>
          ))
        )}
      </div>

      <div className="flex items-start gap-1.5 mt-3 text-[12px] text-jenny-text-secondary">
        <Clock className="w-3.5 h-3.5 mt-0.5 shrink-0" />
        <span className="leading-snug">{hoursSummary(member.working_hours)}</span>
      </div>

      <div className="mt-4 pt-3.5 border-t border-jenny-divider/60">
        <div className="flex items-center justify-between text-[12px]">
          <span className="text-jenny-text-secondary">
            {member.upcoming_count} RDV à venir
          </span>
          {rate !== null && member.is_active && (
            <span className="font-mono text-[11px] text-jenny-text">{rate}% rempli · 7 j</span>
          )}
        </div>
        {rate !== null && member.is_active && (
          <div
            className="mt-1.5 h-1.5 rounded-full bg-jenny-divider/60 overflow-hidden"
            role="progressbar"
            aria-valuenow={rate}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`Remplissage de ${member.display_name}`}
          >
            <div className="h-full rounded-full transition-all" style={{ width: `${rate}%`, backgroundColor: color }} />
          </div>
        )}
      </div>

      {/* actions, toujours visibles */}
      <div className="mt-3 -mb-1 flex items-center justify-end gap-0.5">
        <IconBtn label={`Modifier ${member.display_name}`} onClick={onEdit} disabled={busy}>
          <Pencil className="w-4 h-4" />
        </IconBtn>
        <IconBtn
          label={member.is_active ? `Mettre ${member.display_name} en pause` : `Réactiver ${member.display_name}`}
          onClick={onToggle}
          disabled={busy}
        >
          <Power className="w-4 h-4" />
        </IconBtn>
        <IconBtn label={`Retirer ${member.display_name}`} onClick={onDelete} disabled={busy} danger>
          <Trash className={cn("w-4 h-4", busy && "animate-pulse")} />
        </IconBtn>
      </div>
    </motion.div>
  );
}

function IconBtn({
  label,
  onClick,
  disabled,
  danger,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={cn(
        "p-2 rounded-lg text-jenny-text-secondary transition-all disabled:opacity-50 disabled:pointer-events-none",
        danger ? "hover:text-jenny-error hover:bg-jenny-error/10" : "hover:text-jenny-coral hover:bg-jenny-coral/10"
      )}
    >
      {children}
    </button>
  );
}

function ToggleRow({
  label,
  hint,
  on,
  onToggle,
}: {
  label: string;
  hint: string;
  on: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div>
        <div className="text-[12.5px] font-semibold text-jenny-text">{label}</div>
        <div className="text-[11.5px] text-jenny-text-secondary mt-0.5">{hint}</div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={label}
        onClick={onToggle}
        className={cn("relative w-9 h-5 rounded-full shrink-0 transition-colors", on ? "bg-jenny-coral" : "bg-jenny-divider")}
      >
        <span
          className="absolute top-0.5 w-4 h-4 bg-white rounded-full shadow-sm transition-all"
          style={{ left: on ? 18 : 2 }}
        />
      </button>
    </div>
  );
}

// état vide

function EmptyTeam({ onCreate }: { onCreate: () => void }) {
  return (
    <motion.div
      variants={fadeInUp}
      initial="hidden"
      animate="show"
      className="rounded-2xl border border-jenny-divider bg-jenny-surface p-10 md:p-14 flex flex-col items-center text-center"
    >
      <div className="w-16 h-16 rounded-2xl bg-jenny-coral-tint dark:bg-jenny-coral/10 text-jenny-coral flex items-center justify-center mb-4">
        <Users className="w-8 h-8" />
      </div>
      <h3 className="font-display text-[22px] leading-tight tracking-[-0.01em] text-jenny-text">
        Vous travaillez seul(e) pour l&apos;instant
      </h3>
      <p className="text-sm text-jenny-text-secondary max-w-md mt-2">
        Sans coiffeur déclaré, Jenny gère un seul fauteuil. Ajoutez votre équipe pour prendre
        plusieurs clients à la même heure, chacun chez le bon coiffeur.
      </p>
      <Button onClick={onCreate} className="mt-6">
        <Plus className="w-4 h-4" />
        Ajouter le premier coiffeur
      </Button>
    </motion.div>
  );
}

// modale

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
        className="fixed left-1/2 top-1/2 z-[81] w-[min(94vw,520px)] max-h-[90vh] overflow-y-auto -translate-x-1/2 -translate-y-1/2 bg-jenny-surface border border-jenny-divider rounded-2xl shadow-2xl p-5"
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

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-[12.5px] font-semibold text-jenny-text">
        {label}
      </label>
      {children}
    </div>
  );
}

// chargement / erreur

function TeamSkeleton() {
  return (
    <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="rounded-2xl border border-jenny-divider bg-jenny-surface p-5">
          <div className="flex items-start gap-3">
            <div className="w-11 h-11 rounded-full animate-shimmer shrink-0" />
            <div className="flex-1 space-y-2">
              <div className="h-4 w-1/2 rounded-md animate-shimmer" />
              <div className="h-4 w-14 rounded-full animate-shimmer" />
            </div>
          </div>
          <div className="mt-4 h-4 w-3/4 rounded-md animate-shimmer" />
          <div className="mt-4 pt-3.5 border-t border-jenny-divider/60 h-4 rounded-md animate-shimmer" />
        </div>
      ))}
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

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
  Scissors,
  Clock,
  Euro,
  Plus,
  Pencil,
  Trash,
  Check,
  X,
  Sparkles,
} from "lucide-react";
import {
  listPrestations,
  createPrestation,
  updatePrestation,
  deletePrestation,
  seedCoiffeurTemplate,
  ApiError,
  type Prestation,
  type PrestationPayload,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useFocusTrap } from "@/lib/use-focus-trap";
import { cn } from "@/lib/utils";
import { easeOutExpo, fadeInUp, staggerContainer, staggerItem } from "@/lib/motion";

// ── Catégories de prestations ────────────────────────────────────────────────

type CategoryId = "coupe" | "couleur" | "coiffage" | "soin" | "barbe" | "autre";

const CATEGORIES: { id: CategoryId; label: string }[] = [
  { id: "coupe", label: "Coupe" },
  { id: "couleur", label: "Couleur" },
  { id: "coiffage", label: "Coiffage" },
  { id: "soin", label: "Soin" },
  { id: "barbe", label: "Barbe" },
  { id: "autre", label: "Autre" },
];

// Teinte du badge de catégorie (variables CSS → bascule clair/sombre auto).
const CATEGORY_META: Record<string, { label: string; className: string }> = {
  coupe: { label: "Coupe", className: "bg-jenny-coral/12 text-jenny-coral" },
  couleur: { label: "Couleur", className: "bg-jenny-success/12 text-jenny-success" },
  coiffage: { label: "Coiffage", className: "bg-jenny-warning/12 text-jenny-warning" },
  soin: { label: "Soin", className: "bg-jenny-slate/15 text-jenny-slate" },
  barbe: { label: "Barbe", className: "bg-jenny-coral/12 text-jenny-coral" },
  autre: { label: "Autre", className: "bg-jenny-divider/60 text-jenny-text-secondary" },
};

function categoryMeta(category: string) {
  return (
    CATEGORY_META[category] ?? {
      label: category || "Autre",
      className: "bg-jenny-divider/60 text-jenny-text-secondary",
    }
  );
}

function extractError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    return (err.data as { detail?: string })?.detail || `Erreur ${err.status}`;
  }
  return fallback;
}

// Prix entier → "39 €", prix décimal → "39,50 €".
function formatPrice(eur: number): string {
  const rounded = Math.round(eur * 100) / 100;
  const str = Number.isInteger(rounded)
    ? String(rounded)
    : rounded.toFixed(2).replace(".", ",");
  return `${str} €`;
}

// ── Formulaire (création / édition) ──────────────────────────────────────────

interface PrestationForm {
  name: string;
  category: CategoryId;
  duration: string; // minutes (champ number contrôlé en string)
  price: string; // euros (champ number contrôlé en string)
  description: string;
  isActive: boolean;
}

function emptyForm(): PrestationForm {
  return {
    name: "",
    category: "coupe",
    duration: "30",
    price: "",
    description: "",
    isActive: true,
  };
}

function formFromPrestation(p: Prestation): PrestationForm {
  const known = CATEGORIES.some((c) => c.id === p.category);
  return {
    name: p.name,
    category: (known ? p.category : "autre") as CategoryId,
    duration: String(p.duration_minutes ?? ""),
    price: p.price_eur != null ? String(p.price_eur) : "",
    description: p.description ?? "",
    isActive: p.is_active,
  };
}

// ── Page ──────────────────────────────────────────────────────────────────

export default function PrestationsPage() {
  const toast = useToast();

  const [prestations, setPrestations] = useState<Prestation[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [seeding, setSeeding] = useState(false);

  // Modale de création / édition.
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Prestation | null>(null);
  const [form, setForm] = useState<PrestationForm>(() => emptyForm());
  const [saving, setSaving] = useState(false);
  const formRef = useRef<HTMLDivElement>(null);
  useFocusTrap(formOpen, formRef);

  // Confirmation de suppression (id en attente) + état "en cours".
  const [confirmDelete, setConfirmDelete] = useState<Prestation | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const confirmRef = useRef<HTMLDivElement>(null);
  useFocusTrap(confirmDelete !== null, confirmRef);

  const fetchPrestations = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await listPrestations();
      // Tri stable : sort_order puis nom.
      const sorted = [...res.prestations].sort(
        (a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name, "fr")
      );
      setPrestations(sorted);
    } catch (err) {
      setError(
        extractError(
          err,
          "Impossible de charger les prestations. Vérifiez que le backend est démarré."
        )
      );
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPrestations();
  }, [fetchPrestations]);

  // ── Modèle coiffure (seed) ──
  const handleSeed = async () => {
    if (seeding) return;
    setSeeding(true);
    try {
      const res = await seedCoiffeurTemplate();
      toast.success(`Catalogue créé · ${res.prestations} prestation(s) ajoutée(s).`);
      await fetchPrestations();
    } catch (err) {
      toast.error(extractError(err, "Échec de la création du catalogue."));
    } finally {
      setSeeding(false);
    }
  };

  // ── Ouverture des modales ──
  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm());
    setFormOpen(true);
  };

  const openEdit = (p: Prestation) => {
    setEditing(p);
    setForm(formFromPrestation(p));
    setFormOpen(true);
  };

  const closeForm = () => {
    if (saving) return;
    setFormOpen(false);
  };

  // ── Soumission (création ou édition) ──
  const submitForm = async (e: FormEvent) => {
    e.preventDefault();
    const name = form.name.trim();
    if (!name) {
      toast.error("Le nom de la prestation est obligatoire.");
      return;
    }

    const duration = parseInt(form.duration, 10);
    if (!Number.isFinite(duration) || duration <= 0) {
      toast.error("La durée doit être un nombre de minutes positif.");
      return;
    }

    const priceEur = form.price.trim() === "" ? 0 : Number(form.price.replace(",", "."));
    if (!Number.isFinite(priceEur) || priceEur < 0) {
      toast.error("Le prix doit être un montant valide en euros.");
      return;
    }

    const payload: PrestationPayload = {
      name,
      category: form.category,
      duration_minutes: duration,
      price_cents: Math.round(priceEur * 100),
      description: form.description.trim() || null,
      is_active: form.isActive,
    };

    setSaving(true);
    try {
      if (editing) {
        await updatePrestation(editing.id, payload);
        toast.success("Prestation mise à jour.");
      } else {
        await createPrestation(payload);
        toast.success("Prestation ajoutée.");
      }
      setFormOpen(false);
      await fetchPrestations();
    } catch (err) {
      toast.error(extractError(err, "Échec de l'enregistrement de la prestation."));
    } finally {
      setSaving(false);
    }
  };

  // ── Suppression ──
  const removePrestation = async () => {
    if (!confirmDelete) return;
    const target = confirmDelete;
    setDeletingId(target.id);
    try {
      await deletePrestation(target.id);
      setPrestations((prev) => prev.filter((p) => p.id !== target.id));
      setConfirmDelete(null);
      toast.success("Prestation supprimée.");
    } catch (err) {
      toast.error(extractError(err, "Échec de la suppression."));
    } finally {
      setDeletingId(null);
    }
  };

  const activeCount = useMemo(
    () => prestations.filter((p) => p.is_active).length,
    [prestations]
  );

  // ── Champs partagés (style DA) ──
  const fieldClass =
    "w-full h-11 px-3.5 rounded-xl bg-jenny-bg border border-jenny-divider text-[0.9rem] text-jenny-text " +
    "placeholder:text-jenny-text-secondary/50 focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral transition-all";

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto p-6 md:p-8 space-y-6">
        {/* ── En-tête ── */}
        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: easeOutExpo }}
          className="flex flex-wrap items-end gap-4"
        >
          <div>
            <div className="font-mono text-[11px] tracking-[0.22em] uppercase text-jenny-coral mb-2">
              — Catalogue —
            </div>
            <h1 className="font-display text-[clamp(30px,5vw,42px)] leading-[1] tracking-[-0.02em] text-jenny-text">
              Vos <span className="italic text-jenny-coral">prestations.</span>
            </h1>
            <p className="text-sm text-jenny-text-secondary mt-1">
              Le catalogue que Jenny utilise pour conseiller, chiffrer et réserver.
            </p>
          </div>

          {prestations.length > 0 && (
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-jenny-text-secondary">
                {activeCount}/{prestations.length} active{activeCount > 1 ? "s" : ""}
              </span>
              <Button onClick={openCreate}>
                <Plus className="w-4 h-4" />
                Nouvelle prestation
              </Button>
            </div>
          )}
        </motion.div>

        {/* ── Contenu principal ── */}
        {isLoading ? (
          <PrestationsSkeleton />
        ) : error ? (
          <ErrorBlock message={error} onRetry={fetchPrestations} />
        ) : prestations.length === 0 ? (
          <EmptyCatalog onSeed={handleSeed} seeding={seeding} onCreate={openCreate} />
        ) : (
          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="show"
            className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-3"
          >
            <AnimatePresence mode="popLayout">
              {prestations.map((p) => (
                <PrestationCard
                  key={p.id}
                  prestation={p}
                  deleting={deletingId === p.id}
                  onEdit={() => openEdit(p)}
                  onDelete={() => setConfirmDelete(p)}
                />
              ))}
            </AnimatePresence>
          </motion.div>
        )}
      </div>

      {/* ── Modale : création / édition ── */}
      <AnimatePresence>
        {formOpen && (
          <Modal
            ref={formRef}
            label={editing ? "Modifier la prestation" : "Nouvelle prestation"}
            onClose={closeForm}
          >
            <div className="flex items-center justify-between gap-3 mb-5">
              <h2 className="font-display text-[24px] leading-none tracking-[-0.01em] text-jenny-text">
                {editing ? (
                  <>
                    Modifier la <span className="italic text-jenny-coral">prestation.</span>
                  </>
                ) : (
                  <>
                    Nouvelle <span className="italic text-jenny-coral">prestation.</span>
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

            <form onSubmit={submitForm} className="space-y-4">
              <Field label="Nom" htmlFor="presta-name">
                <input
                  id="presta-name"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="Ex : Coupe femme + brushing"
                  required
                  className={fieldClass}
                />
              </Field>

              <Field label="Catégorie" htmlFor="presta-category">
                <select
                  id="presta-category"
                  value={form.category}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, category: e.target.value as CategoryId }))
                  }
                  className={cn(fieldClass, "appearance-none cursor-pointer")}
                >
                  {CATEGORIES.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </Field>

              <div className="grid grid-cols-2 gap-4">
                <Field label="Durée (minutes)" htmlFor="presta-duration">
                  <input
                    id="presta-duration"
                    type="number"
                    min={1}
                    step={5}
                    inputMode="numeric"
                    value={form.duration}
                    onChange={(e) => setForm((f) => ({ ...f, duration: e.target.value }))}
                    placeholder="30"
                    required
                    className={fieldClass}
                  />
                </Field>
                <Field label="Prix (€)" htmlFor="presta-price">
                  <input
                    id="presta-price"
                    type="number"
                    min={0}
                    step="0.01"
                    inputMode="decimal"
                    value={form.price}
                    onChange={(e) => setForm((f) => ({ ...f, price: e.target.value }))}
                    placeholder="39"
                    className={fieldClass}
                  />
                </Field>
              </div>

              <Field label="Description (optionnel)" htmlFor="presta-description">
                <textarea
                  id="presta-description"
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  placeholder="Précisez ce qu'inclut la prestation…"
                  rows={3}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-jenny-bg border border-jenny-divider text-[0.9rem] text-jenny-text placeholder:text-jenny-text-secondary/50 focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral transition-all resize-none"
                />
              </Field>

              {/* Toggle actif */}
              <div className="flex items-center justify-between rounded-xl bg-jenny-bg border border-jenny-divider px-3.5 py-3">
                <div>
                  <div className="text-[12.5px] font-semibold text-jenny-text">
                    Prestation active
                  </div>
                  <div className="text-[11.5px] text-jenny-text-secondary mt-0.5">
                    Visible dans les conseils et la réservation.
                  </div>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={form.isActive}
                  aria-label="Prestation active"
                  onClick={() => setForm((f) => ({ ...f, isActive: !f.isActive }))}
                  className={cn(
                    "relative w-9 h-5 rounded-full shrink-0 transition-colors",
                    form.isActive ? "bg-jenny-coral" : "bg-jenny-divider"
                  )}
                >
                  <span
                    className="absolute top-0.5 w-4 h-4 bg-white rounded-full shadow-sm transition-all"
                    style={{ left: form.isActive ? 18 : 2 }}
                  />
                </button>
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
                  {editing ? (
                    <>
                      <Check className="w-4 h-4" />
                      Enregistrer
                    </>
                  ) : (
                    <>
                      <Plus className="w-4 h-4" />
                      Ajouter
                    </>
                  )}
                </Button>
              </div>
            </form>
          </Modal>
        )}
      </AnimatePresence>

      {/* ── Modale : confirmation de suppression ── */}
      <AnimatePresence>
        {confirmDelete && (
          <Modal
            ref={confirmRef}
            label="Supprimer la prestation"
            onClose={() => deletingId === null && setConfirmDelete(null)}
          >
            <div className="flex items-start gap-3.5">
              <span className="w-11 h-11 rounded-xl bg-jenny-error/10 text-jenny-error flex items-center justify-center shrink-0">
                <Trash className="w-5 h-5" />
              </span>
              <div className="min-w-0">
                <h2 className="font-display text-[20px] leading-tight tracking-[-0.01em] text-jenny-text">
                  Supprimer cette prestation ?
                </h2>
                <p className="text-[13.5px] text-jenny-text-secondary mt-1.5">
                  «&nbsp;{confirmDelete.name}&nbsp;» sera retirée du catalogue. Cette action est
                  définitive.
                </p>
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-6">
              <button
                type="button"
                onClick={() => setConfirmDelete(null)}
                disabled={deletingId !== null}
                className="h-10 px-4 rounded-xl text-[13px] font-semibold text-jenny-text-secondary hover:bg-jenny-divider/40 transition-colors disabled:opacity-50 disabled:pointer-events-none"
              >
                Annuler
              </button>
              <Button variant="danger" onClick={removePrestation} isLoading={deletingId !== null}>
                <Trash className="w-4 h-4" />
                Supprimer
              </Button>
            </div>
          </Modal>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Carte d'une prestation ────────────────────────────────────────────────

function PrestationCard({
  prestation,
  deleting,
  onEdit,
  onDelete,
}: {
  prestation: Prestation;
  deleting: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const meta = categoryMeta(prestation.category);
  const inactive = !prestation.is_active;

  return (
    <motion.div
      layout
      variants={staggerItem}
      exit={{ opacity: 0, scale: 0.96 }}
      className={cn(
        "group relative flex flex-col rounded-2xl border bg-jenny-surface p-5 transition-all",
        "hover:shadow-md hover:shadow-black/[0.04] hover:border-jenny-coral/25",
        inactive ? "border-jenny-divider/70 opacity-75" : "border-jenny-divider"
      )}
    >
      {/* En-tête carte : icône + catégorie + actions */}
      <div className="flex items-start gap-3">
        <span className="w-10 h-10 rounded-xl bg-jenny-coral-tint dark:bg-jenny-coral/10 text-jenny-coral flex items-center justify-center shrink-0">
          <Scissors className="w-5 h-5" />
        </span>
        <div className="min-w-0 flex-1">
          <span
            className={cn(
              "inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold",
              meta.className
            )}
          >
            {meta.label}
          </span>
          <h3 className="font-semibold text-[15px] text-jenny-text leading-snug mt-1.5 break-words">
            {prestation.name}
          </h3>
        </div>

        {/* Actions (apparaissent au survol, toujours présentes au focus clavier) */}
        <div className="flex items-center gap-0.5 shrink-0 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
          <button
            type="button"
            onClick={onEdit}
            aria-label={`Modifier ${prestation.name}`}
            title="Modifier"
            className="p-2 rounded-lg text-jenny-text-secondary hover:text-jenny-coral hover:bg-jenny-coral/10 transition-all"
          >
            <Pencil className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={onDelete}
            disabled={deleting}
            aria-label={`Supprimer ${prestation.name}`}
            title="Supprimer"
            className="p-2 rounded-lg text-jenny-text-secondary hover:text-jenny-error hover:bg-jenny-error/10 transition-all disabled:opacity-50 disabled:pointer-events-none"
          >
            <Trash className={cn("w-4 h-4", deleting && "animate-pulse")} />
          </button>
        </div>
      </div>

      {/* Description */}
      {prestation.description && (
        <p className="text-[12.5px] text-jenny-text-secondary leading-relaxed mt-3 line-clamp-2">
          {prestation.description}
        </p>
      )}

      {/* Pied : durée + prix + état */}
      <div className="flex items-center gap-3 mt-4 pt-3.5 border-t border-jenny-divider/60">
        <span className="inline-flex items-center gap-1.5 text-[12.5px] text-jenny-text-secondary">
          <Clock className="w-3.5 h-3.5" />
          {prestation.duration_minutes} min
        </span>
        <span className="inline-flex items-center gap-1 text-[13.5px] font-semibold text-jenny-text">
          <Euro className="w-3.5 h-3.5 text-jenny-coral" />
          {formatPrice(prestation.price_eur)}
        </span>
        {inactive && (
          <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.12em] text-jenny-text-secondary">
            Inactive
          </span>
        )}
      </div>
    </motion.div>
  );
}

// ── État vide (catalogue + modèle coiffure) ─────────────────────────────────

function EmptyCatalog({
  onSeed,
  seeding,
  onCreate,
}: {
  onSeed: () => void;
  seeding: boolean;
  onCreate: () => void;
}) {
  return (
    <motion.div
      variants={fadeInUp}
      initial="hidden"
      animate="show"
      className="rounded-2xl border border-jenny-divider bg-jenny-surface p-10 md:p-14 flex flex-col items-center text-center"
    >
      <div className="w-16 h-16 rounded-2xl bg-jenny-coral-tint dark:bg-jenny-coral/10 text-jenny-coral flex items-center justify-center mb-4">
        <Scissors className="w-8 h-8" />
      </div>
      <h3 className="font-display text-[22px] leading-tight tracking-[-0.01em] text-jenny-text">
        Aucune prestation pour le moment
      </h3>
      <p className="text-sm text-jenny-text-secondary max-w-md mt-2">
        Créez votre catalogue pour que Jenny puisse conseiller vos clients, annoncer les
        tarifs et proposer des créneaux. Démarrez avec un modèle coiffure prêt à l&apos;emploi,
        ou ajoutez vos prestations une par une.
      </p>
      <div className="flex flex-wrap items-center justify-center gap-2.5 mt-6">
        <Button onClick={onSeed} isLoading={seeding}>
          <Sparkles className="w-4 h-4" />
          Démarrer avec un modèle coiffure
        </Button>
        <Button variant="secondary" onClick={onCreate} disabled={seeding}>
          <Plus className="w-4 h-4" />
          Ajouter manuellement
        </Button>
      </div>
    </motion.div>
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

// ── États de chargement / erreur ────────────────────────────────────────────

function PrestationsSkeleton() {
  return (
    <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          key={i}
          className="rounded-2xl border border-jenny-divider bg-jenny-surface p-5"
        >
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl animate-shimmer shrink-0" />
            <div className="flex-1 space-y-2">
              <div className="h-4 w-16 rounded-full animate-shimmer" />
              <div className="h-4 w-3/4 rounded-md animate-shimmer" />
            </div>
          </div>
          <div className="mt-4 pt-3.5 border-t border-jenny-divider/60 flex gap-3">
            <div className="h-4 w-16 rounded-md animate-shimmer" />
            <div className="h-4 w-12 rounded-md animate-shimmer" />
          </div>
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

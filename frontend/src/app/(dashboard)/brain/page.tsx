"use client";

import {
  useState,
  useEffect,
  useCallback,
  useRef,
  type KeyboardEvent,
} from "react";
import Image from "next/image";
import { motion } from "framer-motion";
import { Plus, Check, Sparkles, X, Wallet, BellRing, CalendarOff, Trash } from "lucide-react";
import {
  getBusiness,
  updateBusiness,
  listClosures,
  createClosure,
  deleteClosure,
  type BusinessConfig,
  type JennyPersona,
  type Closure,
  ApiError,
} from "@/lib/api";
import { ErrorState } from "@/components/shared/error-state";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

// « Cerveau de Jenny » — page de configuration de la personnalité (DA handoff,
// recréation de l'écran `ScreenConfig`). Le chrome (Sidebar + Topbar) est fourni
// par le layout `(dashboard)` ; cette page ne rend que la zone de contenu.

// ── Tons disponibles (base, puis affinage) ──
const TONES = [
  { id: "pro", name: "Pro", desc: "Posé, courtois" },
  { id: "cool", name: "Cool", desc: "Décontracté, jeune" },
  { id: "vendeur", name: "Vendeur", desc: "Persuasif, direct" },
  { id: "chaleureux", name: "Chaleureux", desc: "Empathique" },
] as const;

type ToneId = (typeof TONES)[number]["id"];

// Curseurs 0–100 (le tutoiement est géré à part, comme un toggle).
const SLIDER_DEFS = [
  { key: "formel", label: "Formel ↔ Décontracté" },
  { key: "concision", label: "Concis ↔ Détaillé" },
  { key: "vente", label: "Discret ↔ Vendeur" },
] as const;

type SliderKey = (typeof SLIDER_DEFS)[number]["key"];

type Sliders = Record<SliderKey, number>;

interface Rule {
  label: string;
  on: boolean;
}

// Valeurs par défaut quand le business n'a pas encore de persona enregistrée :
// elles reflètent le mockup pour que l'écran « parle » dès la première visite.
const DEFAULT_SLIDERS: Sliders = { formel: 70, concision: 45, vente: 60 };
const DEFAULT_RULES: Rule[] = [
  { label: "Toujours répondre en français sauf si le client écrit en anglais", on: true },
  { label: "Ne jamais promettre une livraison < 48h", on: true },
  { label: "Toujours proposer un produit similaire si rupture", on: true },
  { label: "Transférer à un humain si demande de remboursement > 200€", on: true },
  { label: "Ne jamais mentionner les concurrents", on: false },
];

function extractError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    return (err.data as { detail?: string })?.detail || `Erreur ${err.status}`;
  }
  return fallback;
}

// La persona stocke des clés libres (#brain) ; on lit `sector` en tant qu'extra
// sans casser le type `JennyPersona`.
function readSector(persona: JennyPersona | null): string {
  if (!persona) return "";
  const sector = (persona as { sector?: unknown }).sector;
  return typeof sector === "string" ? sector : "";
}

export default function BrainPage() {
  const toast = useToast();

  // ── État de chargement ──
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // ── 01 · Identité ──
  const [name, setName] = useState("");
  const [sector, setSector] = useState("");
  const [description, setDescription] = useState("");

  // ── 02 · Ton de voix ──
  const [tone, setTone] = useState<ToneId>("cool");
  const [sliders, setSliders] = useState<Sliders>(DEFAULT_SLIDERS);
  const [tutoiement, setTutoiement] = useState(true);
  const [vocab, setVocab] = useState<string[]>([
    "l'atelier",
    "maison",
    "cuir tannage végétal",
    "pièce unique",
    "fait main",
  ]);
  const [vocabDraft, setVocabDraft] = useState("");

  // ── 03 · Règles d'or ──
  const [rules, setRules] = useState<Rule[]>(DEFAULT_RULES);
  const [ruleDraft, setRuleDraft] = useState("");
  const [addingRule, setAddingRule] = useState(false);

  // ── 04 · Acompte anti-no-show ──
  const [depositEnabled, setDepositEnabled] = useState(false);
  const [depositPercent, setDepositPercent] = useState(30);
  const [depositMinCents, setDepositMinCents] = useState(1000);

  // ── 05 · Rappels & fidélité ──
  const [reminderLeadMinutes, setReminderLeadMinutes] = useState(120);
  const [dayReminderLeadHours, setDayReminderLeadHours] = useState(24);
  const [loyaltyThreshold, setLoyaltyThreshold] = useState(0);

  // ── 06 · Fermetures exceptionnelles (état local, hors autosave) ──
  const [closures, setClosures] = useState<Closure[]>([]);
  const [closuresLoading, setClosuresLoading] = useState(true);
  const [closureStart, setClosureStart] = useState("");
  const [closureEnd, setClosureEnd] = useState("");
  const [closureReason, setClosureReason] = useState("");
  const [closureSubmitting, setClosureSubmitting] = useState(false);

  // Garde le premier chargement pour éviter un autosave au montage.
  const hydrated = useRef(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Empreinte du dernier état persisté : évite qu'un écho serveur (nouveaux
  // objets renvoyés par l'API) ne relance un autosave en boucle.
  const lastSaved = useRef<string>("");

  const applyBusiness = useCallback((b: BusinessConfig) => {
    setName(b.name || "");
    setDescription(b.description || "");
    const p = b.persona;
    setSector(readSector(p));
    if (p?.tone && TONES.some((t) => t.id === p.tone)) {
      setTone(p.tone as ToneId);
    }
    if (p?.sliders) {
      setSliders({
        formel: p.sliders.formel ?? DEFAULT_SLIDERS.formel,
        concision: p.sliders.concision ?? DEFAULT_SLIDERS.concision,
        vente: p.sliders.vente ?? DEFAULT_SLIDERS.vente,
      });
    }
    if (typeof p?.tutoiement === "boolean") setTutoiement(p.tutoiement);
    if (Array.isArray(p?.vocab)) setVocab(p.vocab);
    if (Array.isArray(p?.rules)) setRules(p.rules);
    if (typeof b.deposit_enabled === "boolean") setDepositEnabled(b.deposit_enabled);
    if (typeof b.deposit_percent === "number") setDepositPercent(b.deposit_percent);
    if (typeof b.deposit_min_cents === "number") setDepositMinCents(b.deposit_min_cents);
    if (typeof b.reminder_lead_minutes === "number") setReminderLeadMinutes(b.reminder_lead_minutes);
    if (typeof b.day_reminder_lead_hours === "number") setDayReminderLeadHours(b.day_reminder_lead_hours);
    if (typeof b.loyalty_threshold === "number") setLoyaltyThreshold(b.loyalty_threshold);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      applyBusiness(await getBusiness());
    } catch (err) {
      setLoadError(extractError(err, "Impossible de charger la configuration de Jenny."));
    } finally {
      setLoading(false);
    }
  }, [applyBusiness]);

  useEffect(() => {
    load();
  }, [load]);

  // Construit le payload à persister (identité + persona enrichie).
  const buildPayload = useCallback(
    () => ({
      name: name.trim(),
      description: description.trim() || null,
      persona: {
        tone,
        sliders,
        tutoiement,
        vocab,
        rules,
        sector: sector.trim(),
      } as JennyPersona,
      deposit_enabled: depositEnabled,
      deposit_percent: depositPercent,
      deposit_min_cents: depositMinCents,
      reminder_lead_minutes: reminderLeadMinutes,
      day_reminder_lead_hours: dayReminderLeadHours,
      loyalty_threshold: loyaltyThreshold,
    }),
    [
      name,
      description,
      tone,
      sliders,
      tutoiement,
      vocab,
      rules,
      sector,
      depositEnabled,
      depositPercent,
      depositMinCents,
      reminderLeadMinutes,
      dayReminderLeadHours,
      loyaltyThreshold,
    ]
  );

  const persist = useCallback(
    async (opts: { silent?: boolean } = {}) => {
      const payload = buildPayload();
      setSaving(true);
      try {
        const updated = await updateBusiness(payload);
        // On fige l'empreinte AVANT de réappliquer la réponse serveur, pour que
        // les nouveaux objets renvoyés ne déclenchent pas un nouvel autosave.
        lastSaved.current = JSON.stringify(payload);
        applyBusiness(updated);
        if (!opts.silent) toast.success("Personnalité de Jenny enregistrée.");
      } catch (err) {
        toast.error(extractError(err, "Échec de l'enregistrement."));
      } finally {
        setSaving(false);
      }
    },
    [buildPayload, applyBusiness, toast]
  );

  // ── Autosave débouncé (1,2 s après la dernière modification) ──
  useEffect(() => {
    if (loading || loadError) return;
    const snapshot = JSON.stringify(buildPayload());
    if (!hydrated.current) {
      hydrated.current = true;
      lastSaved.current = snapshot; // état initial chargé = déjà « sauvé »
      return;
    }
    if (snapshot === lastSaved.current) return; // simple écho serveur → on ignore
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      void persist({ silent: true });
    }, 1200);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
    // On dépend des valeurs de formulaire (via buildPayload), pas de `persist`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    name,
    sector,
    description,
    tone,
    sliders,
    tutoiement,
    vocab,
    rules,
    depositEnabled,
    depositPercent,
    depositMinCents,
    reminderLeadMinutes,
    dayReminderLeadHours,
    loyaltyThreshold,
  ]);

  // ── Fermetures exceptionnelles : chargement + actions (état local) ──
  const loadClosures = useCallback(async () => {
    setClosuresLoading(true);
    try {
      setClosures(await listClosures());
    } catch (err) {
      toast.error(extractError(err, "Impossible de charger les fermetures."));
    } finally {
      setClosuresLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void loadClosures();
  }, [loadClosures]);

  const addClosure = async () => {
    if (!closureStart || closureSubmitting) return;
    setClosureSubmitting(true);
    try {
      await createClosure({
        start_date: closureStart,
        end_date: closureEnd || undefined,
        reason: closureReason.trim() || null,
      });
      setClosureStart("");
      setClosureEnd("");
      setClosureReason("");
      await loadClosures();
      toast.success("Fermeture ajoutée.");
    } catch (err) {
      toast.error(extractError(err, "Échec de l'ajout de la fermeture."));
    } finally {
      setClosureSubmitting(false);
    }
  };

  const removeClosure = async (id: string) => {
    try {
      await deleteClosure(id);
      await loadClosures();
      toast.success("Fermeture supprimée.");
    } catch (err) {
      toast.error(extractError(err, "Échec de la suppression."));
    }
  };

  // Affiche une date ISO (AAAA-MM-JJ) au format français JJ/MM/AAAA.
  const formatDate = (iso: string): string => {
    const [y, m, d] = iso.slice(0, 10).split("-");
    return y && m && d ? `${d}/${m}/${y}` : iso;
  };

  // ── Helpers vocabulaire ──
  const addVocab = () => {
    const v = vocabDraft.trim();
    if (!v || vocab.includes(v)) {
      setVocabDraft("");
      return;
    }
    setVocab((prev) => [...prev, v]);
    setVocabDraft("");
  };
  const removeVocab = (w: string) => setVocab((prev) => prev.filter((x) => x !== w));
  const onVocabKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addVocab();
    } else if (e.key === "Backspace" && !vocabDraft && vocab.length) {
      setVocab((prev) => prev.slice(0, -1));
    }
  };

  // ── Helpers règles ──
  const toggleRule = (i: number) =>
    setRules((prev) => prev.map((r, idx) => (idx === i ? { ...r, on: !r.on } : r)));
  const removeRule = (i: number) => setRules((prev) => prev.filter((_, idx) => idx !== i));
  const addRule = () => {
    const l = ruleDraft.trim();
    if (!l) {
      setAddingRule(false);
      return;
    }
    setRules((prev) => [...prev, { label: l, on: true }]);
    setRuleDraft("");
    setAddingRule(false);
  };

  const toneLabel = (TONES.find((t) => t.id === tone)?.name || "Cool").toUpperCase();

  // ── Input partagé (style DA : fond clair, bord divider, radius 10) ──
  const fieldClass =
    "w-full h-[42px] px-3.5 rounded-[10px] bg-jenny-bg border border-jenny-divider text-[13.5px] text-jenny-text " +
    "placeholder:text-jenny-text-secondary/50 focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral transition-all";

  const eyebrowClass =
    "font-mono text-[10px] tracking-[0.18em] uppercase text-jenny-text-secondary font-semibold";

  if (loading) {
    return (
      <div className="h-full overflow-y-auto">
        <div className="max-w-[1180px] mx-auto px-6 md:px-8 py-7">
          <div className="grid lg:grid-cols-[1fr_360px] gap-7 items-start">
            <div className="space-y-4">
              <div className="h-12 w-2/3 rounded-xl animate-shimmer" />
              <div className="h-40 rounded-2xl animate-shimmer" />
              <div className="h-72 rounded-2xl animate-shimmer" />
              <div className="h-56 rounded-2xl animate-shimmer" />
            </div>
            <div className="h-[520px] rounded-3xl animate-shimmer" />
          </div>
        </div>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="h-full overflow-y-auto">
        <div className="max-w-[1180px] mx-auto px-6 md:px-8 py-7">
          <ErrorState message={loadError} onRetry={load} />
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-[1180px] mx-auto px-6 md:px-8 py-7">
        <div className="grid lg:grid-cols-[1fr_360px] gap-7 items-start">
          {/* ════════ Colonne formulaire ════════ */}
          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
            <div className="font-mono text-[11px] tracking-[0.22em] uppercase text-jenny-coral mb-3">
              — le cerveau de jenny —
            </div>
            <h1 className="font-display font-normal text-[clamp(34px,5vw,48px)] leading-[1.05] tracking-[-0.02em] mb-3.5">
              Apprenez-lui à <span className="italic text-jenny-coral">vous ressembler.</span>
            </h1>
            <p className="text-[14.5px] text-jenny-text-secondary max-w-[560px] leading-[1.55] mb-8">
              Plus vous donnez de contexte, plus Jenny répond comme vous l&apos;auriez fait. Tout se
              sauvegarde automatiquement.
            </p>

            {/* ── 01 · Identité ── */}
            <motion.section
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.05 }}
              className="bg-jenny-surface rounded-2xl border border-jenny-divider p-6 mb-[18px]"
            >
              <div className={cn(eyebrowClass, "mb-[18px]")}>01 · Identité</div>
              <div className="grid sm:grid-cols-2 gap-3.5 mb-3.5">
                <div>
                  <label htmlFor="biz-name" className="block text-xs font-semibold text-jenny-text mb-1.5">
                    Nom du business
                  </label>
                  <input
                    id="biz-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Maison Lila"
                    className={fieldClass}
                  />
                </div>
                <div>
                  <label htmlFor="biz-sector" className="block text-xs font-semibold text-jenny-text mb-1.5">
                    Secteur
                  </label>
                  <input
                    id="biz-sector"
                    value={sector}
                    onChange={(e) => setSector(e.target.value)}
                    placeholder="Maroquinerie artisanale"
                    className={fieldClass}
                  />
                </div>
              </div>
              <div>
                <label htmlFor="biz-desc" className="block text-xs font-semibold text-jenny-text mb-1.5">
                  Description courte (Jenny l&apos;utilise pour se présenter)
                </label>
                <textarea
                  id="biz-desc"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Présentez votre activité en quelques mots…"
                  rows={3}
                  className="w-full px-3.5 py-3 rounded-[10px] bg-jenny-bg border border-jenny-divider text-[13.5px] text-jenny-text leading-[1.5] placeholder:text-jenny-text-secondary/50 focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral transition-all resize-y min-h-[72px]"
                />
              </div>
            </motion.section>

            {/* ── 02 · Ton de voix ── */}
            <motion.section
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              className="bg-jenny-surface rounded-2xl border border-jenny-divider p-6 mb-[18px]"
            >
              <div className={cn(eyebrowClass, "mb-1.5")}>02 · Ton de voix</div>
              <div className="text-[13px] text-jenny-text-secondary mb-[18px]">
                Choisissez la base, puis affinez.
              </div>

              {/* Cartes de ton */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-5">
                {TONES.map((t) => {
                  const active = t.id === tone;
                  return (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => setTone(t.id)}
                      aria-pressed={active}
                      className={cn(
                        "text-left p-3.5 rounded-xl transition-all",
                        active
                          ? "bg-jenny-coral-tint border-2 border-jenny-coral"
                          : "bg-white border border-jenny-divider hover:border-jenny-coral/40"
                      )}
                    >
                      <div className="text-sm font-semibold mb-0.5 text-jenny-text">{t.name}</div>
                      <div className="text-[11.5px] text-jenny-text-secondary leading-snug">{t.desc}</div>
                    </button>
                  );
                })}
              </div>

              {/* Curseurs 0–100 */}
              {SLIDER_DEFS.map((s) => (
                <div key={s.key} className="mb-3.5">
                  <div className="flex justify-between mb-[7px]">
                    <span className="text-[12.5px] text-jenny-text font-medium">{s.label}</span>
                    <span className="text-[11px] font-mono text-jenny-text-secondary">
                      {sliders[s.key]}%
                    </span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={sliders[s.key]}
                    onChange={(e) =>
                      setSliders((prev) => ({ ...prev, [s.key]: Number(e.target.value) }))
                    }
                    aria-label={s.label}
                    className="jenny-range w-full"
                    style={{ ["--pct" as string]: `${sliders[s.key]}%` }}
                  />
                </div>
              ))}

              {/* Tutoiement — toggle */}
              <div className="mb-5">
                <div className="flex justify-between items-center mb-[7px]">
                  <span className="text-[12.5px] text-jenny-text font-medium">Tutoiement</span>
                  <span className="text-[11px] font-mono text-jenny-text-secondary">
                    {tutoiement ? "OUI" : "NON"}
                  </span>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={tutoiement}
                  aria-label="Tutoiement"
                  onClick={() => setTutoiement((v) => !v)}
                  className={cn(
                    "relative w-9 h-5 rounded-full transition-colors",
                    tutoiement ? "bg-jenny-coral" : "bg-jenny-divider"
                  )}
                >
                  <span
                    className="absolute top-0.5 w-4 h-4 bg-white rounded-full shadow-sm transition-all"
                    style={{ left: tutoiement ? 18 : 2 }}
                  />
                </button>
              </div>

              {/* Vocabulaire — chips */}
              <div>
                <label className="block text-xs font-semibold text-jenny-text mb-1.5">
                  Mots et expressions à utiliser
                </label>
                <div className="flex flex-wrap gap-1.5 p-2.5 bg-jenny-bg border border-jenny-divider rounded-[10px] min-h-[46px]">
                  {vocab.map((w) => (
                    <span
                      key={w}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-white border border-jenny-divider rounded-full text-[12.5px] text-jenny-text"
                    >
                      {w}
                      <button
                        type="button"
                        onClick={() => removeVocab(w)}
                        aria-label={`Retirer ${w}`}
                        className="text-jenny-text-secondary/60 hover:text-jenny-coral transition-colors"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                  <input
                    value={vocabDraft}
                    onChange={(e) => setVocabDraft(e.target.value)}
                    onKeyDown={onVocabKey}
                    onBlur={addVocab}
                    placeholder="+ ajouter…"
                    aria-label="Ajouter un mot ou une expression"
                    className="flex-1 min-w-[100px] bg-transparent text-[12.5px] text-jenny-text placeholder:text-jenny-text-secondary/60 outline-none px-1.5"
                  />
                </div>
              </div>
            </motion.section>

            {/* ── 03 · Règles d'or ── */}
            <motion.section
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.15 }}
              className="bg-jenny-surface rounded-2xl border border-jenny-divider p-6"
            >
              <div className={cn(eyebrowClass, "mb-[18px]")}>03 · Règles d&apos;or</div>
              {rules.length === 0 && (
                <p className="text-[13px] text-jenny-text-secondary py-2">
                  Aucune règle pour le moment. Ajoutez-en une pour cadrer Jenny.
                </p>
              )}
              {rules.map((r, i) => (
                <div
                  key={`${r.label}-${i}`}
                  className={cn(
                    "group flex items-center gap-3 py-3",
                    i < rules.length - 1 && "border-b border-jenny-divider/60"
                  )}
                >
                  <span className="flex-1 text-[13.5px] text-jenny-text">{r.label}</span>
                  <button
                    type="button"
                    onClick={() => removeRule(i)}
                    aria-label={`Supprimer la règle : ${r.label}`}
                    className="opacity-0 group-hover:opacity-100 text-jenny-text-secondary/50 hover:text-jenny-error transition-all"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={r.on}
                    aria-label={`Activer la règle : ${r.label}`}
                    onClick={() => toggleRule(i)}
                    className={cn(
                      "relative w-9 h-5 rounded-full shrink-0 transition-colors",
                      r.on ? "bg-jenny-coral" : "bg-jenny-divider"
                    )}
                  >
                    <span
                      className="absolute top-0.5 w-4 h-4 bg-white rounded-full shadow-sm transition-all"
                      style={{ left: r.on ? 18 : 2 }}
                    />
                  </button>
                </div>
              ))}

              {addingRule ? (
                <div className="flex items-center gap-2 mt-3">
                  <input
                    autoFocus
                    value={ruleDraft}
                    onChange={(e) => setRuleDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        addRule();
                      } else if (e.key === "Escape") {
                        setRuleDraft("");
                        setAddingRule(false);
                      }
                    }}
                    onBlur={addRule}
                    placeholder="Décrivez la règle…"
                    aria-label="Nouvelle règle"
                    className={fieldClass}
                  />
                  <button
                    type="button"
                    onClick={addRule}
                    aria-label="Valider la règle"
                    className="h-[42px] px-3 rounded-[10px] bg-jenny-coral text-white inline-flex items-center justify-center hover:bg-jenny-coral-dark transition-colors shrink-0"
                  >
                    <Check className="w-4 h-4" />
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setAddingRule(true)}
                  className="inline-flex items-center gap-1.5 mt-3 h-9 px-3.5 rounded-xl text-[0.8125rem] font-semibold text-jenny-text-secondary hover:text-jenny-text hover:bg-jenny-divider/40 transition-all"
                >
                  <Plus className="w-[13px] h-[13px]" />
                  Ajouter une règle
                </button>
              )}
            </motion.section>

            {/* ── 04 · Acompte anti-no-show ── */}
            <motion.section
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              className="bg-jenny-surface rounded-2xl border border-jenny-divider p-6 mt-[18px]"
            >
              <div className={cn(eyebrowClass, "mb-1.5")}>04 · Acompte anti-no-show</div>
              <div className="text-[13px] text-jenny-text-secondary mb-[18px]">
                Demander un acompte réduit fortement les rendez-vous manqués.
              </div>

              {/* Activation — toggle (même style que le tutoiement) */}
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <span className="block text-[13.5px] text-jenny-text font-medium">
                    Demander un acompte
                  </span>
                  <span className="block text-[12px] text-jenny-text-secondary">
                    Jenny réclame un acompte avant de confirmer le rendez-vous.
                  </span>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={depositEnabled}
                  aria-label="Demander un acompte"
                  onClick={() => setDepositEnabled((v) => !v)}
                  className={cn(
                    "relative w-9 h-5 rounded-full shrink-0 transition-colors",
                    depositEnabled ? "bg-jenny-coral" : "bg-jenny-divider"
                  )}
                >
                  <span
                    className="absolute top-0.5 w-4 h-4 bg-white rounded-full shadow-sm transition-all"
                    style={{ left: depositEnabled ? 18 : 2 }}
                  />
                </button>
              </div>

              {depositEnabled && (
                <div className="grid sm:grid-cols-2 gap-3.5 mt-[18px]">
                  <div>
                    <label
                      htmlFor="deposit-percent"
                      className="block text-xs font-semibold text-jenny-text mb-1.5"
                    >
                      Pourcentage du prix demandé en acompte
                    </label>
                    <div className="relative">
                      <input
                        id="deposit-percent"
                        type="number"
                        min={0}
                        max={100}
                        value={depositPercent}
                        onChange={(e) => {
                          const n = Number(e.target.value);
                          setDepositPercent(
                            Number.isNaN(n) ? 0 : Math.min(100, Math.max(0, n))
                          );
                        }}
                        className={cn(fieldClass, "pr-9")}
                      />
                      <span className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-[13px] text-jenny-text-secondary">
                        %
                      </span>
                    </div>
                  </div>
                  <div>
                    <label
                      htmlFor="deposit-forfait"
                      className="block text-xs font-semibold text-jenny-text mb-1.5"
                    >
                      Acompte forfaitaire si prix inconnu (€)
                    </label>
                    <input
                      id="deposit-forfait"
                      type="number"
                      min={0}
                      step="0.01"
                      value={depositMinCents / 100}
                      onChange={(e) => {
                        const euros = Number(e.target.value);
                        setDepositMinCents(
                          Number.isNaN(euros) ? 0 : Math.max(0, Math.round(euros * 100))
                        );
                      }}
                      className={fieldClass}
                    />
                  </div>
                </div>
              )}

              <div className="flex items-center gap-1.5 mt-4 text-[12px] text-jenny-text-secondary">
                <Wallet className="w-3.5 h-3.5 text-jenny-coral shrink-0" />
                Demander un acompte réduit fortement les rendez-vous manqués.
              </div>
            </motion.section>

            {/* ── 05 · Rappels & fidélité ── */}
            <motion.section
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.22 }}
              className="bg-jenny-surface rounded-2xl border border-jenny-divider p-6 mt-[18px]"
            >
              <div className={cn(eyebrowClass, "mb-1.5")}>05 · Rappels &amp; fidélité</div>
              <div className="text-[13px] text-jenny-text-secondary mb-[18px]">
                Quand Jenny relance vos clients et à partir de combien de visites elle les récompense.
              </div>

              <div className="grid sm:grid-cols-2 gap-3.5">
                <div>
                  <label
                    htmlFor="reminder-lead"
                    className="block text-xs font-semibold text-jenny-text mb-1.5"
                  >
                    Rappel imminent (minutes avant le RDV)
                  </label>
                  <input
                    id="reminder-lead"
                    type="number"
                    min={5}
                    max={1440}
                    value={reminderLeadMinutes}
                    onChange={(e) => {
                      const n = Number(e.target.value);
                      setReminderLeadMinutes(
                        Number.isNaN(n) ? 5 : Math.min(1440, Math.max(5, n))
                      );
                    }}
                    className={fieldClass}
                  />
                </div>
                <div>
                  <label
                    htmlFor="day-reminder-lead"
                    className="block text-xs font-semibold text-jenny-text mb-1.5"
                  >
                    Rappel la veille (heures avant le RDV)
                  </label>
                  <input
                    id="day-reminder-lead"
                    type="number"
                    min={1}
                    max={168}
                    value={dayReminderLeadHours}
                    onChange={(e) => {
                      const n = Number(e.target.value);
                      setDayReminderLeadHours(
                        Number.isNaN(n) ? 1 : Math.min(168, Math.max(1, n))
                      );
                    }}
                    className={fieldClass}
                  />
                </div>
              </div>

              <div className="mt-3.5">
                <label
                  htmlFor="loyalty-threshold"
                  className="block text-xs font-semibold text-jenny-text mb-1.5"
                >
                  Récompense fidélité après N rendez-vous
                </label>
                <input
                  id="loyalty-threshold"
                  type="number"
                  min={0}
                  max={100}
                  value={loyaltyThreshold}
                  onChange={(e) => {
                    const n = Number(e.target.value);
                    setLoyaltyThreshold(
                      Number.isNaN(n) ? 0 : Math.min(100, Math.max(0, n))
                    );
                  }}
                  className={fieldClass}
                />
                <p className="mt-1.5 text-[11.5px] text-jenny-text-secondary/80">
                  0 = récompense fidélité désactivée.
                </p>
              </div>

              <div className="flex items-center gap-1.5 mt-4 text-[12px] text-jenny-text-secondary">
                <BellRing className="w-3.5 h-3.5 text-jenny-coral shrink-0" />
                Des rappels bien placés réduisent les oublis ; la récompense fidélise vos habitués.
              </div>
            </motion.section>

            {/* ── 06 · Fermetures exceptionnelles ── */}
            <motion.section
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.25 }}
              className="bg-jenny-surface rounded-2xl border border-jenny-divider p-6 mt-[18px]"
            >
              <div className={cn(eyebrowClass, "mb-1.5")}>06 · Fermetures exceptionnelles</div>
              <div className="text-[13px] text-jenny-text-secondary mb-[18px]">
                Congés, jours fériés… Jenny ne proposera aucun créneau sur ces dates.
              </div>

              {/* Liste des fermetures */}
              {closuresLoading ? (
                <div className="space-y-2">
                  <div className="h-[52px] rounded-[10px] animate-shimmer" />
                  <div className="h-[52px] rounded-[10px] animate-shimmer" />
                </div>
              ) : closures.length === 0 ? (
                <p className="text-[13px] text-jenny-text-secondary py-1">
                  Aucune fermeture programmée.
                </p>
              ) : (
                <ul className="space-y-2">
                  {closures.map((c) => (
                    <li
                      key={c.id}
                      className="group flex items-center gap-3 px-3.5 py-2.5 rounded-[10px] bg-jenny-bg border border-jenny-divider"
                    >
                      <CalendarOff className="w-4 h-4 text-jenny-coral shrink-0" />
                      <div className="min-w-0 flex-1">
                        <div className="text-[13px] text-jenny-text">
                          du {formatDate(c.start_date)} au {formatDate(c.end_date)}
                        </div>
                        {c.reason && (
                          <div className="text-[12px] text-jenny-text-secondary truncate">
                            {c.reason}
                          </div>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={() => void removeClosure(c.id)}
                        aria-label={`Supprimer la fermeture du ${formatDate(c.start_date)}`}
                        className="opacity-0 group-hover:opacity-100 text-jenny-text-secondary/50 hover:text-jenny-error transition-all shrink-0"
                      >
                        <Trash className="w-4 h-4" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              {/* Formulaire d'ajout */}
              <div className="mt-4 pt-4 border-t border-jenny-divider/60">
                <div className="grid sm:grid-cols-2 gap-3.5">
                  <div>
                    <label
                      htmlFor="closure-start"
                      className="block text-xs font-semibold text-jenny-text mb-1.5"
                    >
                      Début
                    </label>
                    <input
                      id="closure-start"
                      type="date"
                      value={closureStart}
                      onChange={(e) => setClosureStart(e.target.value)}
                      className={fieldClass}
                    />
                  </div>
                  <div>
                    <label
                      htmlFor="closure-end"
                      className="block text-xs font-semibold text-jenny-text mb-1.5"
                    >
                      Fin (optionnel)
                    </label>
                    <input
                      id="closure-end"
                      type="date"
                      value={closureEnd}
                      min={closureStart || undefined}
                      onChange={(e) => setClosureEnd(e.target.value)}
                      className={fieldClass}
                    />
                  </div>
                </div>
                <div className="mt-3.5 flex flex-col sm:flex-row gap-2.5 sm:items-end">
                  <div className="flex-1">
                    <label
                      htmlFor="closure-reason"
                      className="block text-xs font-semibold text-jenny-text mb-1.5"
                    >
                      Motif (optionnel)
                    </label>
                    <input
                      id="closure-reason"
                      type="text"
                      value={closureReason}
                      onChange={(e) => setClosureReason(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          void addClosure();
                        }
                      }}
                      placeholder="Congés d'été, jour férié…"
                      className={fieldClass}
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => void addClosure()}
                    disabled={!closureStart || closureSubmitting}
                    className="inline-flex items-center justify-center gap-1.5 h-[42px] px-4 rounded-[10px] text-[0.8125rem] font-semibold bg-jenny-coral text-white hover:bg-jenny-coral-dark transition-all shrink-0 disabled:opacity-40 disabled:pointer-events-none"
                  >
                    <Plus className="w-[14px] h-[14px]" />
                    Ajouter
                  </button>
                </div>
              </div>
            </motion.section>

            {/* Enregistrer (l'autosave tourne déjà ; bouton pour sauver tout de suite) */}
            <div className="flex items-center gap-3 mt-6">
              <button
                type="button"
                onClick={() => void persist()}
                disabled={saving}
                className="inline-flex items-center justify-center gap-2 h-11 px-5 rounded-xl text-[0.9375rem] font-semibold bg-jenny-coral text-white hover:bg-jenny-coral-dark shadow-sm shadow-jenny-coral/20 active:scale-[0.98] transition-all disabled:opacity-40 disabled:pointer-events-none"
              >
                {saving ? (
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                ) : (
                  <Check className="w-4 h-4" />
                )}
                Enregistrer
              </button>
              <span className="text-[12px] font-mono text-jenny-text-secondary/70">
                {saving ? "Enregistrement…" : "Sauvegarde automatique active"}
              </span>
            </div>
          </motion.div>

          {/* ════════ Colonne aperçu (sticky) ════════ */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.1 }}
            className="lg:sticky lg:top-5"
          >
            <div className="flex items-center gap-2 mb-3">
              <span className="w-1.5 h-1.5 rounded-full bg-jenny-success" />
              <span className={eyebrowClass}>aperçu en direct</span>
            </div>

            {/* Téléphone sombre */}
            <div
              className="rounded-[24px] px-4 pt-10 pb-4 h-[520px] flex flex-col"
              style={{ background: "#0E0B14" }}
            >
              <div
                className="flex items-center gap-2 px-3 py-2.5 rounded-xl mb-3"
                style={{ background: "rgba(255,255,255,0.04)" }}
              >
                <span className="w-[26px] h-[26px] rounded-full overflow-hidden bg-jenny-coral block shrink-0 relative">
                  <Image
                    src="/jenny.png"
                    alt="Jenny"
                    width={31}
                    height={31}
                    className="object-cover w-[120%] h-[120%] mt-[3px] max-w-none"
                  />
                </span>
                <div className="min-w-0">
                  <div className="text-[11px] font-semibold text-white truncate">
                    Jenny · {name || "Maison Lila"}
                  </div>
                  <div className="text-[9px] font-mono tracking-[0.1em] text-jenny-success">
                    ● TON: {toneLabel}
                  </div>
                </div>
              </div>

              <div className="flex-1 flex flex-col gap-2 overflow-hidden">
                <div className="self-end max-w-[85%] px-[11px] py-2 bg-jenny-coral text-[#1a0a08] text-[11.5px] font-medium rounded-[12px_12px_3px_12px]">
                  Salut ! Vous livrez vite à Lyon ?
                </div>
                <div
                  className="self-start max-w-[88%] px-[11px] py-2 text-[11.5px] rounded-[12px_12px_12px_3px]"
                  style={{
                    background: "rgba(255,255,255,0.06)",
                    color: "rgba(244,241,237,0.95)",
                    border: "1px solid rgba(255,255,255,0.06)",
                  }}
                >
                  Hello 👋 Yes, à Lyon on est à 48-72h via Colissimo. Tu cherches une pièce
                  particulière ?
                </div>
                <div className="self-end max-w-[85%] px-[11px] py-2 bg-jenny-coral text-[#1a0a08] text-[11.5px] font-medium rounded-[12px_12px_3px_12px]">
                  Le sac caramel
                </div>
                <div
                  className="self-start max-w-[88%] px-[11px] py-2 text-[11.5px] rounded-[12px_12px_12px_3px]"
                  style={{
                    background: "rgba(255,255,255,0.06)",
                    color: "rgba(244,241,237,0.95)",
                    border: "1px solid rgba(255,255,255,0.06)",
                  }}
                >
                  Top choix ✨ C&apos;est une pièce unique cousue main à l&apos;atelier. Il en reste
                  3. Tu veux que je te montre ?
                </div>
              </div>

              <div
                className="px-2 py-2 rounded-[10px] text-[10px] font-mono text-center"
                style={{ background: "rgba(255,255,255,0.04)", color: "rgba(244,241,237,0.5)" }}
              >
                ↓ tape pour tester en direct ↓
              </div>
            </div>

            {/* Tests de cohérence */}
            <div className="mt-4 p-4 bg-jenny-surface border border-jenny-divider rounded-[14px]">
              <div className="flex items-center gap-2 text-xs font-semibold text-jenny-text mb-2.5">
                <Sparkles className="w-3.5 h-3.5 text-jenny-coral" />
                Tests de cohérence
              </div>
              {[
                { l: "Cohérence du ton", v: 96 },
                { l: "Respect des règles", v: 100 },
                { l: "Précision factuelle", v: 89 },
              ].map((m) => (
                <div key={m.l} className="mb-2">
                  <div className="flex justify-between mb-1">
                    <span className="text-[11.5px] text-jenny-text-secondary">{m.l}</span>
                    <span
                      className={cn(
                        "text-[11px] font-mono font-bold",
                        m.v >= 95
                          ? "text-jenny-success"
                          : m.v >= 80
                            ? "text-jenny-coral"
                            : "text-jenny-warning"
                      )}
                    >
                      {m.v}%
                    </span>
                  </div>
                  <div className="h-[3px] rounded-sm" style={{ background: "var(--color-jenny-bg-tint)" }}>
                    <div
                      className={cn("h-full rounded-sm", m.v >= 95 ? "bg-jenny-success" : "bg-jenny-coral")}
                      style={{ width: `${m.v}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        </div>
      </div>

      {/* Style du curseur (track corail rempli + thumb blanc cerclé corail) */}
      <style>{`
        .jenny-range {
          -webkit-appearance: none;
          appearance: none;
          height: 6px;
          border-radius: 3px;
          background: linear-gradient(
            to right,
            var(--color-jenny-coral) 0%,
            var(--color-jenny-coral) var(--pct),
            var(--color-jenny-bg-tint) var(--pct),
            var(--color-jenny-bg-tint) 100%
          );
          outline: none;
          cursor: pointer;
        }
        .jenny-range::-webkit-slider-thumb {
          -webkit-appearance: none;
          appearance: none;
          width: 16px;
          height: 16px;
          border-radius: 50%;
          background: #fff;
          border: 2px solid var(--color-jenny-coral);
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
          cursor: pointer;
        }
        .jenny-range::-moz-range-thumb {
          width: 16px;
          height: 16px;
          border-radius: 50%;
          background: #fff;
          border: 2px solid var(--color-jenny-coral);
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
          cursor: pointer;
        }
        .jenny-range::-moz-range-track {
          height: 6px;
          border-radius: 3px;
          background: transparent;
        }
      `}</style>
    </div>
  );
}

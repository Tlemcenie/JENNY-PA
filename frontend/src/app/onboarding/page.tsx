"use client";

import { useCallback, useEffect, useState, type ComponentType } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  AtSign,
  Briefcase,
  Check,
  Heart,
  Loader2,
  Mail,
  MessageCircle,
  Scissors,
  Smile,
  Zap,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import {
  getBusiness,
  humanError,
  listChannels,
  listPrestations,
  seedCoiffeurTemplate,
  updateBusiness,
  type BusinessConfig,
  type ChannelStatus,
  type JennyPersona,
} from "@/lib/api";
import {
  HoursEditor,
  invalidDay,
  weekFromBusiness,
  weekToBusiness,
  type WeekHours,
} from "@/components/onboarding/hours-editor";

// horaires avant le modèle
const STEPS = [
  { n: 1, label: "Votre salon" },
  { n: 2, label: "Vos horaires" },
  { n: 3, label: "Vos prestations" },
  { n: 4, label: "Vos canaux" },
  { n: 5, label: "Le ton de Jenny" },
] as const;

const TOTAL_STEPS = STEPS.length;

const STEP_META: Record<number, { eyebrow: string; title: [string, string]; intro: string }> = {
  1: {
    eyebrow: "— étape 1 —",
    title: ["Parlez-nous de ", "votre salon."],
    intro: "Jenny s'en sert pour répondre juste dès le premier message.",
  },
  2: {
    eyebrow: "— étape 2 —",
    title: ["Vos ", "horaires."],
    intro: "Jenny ne propose un rendez-vous que pendant vos heures d'ouverture.",
  },
  3: {
    eyebrow: "— étape 3 —",
    title: ["Vos ", "prestations."],
    intro: "Avec le catalogue, Jenny donne les bons prix, les bonnes durées et propose des créneaux qui tiennent.",
  },
  4: {
    eyebrow: "— étape 4 —",
    title: ["Où sont ", "vos clients ?"],
    intro: "L'état réel de vos canaux. Vous pourrez les connecter maintenant ou plus tard depuis la page Canaux.",
  },
  5: {
    eyebrow: "— étape 5 —",
    title: ["Quel est le ton de ", "Jenny ?"],
    intro: "Jenny s'y tiendra sur tous vos canaux. Elle se présente toujours comme l'assistante virtuelle du salon.",
  },
};

// mapping canal → icône + couleur
type ChannelBrand = {
  icon: ComponentType<{ className?: string; style?: React.CSSProperties }>;
  color: string;
};

const CHANNEL_BRANDS: Record<string, ChannelBrand> = {
  whatsapp: { icon: MessageCircle, color: "#25D366" },
  instagram: { icon: AtSign, color: "#E4405F" },
  email: { icon: Mail, color: "#3B82F6" },
};

function brandFor(channel: string): ChannelBrand {
  return CHANNEL_BRANDS[channel] ?? { icon: MessageCircle, color: "#7284A8" };
}

type Tone = {
  id: string;
  title: string;
  body: string;
  icon: ComponentType<{ className?: string }>;
};

const TONES: Tone[] = [
  { id: "pro", title: "Professionnel", body: "Clair, posé, irréprochable. Idéal pour un salon haut de gamme.", icon: Briefcase },
  { id: "cool", title: "Cool", body: "Décontracté et direct. Parle comme vos clients.", icon: Smile },
  { id: "vendeur", title: "Vendeur", body: "Met en avant vos prestations et guide vers la prise de rendez-vous.", icon: Zap },
  { id: "chaleureux", title: "Chaleureux", body: "Bienveillant et attentionné. Chaque client se sent écouté.", icon: Heart },
];

const PAGE_BG = "var(--color-jenny-bg)";

// transition entre étapes
const stepVariants = {
  enter: { opacity: 0, y: 14 },
  center: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -10 },
};

const inputCls =
  "w-full h-12 px-4 rounded-xl bg-jenny-surface border border-jenny-divider text-[14.5px] text-jenny-text outline-none focus:border-jenny-coral transition-colors";

export default function OnboardingPage() {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  const [step, setStep] = useState(1);

  // business chargé (base des fusions)
  const [business, setBusiness] = useState<BusinessConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // étape 1
  const [name, setName] = useState("");
  const [sector, setSector] = useState("");
  const [description, setDescription] = useState("");

  // étape 2
  const [week, setWeek] = useState<WeekHours>(() => weekFromBusiness(null));

  // étape 3
  const [prestaCount, setPrestaCount] = useState<number | null>(null);
  const [prestaError, setPrestaError] = useState<string | null>(null);
  const [seeding, setSeeding] = useState(false);
  const [seedInfo, setSeedInfo] = useState<string | null>(null);
  // fiches kb déjà créées
  const [seededKb, setSeededKb] = useState(false);

  // étape 4
  const [channels, setChannels] = useState<ChannelStatus[] | null>(null);
  const [channelsError, setChannelsError] = useState<string | null>(null);

  // étape 5
  const [tone, setTone] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // garde d'authentification
  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isAuthenticated, isLoading, router]);

  const loadBusiness = useCallback(async () => {
    setLoadError(null);
    try {
      const b = await getBusiness();
      setBusiness(b);
      setName(b.name ?? "");
      setDescription(b.description ?? "");
      setSector(b.persona?.sector ?? "");
      if (b.persona?.tone) setTone(b.persona.tone);
      setWeek(weekFromBusiness(b.business_hours));
    } catch (err) {
      setLoadError(humanError(err, "Impossible de récupérer votre salon."));
    }
  }, []);

  const loadPrestations = useCallback(async () => {
    setPrestaError(null);
    try {
      const r = await listPrestations();
      setPrestaCount(r.total ?? r.prestations.length);
    } catch (err) {
      setPrestaError(humanError(err, "Impossible de lire vos prestations."));
    }
  }, []);

  const loadChannels = useCallback(async () => {
    setChannelsError(null);
    try {
      setChannels(await listChannels());
    } catch (err) {
      setChannels(null);
      setChannelsError(humanError(err, "Impossible de lire l'état de vos canaux."));
    }
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;
    // synchro avec l'api
    void loadBusiness();
    void loadPrestations();
    void loadChannels();
  }, [isAuthenticated, loadBusiness, loadPrestations, loadChannels]);

  const goBack = () => {
    setSaveError(null);
    setStep((s) => Math.max(1, s - 1));
  };

  const next = () => {
    setSaveError(null);
    setStep((s) => Math.min(TOTAL_STEPS, s + 1));
  };

  // persona fusionnée, rien d'écrasé
  const mergedPersona = (patch: Partial<JennyPersona>): JennyPersona => ({
    ...(business?.persona ?? {}),
    ...patch,
  });

  async function save(payload: Parameters<typeof updateBusiness>[0]): Promise<boolean> {
    setSaving(true);
    setSaveError(null);
    try {
      setBusiness(await updateBusiness(payload));
      return true;
    } catch (err) {
      setSaveError(humanError(err, "L'enregistrement a échoué. Réessayez."));
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function handleStep1() {
    if (!name.trim()) {
      setSaveError("Indiquez le nom de votre salon.");
      return;
    }
    const ok = await save({
      name: name.trim(),
      description: description.trim() || null,
      persona: mergedPersona({ sector: sector.trim() }),
    });
    if (ok) next();
  }

  async function handleSeed() {
    setSeeding(true);
    setSeedInfo(null);
    try {
      const r = await seedCoiffeurTemplate();
      if (r.knowledge > 0) setSeededKb(true);
      const kbNote =
        r.knowledge > 0
          ? ` ${r.knowledge} fiche${r.knowledge > 1 ? "s" : ""} ajoutée${r.knowledge > 1 ? "s" : ""} à la base (horaires, annulation) : relisez-les.`
          : "";
      setSeedInfo(
        r.prestations > 0
          ? `${r.prestations} prestations ajoutées. Ajustez les prix quand vous voulez.${kbNote}`
          : `Vous aviez déjà des prestations : rien n'a été dupliqué.${kbNote}`
      );
      await loadPrestations();
    } catch (err) {
      setSeedInfo(humanError(err, "Le modèle n'a pas pu être chargé."));
    } finally {
      setSeeding(false);
    }
  }

  async function handleHours() {
    const bad = invalidDay(week);
    if (bad) {
      setSaveError(`${bad} : indiquez une ouverture et une fermeture, la fermeture après l'ouverture.`);
      return;
    }
    const hours = weekToBusiness(week);
    // même ordre des jours
    const before = business?.business_hours
      ? JSON.stringify(weekToBusiness(weekFromBusiness(business.business_hours)))
      : "null";
    const changed = JSON.stringify(hours) !== before;
    const ok = await save({ business_hours: hours });
    if (!ok) return;
    // fiche horaires déjà faite
    if (seededKb && changed) {
      setSeedInfo(
        "Vos horaires ont changé après le chargement du modèle : mettez à jour la fiche « Horaires » dans la base de connaissances."
      );
    }
    next();
  }

  async function handleStep5() {
    if (!tone) return;
    const ok = await save({ persona: mergedPersona({ tone }) });
    if (ok) router.push("/chat");
  }

  // évite le flash avant auth
  if (isLoading || !isAuthenticated) {
    return (
      <div
        className="h-full flex items-center justify-center"
        style={{ background: PAGE_BG, fontFamily: "var(--font-sans)" }}
      >
        <Loader2 className="w-6 h-6 animate-spin text-jenny-coral" />
      </div>
    );
  }

  const meta = STEP_META[step];

  return (
    <div
      className="h-full flex flex-col bg-jenny-bg text-jenny-text"
      style={{ fontFamily: "var(--font-sans)" }}
    >
      {/* header */}
      <header className="flex items-center px-6 md:px-12 py-5 border-b border-jenny-divider">
        <div className="flex items-center gap-2.5">
          <span className="w-[30px] h-[30px] rounded-lg overflow-hidden bg-jenny-coral block">
            <Image src="/jenny.png" alt="" width={30} height={30} className="object-cover w-full h-full" />
          </span>
          <span className="text-[16px] font-bold tracking-[-0.02em]">Jenny</span>
        </div>
        <div className="ml-auto text-[13px] text-jenny-text-secondary">
          Étape <b className="text-jenny-text">{step}</b> sur {TOTAL_STEPS}
        </div>
      </header>

      {/* stepper + contenu */}
      <div className="flex-1 overflow-y-auto">
        <div className="px-4 sm:px-6 md:px-12 py-10 md:py-14 grid grid-cols-1 md:grid-cols-[260px_1fr] gap-10 md:gap-16 max-w-[1100px] mx-auto w-full">
          {/* Stepper */}
          <nav aria-label="Progression de l'onboarding">
            <ol className="flex md:block gap-4 md:gap-0 overflow-x-auto md:overflow-visible">
              {STEPS.map((s) => {
                const done = s.n < step;
                const active = s.n === step;
                return (
                  <li key={s.n} className="flex gap-3.5 md:mb-6 shrink-0" aria-current={active ? "step" : undefined}>
                    <span
                      className="w-8 h-8 rounded-full shrink-0 flex items-center justify-center text-[13px] font-bold transition-colors"
                      style={{
                        background: done
                          ? "var(--color-jenny-coral)"
                          : active
                          ? "var(--color-jenny-surface)"
                          : "var(--color-jenny-divider)",
                        border: active ? "2px solid var(--color-jenny-coral)" : "none",
                        color: done
                          ? "#FFFFFF"
                          : active
                          ? "var(--color-jenny-coral)"
                          : "var(--color-jenny-text-secondary)",
                      }}
                    >
                      {done ? <Check className="w-3.5 h-3.5" /> : s.n}
                    </span>
                    <div className="pt-0.5">
                      <div
                        className="text-[14px] font-semibold mb-1"
                        style={{
                          color:
                            active || done
                              ? "var(--color-jenny-text)"
                              : "var(--color-jenny-text-secondary)",
                        }}
                      >
                        {s.label}
                      </div>
                      {active && <div className="text-[12px] text-jenny-text-secondary">En cours…</div>}
                    </div>
                  </li>
                );
              })}
            </ol>
          </nav>

          {/* Contenu */}
          <div className="max-w-[560px] w-full">
            <AnimatePresence mode="wait">
              <motion.div
                key={step}
                variants={stepVariants}
                initial="enter"
                animate="center"
                exit="exit"
                transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
              >
                <div className="font-mono text-[11px] tracking-[0.28em] uppercase text-jenny-coral mb-3.5">
                  {meta.eyebrow}
                </div>
                <h1 className="font-display text-[36px] md:text-[48px] leading-[1.05] tracking-[-0.02em] mb-3.5">
                  {meta.title[0]}
                  <span className="italic text-jenny-coral">{meta.title[1]}</span>
                </h1>
                <p className="text-[15px] text-jenny-text-secondary mb-9 leading-[1.55]">{meta.intro}</p>

                {/* chargement du salon raté */}
                {loadError && (
                  <ErrorBox message={loadError} onRetry={() => void loadBusiness()} />
                )}

                {/* étape 1 : salon */}
                {step === 1 && (
                  <div className="flex flex-col gap-4">
                    <Field label="Nom du salon">
                      <input
                        type="text"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="Maison Lila"
                        className={inputCls}
                      />
                    </Field>
                    <Field label="Type de salon">
                      <input
                        type="text"
                        value={sector}
                        onChange={(e) => setSector(e.target.value)}
                        placeholder="Coiffure mixte, barbier, coloriste…"
                        className={inputCls}
                      />
                    </Field>
                    <Field label="Décrivez votre salon">
                      <textarea
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                        rows={4}
                        placeholder="Votre clientèle, vos spécialités, ce qui vous différencie…"
                        className="w-full px-4 py-3 rounded-xl bg-jenny-surface border border-jenny-divider text-[14.5px] text-jenny-text outline-none focus:border-jenny-coral transition-colors resize-none leading-[1.55]"
                      />
                    </Field>
                  </div>
                )}

                {/* étape 3 : prestations */}
                {step === 3 && (
                  <div className="flex flex-col gap-3">
                    {prestaError ? (
                      <ErrorBox message={prestaError} onRetry={() => void loadPrestations()} />
                    ) : (
                      <div className="rounded-2xl bg-jenny-surface border border-jenny-divider p-[18px] flex items-center gap-4 flex-wrap">
                        <span className="w-11 h-11 rounded-[11px] bg-jenny-bg flex items-center justify-center shrink-0">
                          <Scissors className="w-6 h-6 text-jenny-coral" />
                        </span>
                        <div className="flex-1 min-w-[180px]">
                          <div className="text-[14.5px] font-semibold text-jenny-text">
                            {prestaCount === null
                              ? "Lecture du catalogue…"
                              : prestaCount > 0
                                ? `${prestaCount} prestation${prestaCount > 1 ? "s" : ""} au catalogue`
                                : "Catalogue vide"}
                          </div>
                          <div className="text-[12.5px] text-jenny-text-secondary mt-0.5">
                            {prestaCount
                              ? "Jenny s'en sert déjà pour les prix et les créneaux."
                              : "Partez du modèle coiffeur (coupes, couleurs, soins) puis ajustez vos prix."}
                          </div>
                        </div>
                        {prestaCount === 0 && (
                          <button
                            type="button"
                            onClick={handleSeed}
                            disabled={seeding}
                            className="h-9 px-3.5 rounded-lg text-[12.5px] font-semibold inline-flex items-center gap-1.5 bg-jenny-coral text-white hover:bg-jenny-coral-dark transition-colors disabled:opacity-60 shrink-0"
                          >
                            {seeding && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                            Charger le modèle coiffeur
                          </button>
                        )}
                      </div>
                    )}
                    {prestaCount === 0 && !business?.business_hours && (
                      <p className="text-[12.5px] text-jenny-text-secondary">
                        Enregistrez d&apos;abord vos horaires (étape précédente) : la fiche « Horaires » du
                        modèle en dépend.
                      </p>
                    )}
                    {seedInfo && (
                      <p role="status" className="text-[13px] text-jenny-text-secondary">
                        {seedInfo}
                      </p>
                    )}
                    <p className="text-[12.5px] text-jenny-text-secondary">
                      Tarifs et durées se modifient à tout moment dans{" "}
                      <Link href="/prestations" className="text-jenny-coral font-semibold hover:underline">
                        Prestations
                      </Link>
                      .
                    </p>
                  </div>
                )}

                {/* étape 2 : horaires */}
                {step === 2 && <HoursEditor value={week} onChange={setWeek} />}

                {/* étape 4 : canaux réels */}
                {step === 4 && (
                  <div className="flex flex-col gap-2.5">
                    {channelsError ? (
                      <ErrorBox message={channelsError} onRetry={() => void loadChannels()} />
                    ) : channels === null ? (
                      Array.from({ length: 3 }).map((_, i) => (
                        <div
                          key={i}
                          className="h-[80px] rounded-2xl bg-jenny-surface border border-jenny-divider animate-pulse"
                        />
                      ))
                    ) : channels.length === 0 ? (
                      <p className="text-[13.5px] text-jenny-text-secondary">Aucun canal disponible pour le moment.</p>
                    ) : (
                      channels.map((c) => {
                        const brand = brandFor(c.channel);
                        const Icon = brand.icon;
                        const status =
                          c.account ?? (c.builtin ? "Intégré, toujours actif" : c.connected ? "Connecté" : "Non connecté");
                        return (
                          <div
                            key={c.channel}
                            className="rounded-2xl bg-jenny-surface border border-jenny-divider p-[18px] flex items-center gap-4"
                          >
                            <span className="w-11 h-11 rounded-[11px] bg-jenny-bg flex items-center justify-center shrink-0">
                              <Icon className="w-6 h-6" style={{ color: brand.color }} />
                            </span>
                            <div className="flex-1 min-w-0">
                              <div className="text-[14.5px] font-semibold text-jenny-text truncate">{c.label}</div>
                              <div className="text-[12.5px] text-jenny-text-secondary mt-0.5 truncate">{status}</div>
                            </div>
                            {c.connected ? (
                              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-jenny-success/15 text-jenny-success text-[11px] font-mono font-semibold tracking-[0.06em] shrink-0">
                                <Check className="w-[11px] h-[11px]" />
                                CONNECTÉ
                              </span>
                            ) : c.configurable ? (
                              <Link
                                href="/channels"
                                className="h-8 px-3.5 rounded-lg text-[12.5px] font-semibold inline-flex items-center bg-jenny-coral text-white hover:bg-jenny-coral-dark transition-colors shrink-0"
                              >
                                Connecter
                              </Link>
                            ) : (
                              <span className="text-[11.5px] font-mono text-jenny-text-secondary shrink-0">
                                Bientôt
                              </span>
                            )}
                          </div>
                        );
                      })
                    )}
                  </div>
                )}

                {/* étape 5 : ton */}
                {step === 5 && (
                  <div className="grid sm:grid-cols-2 gap-3">
                    {TONES.map((t) => {
                      const Icon = t.icon;
                      const selected = tone === t.id;
                      return (
                        <button
                          key={t.id}
                          type="button"
                          onClick={() => setTone(t.id)}
                          aria-pressed={selected}
                          className="text-left rounded-2xl p-5 bg-jenny-surface transition-colors"
                          style={{
                            border: selected
                              ? "2px solid var(--color-jenny-coral)"
                              : "1px solid var(--color-jenny-divider)",
                            boxShadow: selected ? "0 4px 14px rgba(255,127,106,0.18)" : "none",
                          }}
                        >
                          <span
                            className="w-10 h-10 rounded-[11px] flex items-center justify-center mb-3.5"
                            style={{
                              background: selected ? "var(--color-jenny-coral)" : "color-mix(in srgb, var(--color-jenny-coral) 12%, transparent)",
                              color: selected ? "#FFFFFF" : "var(--color-jenny-coral)",
                            }}
                          >
                            <Icon className="w-5 h-5" />
                          </span>
                          <div className="text-[15px] font-semibold text-jenny-text mb-1.5 tracking-[-0.01em]">
                            {t.title}
                          </div>
                          <div className="text-[13px] leading-[1.5] text-jenny-text-secondary">{t.body}</div>
                        </button>
                      );
                    })}
                  </div>
                )}

                {saveError && (
                  <p role="alert" className="mt-5 text-[13px] text-jenny-error flex items-start gap-2">
                    <AlertCircle className="w-4 h-4 shrink-0 mt-px" />
                    {saveError}
                  </p>
                )}

                {/* navigation */}
                <div className="mt-9 flex flex-wrap gap-3 items-center">
                  {step > 1 && (
                    <button
                      type="button"
                      onClick={goBack}
                      disabled={saving}
                      className="h-11 px-4 rounded-xl text-[14px] font-semibold inline-flex items-center gap-1.5 text-jenny-text-secondary hover:text-jenny-text hover:bg-jenny-coral/10 transition-colors disabled:opacity-50"
                    >
                      <ArrowLeft className="w-4 h-4" />
                      Retour
                    </button>
                  )}

                  {step === 1 && (
                    <PrimaryButton
                      onClick={handleStep1}
                      loading={saving}
                      disabled={!business}
                      className="ml-auto"
                    >
                      Continuer
                      <ArrowRight className="w-3.5 h-3.5" />
                    </PrimaryButton>
                  )}

                  {(step === 3 || step === 4) && (
                    <PrimaryButton onClick={next} className="ml-auto">
                      Continuer
                      <ArrowRight className="w-3.5 h-3.5" />
                    </PrimaryButton>
                  )}

                  {step === 2 && (
                    <>
                      <PrimaryButton onClick={handleHours} loading={saving} disabled={!business} className="ml-auto">
                        Enregistrer
                        <ArrowRight className="w-3.5 h-3.5" />
                      </PrimaryButton>
                      <button type="button" onClick={next} className="text-[12.5px] text-jenny-text-secondary">
                        ou <u>plus tard</u>
                      </button>
                    </>
                  )}

                  {step === 5 && (
                    <PrimaryButton
                      onClick={handleStep5}
                      loading={saving}
                      disabled={!tone || !business}
                      className="ml-auto"
                    >
                      Tester Jenny
                      <ArrowRight className="w-3.5 h-3.5" />
                    </PrimaryButton>
                  )}
                </div>
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </div>
    </div>
  );
}

// sous-composants

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[12px] font-semibold text-jenny-text-secondary mb-1.5 font-mono tracking-[0.06em] uppercase">
        {label}
      </span>
      {children}
    </label>
  );
}

function ErrorBox({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="mb-5 rounded-xl border border-jenny-error/25 bg-jenny-error/[0.06] px-4 py-3 flex items-center gap-3 flex-wrap"
    >
      <AlertCircle className="w-4 h-4 text-jenny-error shrink-0" />
      <span className="text-[13px] text-jenny-text flex-1 min-w-[180px]">{message}</span>
      <button
        type="button"
        onClick={onRetry}
        className="text-[12.5px] font-semibold text-jenny-coral hover:underline underline-offset-2"
      >
        Réessayer
      </button>
    </div>
  );
}

function PrimaryButton({
  children,
  onClick,
  loading = false,
  disabled = false,
  className = "",
}: {
  children: React.ReactNode;
  onClick: () => void;
  loading?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={loading || disabled}
      className={`h-11 px-5 rounded-xl text-[14px] font-semibold inline-flex items-center gap-2 bg-jenny-coral text-white hover:bg-jenny-coral-dark transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${className}`}
      style={{ boxShadow: "0 4px 14px rgba(255,127,106,0.25)" }}
    >
      {loading && <Loader2 className="w-4 h-4 animate-spin" />}
      {children}
    </button>
  );
}

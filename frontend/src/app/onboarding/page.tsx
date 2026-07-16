"use client";

import { useEffect, useMemo, useState, type ComponentType } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowLeft,
  ArrowRight,
  AtSign,
  Briefcase,
  Check,
  Heart,
  Loader2,
  Mail,
  MessageCircle,
  Music,
  Smile,
  Zap,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import {
  getBusiness,
  listChannels,
  updateBusiness,
  type ChannelStatus,
} from "@/lib/api";

// onboarding en 3 étapes

const TOTAL_STEPS = 3;

const STEPS = [
  { n: 1, label: "Votre business" },
  { n: 2, label: "Connectez vos canaux" },
  { n: 3, label: "Le ton de Jenny" },
] as const;

// mapping canal → icône + couleur
type ChannelBrand = {
  label: string;
  icon: ComponentType<{ className?: string; style?: React.CSSProperties }>;
  color: string;
};

const CHANNEL_BRANDS: Record<string, ChannelBrand> = {
  whatsapp: { label: "WhatsApp Business", icon: MessageCircle, color: "#25D366" },
  instagram: { label: "Instagram", icon: AtSign, color: "#E4405F" },
  email: { label: "Email Pro", icon: Mail, color: "#3B82F6" },
  tiktok: { label: "TikTok", icon: Music, color: "#1A1D26" },
};

function brandFor(channel: string, fallbackLabel?: string): ChannelBrand {
  return (
    CHANNEL_BRANDS[channel] ?? {
      label: fallbackLabel || channel,
      icon: MessageCircle,
      color: "#7284A8",
    }
  );
}

// repli statique si erreur
const FALLBACK_CHANNELS: ChannelStatus[] = [
  { channel: "whatsapp", label: "WhatsApp Business", connected: true, builtin: false, account: "+33 6 12 34 56 78" },
  { channel: "instagram", label: "Instagram", connected: true, builtin: false, account: "@maisonlila — 12.4k followers" },
  { channel: "email", label: "Email Pro", connected: false, builtin: true, account: "contact@maisonlila.fr" },
  { channel: "tiktok", label: "TikTok", connected: false, builtin: false, account: "Bientôt disponible" },
];

// les 4 tons
type Tone = {
  id: string;
  title: string;
  body: string;
  icon: ComponentType<{ className?: string }>;
};

const TONES: Tone[] = [
  {
    id: "pro",
    title: "Professionnel",
    body: "Clair, posé, irréprochable. Idéal pour le B2B et les marques premium.",
    icon: Briefcase,
  },
  {
    id: "cool",
    title: "Cool",
    body: "Décontracté et direct, avec ce qu'il faut d'émojis. Parle comme vos clients.",
    icon: Smile,
  },
  {
    id: "vendeur",
    title: "Vendeur",
    body: "Orienté conversion : met en avant l'offre et guide vers l'achat sans forcer.",
    icon: Zap,
  },
  {
    id: "chaleureux",
    title: "Chaleureux",
    body: "Bienveillant et attentionné. Chaque client se sent unique et écouté.",
    icon: Heart,
  },
];

const PAGE_BG = "var(--color-jenny-bg)";

// transition entre étapes
const stepVariants = {
  enter: { opacity: 0, y: 14 },
  center: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -10 },
};

export default function OnboardingPage() {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  const [step, setStep] = useState(1);

  // étape 1 : business
  const [name, setName] = useState("");
  const [sector, setSector] = useState("");
  const [description, setDescription] = useState("");

  // étape 2 : canaux
  const [channels, setChannels] = useState<ChannelStatus[]>([]);
  const [channelsLoading, setChannelsLoading] = useState(true);

  // étape 3 : ton
  const [tone, setTone] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);

  // garde d'authentification
  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isAuthenticated, isLoading, router]);

  // préremplissage du business
  useEffect(() => {
    if (!isAuthenticated) return;
    let active = true;
    getBusiness()
      .then((b) => {
        if (!active) return;
        setName(b.name ?? "");
        setDescription(b.description ?? "");
        if (b.persona?.tone) setTone(b.persona.tone);
      })
      .catch(() => {
        // pas encore de business
      });
    return () => {
      active = false;
    };
  }, [isAuthenticated]);

  // chargement des canaux
  useEffect(() => {
    if (!isAuthenticated) return;
    let active = true;
    setChannelsLoading(true);
    listChannels()
      .then((list) => {
        if (!active) return;
        setChannels(list.length > 0 ? list : FALLBACK_CHANNELS);
      })
      .catch(() => {
        if (active) setChannels(FALLBACK_CHANNELS);
      })
      .finally(() => {
        if (active) setChannelsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [isAuthenticated]);

  const goBack = () => setStep((s) => Math.max(1, s - 1));

  // sauvegarde étape 1
  async function handleStep1() {
    setSaving(true);
    try {
      await updateBusiness({
        name: name.trim(),
        description: description.trim() || null,
      });
    } catch {
      // best-effort
    } finally {
      setSaving(false);
      setStep(2);
    }
  }

  // sauvegarde étape 3
  async function handleStep3() {
    if (!tone) return;
    setSaving(true);
    try {
      await updateBusiness({ persona: { tone } });
    } catch {
      // best-effort
    } finally {
      setSaving(false);
      router.push("/chat");
    }
  }

  const stepMeta = useMemo(
    () => ({
      1: {
        eyebrow: "— étape 1 —",
        title: ["Parlez-nous de ", "votre business."],
        intro:
          "Jenny apprend votre activité pour répondre juste, dès le premier message. Ces informations façonnent chacune de ses réponses.",
      },
      2: {
        eyebrow: "— étape 2 —",
        title: ["Où sont ", "vos clients ?"],
        intro:
          "Connectez les canaux où vous recevez des messages. Jenny s'y branche en lecture-seule jusqu'à ce que vous l'autorisiez à répondre.",
      },
      3: {
        eyebrow: "— étape 3 —",
        title: ["Quel est le ton de ", "Jenny ?"],
        intro:
          "Choisissez la personnalité de Jenny. Elle s'y tiendra sur tous vos canaux, dans chaque conversation.",
      },
    }),
    []
  );

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

  const meta = stepMeta[step as 1 | 2 | 3];

  return (
    <div
      className="h-full flex flex-col bg-jenny-bg text-jenny-text"
      style={{ fontFamily: "var(--font-sans)" }}
    >
      {/* header */}
      <header className="flex items-center px-6 md:px-12 py-5 border-b border-jenny-divider">
        <div className="flex items-center gap-2.5">
          <span className="w-[30px] h-[30px] rounded-lg overflow-hidden bg-jenny-coral block">
            <Image src="/jenny.png" alt="Jenny" width={30} height={30} className="object-cover w-full h-full" />
          </span>
          <span className="text-[16px] font-bold tracking-[-0.02em]">Jenny</span>
        </div>
        <div className="ml-auto text-[13px] text-jenny-text-secondary">
          Étape <b className="text-jenny-text">{step}</b> sur {TOTAL_STEPS}
        </div>
      </header>

      {/* stepper + contenu */}
      <div className="flex-1 overflow-y-auto">
        <div className="px-6 md:px-12 py-10 md:py-14 grid grid-cols-1 md:grid-cols-[280px_1fr] gap-10 md:gap-16 max-w-[1100px] mx-auto w-full">
          {/* Stepper */}
          <nav aria-label="Progression de l'onboarding">
            <ol className="flex md:block gap-4 md:gap-0 overflow-x-auto md:overflow-visible">
              {STEPS.map((s) => {
                const done = s.n < step;
                const active = s.n === step;
                return (
                  <li key={s.n} className="flex gap-3.5 md:mb-6 shrink-0">
                    <span
                      className="w-8 h-8 rounded-full shrink-0 flex items-center justify-center text-[13px] font-bold transition-colors"
                      style={{
                        background: done
                          ? "var(--color-jenny-coral)"
                          : active
                          ? "var(--color-jenny-surface)"
                          : "#F0F0EE",
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
                      {done && (
                        <div className="text-[12px] text-jenny-success font-mono tracking-[0.06em]">TERMINÉ</div>
                      )}
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
                <h1 className="font-display text-[40px] md:text-[48px] leading-[1.05] tracking-[-0.02em] mb-3.5">
                  {meta.title[0]}
                  <span className="italic text-jenny-coral">{meta.title[1]}</span>
                </h1>
                <p className="text-[15px] text-jenny-text-secondary mb-9 leading-[1.55]">{meta.intro}</p>

                {/* étape 1 : business */}
                {step === 1 && (
                  <div className="flex flex-col gap-4">
                    <Field label="Nom du business">
                      <input
                        type="text"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="Maison Lila"
                        className="w-full h-12 px-4 rounded-xl bg-jenny-surface border border-jenny-divider text-[14.5px] text-jenny-text outline-none focus:border-jenny-coral transition-colors"
                      />
                    </Field>
                    <Field label="Secteur d'activité">
                      <input
                        type="text"
                        value={sector}
                        onChange={(e) => setSector(e.target.value)}
                        placeholder="Mode & accessoires, e-commerce…"
                        className="w-full h-12 px-4 rounded-xl bg-jenny-surface border border-jenny-divider text-[14.5px] text-jenny-text outline-none focus:border-jenny-coral transition-colors"
                      />
                    </Field>
                    <Field label="Décrivez votre activité">
                      <textarea
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                        rows={4}
                        placeholder="Ce que vous vendez, votre clientèle, ce qui vous différencie…"
                        className="w-full px-4 py-3 rounded-xl bg-jenny-surface border border-jenny-divider text-[14.5px] text-jenny-text outline-none focus:border-jenny-coral transition-colors resize-none leading-[1.55]"
                      />
                    </Field>
                  </div>
                )}

                {/* étape 2 : canaux */}
                {step === 2 && (
                  <div className="flex flex-col gap-2.5">
                    {channelsLoading ? (
                      Array.from({ length: 4 }).map((_, i) => (
                        <div
                          key={i}
                          className="h-[80px] rounded-2xl bg-jenny-surface border border-jenny-divider animate-pulse"
                        />
                      ))
                    ) : (
                      channels.map((c) => {
                        const brand = brandFor(c.channel, c.label);
                        const Icon = brand.icon;
                        const meta =
                          c.account ?? (c.builtin ? "Intégré nativement" : c.connected ? "Connecté" : "Non connecté");
                        return (
                          <div
                            key={c.channel}
                            className="rounded-2xl bg-jenny-surface border border-jenny-divider p-[18px] flex items-center gap-4"
                          >
                            <span className="w-11 h-11 rounded-[11px] bg-jenny-bg flex items-center justify-center shrink-0">
                              <Icon className="w-6 h-6" style={{ color: brand.color }} />
                            </span>
                            <div className="flex-1 min-w-0">
                              <div className="text-[14.5px] font-semibold text-jenny-text truncate">{brand.label}</div>
                              <div className="text-[12.5px] text-jenny-text-secondary mt-0.5 truncate">{meta}</div>
                            </div>
                            {c.connected ? (
                              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-jenny-mint text-jenny-success text-[11px] font-mono font-semibold tracking-[0.06em] shrink-0">
                                <Check className="w-[11px] h-[11px]" />
                                CONNECTÉ
                              </span>
                            ) : (
                              <button
                                type="button"
                                className="h-8 px-3.5 rounded-lg text-[12.5px] font-semibold inline-flex items-center bg-jenny-coral text-white hover:bg-jenny-coral-dark transition-colors shrink-0"
                              >
                                Connecter
                              </button>
                            )}
                          </div>
                        );
                      })
                    )}
                  </div>
                )}

                {/* étape 3 : ton */}
                {step === 3 && (
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
                              background: selected ? "var(--color-jenny-coral)" : "var(--color-jenny-coral-tint)",
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

                {/* navigation */}
                <div className="mt-9 flex flex-wrap gap-3 items-center">
                  {step > 1 && (
                    <button
                      type="button"
                      onClick={goBack}
                      disabled={saving}
                      className="h-11 px-4 rounded-xl text-[14px] font-semibold inline-flex items-center gap-1.5 text-jenny-text-secondary hover:text-jenny-text hover:bg-jenny-coral-tint transition-colors disabled:opacity-50"
                    >
                      <ArrowLeft className="w-4 h-4" />
                      Retour
                    </button>
                  )}

                  {step === 1 && (
                    <PrimaryButton onClick={handleStep1} loading={saving} className="ml-auto">
                      Continuer
                      <ArrowRight className="w-3.5 h-3.5" />
                    </PrimaryButton>
                  )}

                  {step === 2 && (
                    <>
                      <PrimaryButton onClick={() => setStep(3)} className="ml-auto">
                        Continuer
                        <ArrowRight className="w-3.5 h-3.5" />
                      </PrimaryButton>
                      <button
                        type="button"
                        onClick={() => setStep(3)}
                        className="text-[12.5px] text-jenny-text-secondary"
                      >
                        ou <u>sauter cette étape</u>
                      </button>
                    </>
                  )}

                  {step === 3 && (
                    <PrimaryButton onClick={handleStep3} loading={saving} disabled={!tone} className="ml-auto">
                      Activer Jenny
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

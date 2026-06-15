"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { motion } from "framer-motion";
import { ArrowLeft, Check } from "lucide-react";
import { forgotPassword, resetPassword, ApiError } from "@/lib/api";
import { staggerContainer, staggerItem } from "@/lib/motion";

// Page « Mot de passe oublié » — DA « Jenny Front » : calque exact de l'écran
// login (split-screen, formulaire sur fond clair à gauche, panneau nuit profonde
// + citation éditoriale et mascotte flottante à droite). Le parcours se déroule
// en deux étapes dans ce seul fichier : « demande » (saisie de l'email) puis
// « réinitialisation » (code + nouveau mot de passe), suivi d'un bref écran de
// confirmation avant la redirection vers /login.

const NIGHT_BG =
  "radial-gradient(ellipse at 30% 20%, rgba(255,127,106,0.18) 0%, transparent 55%), #0E0B14";

// Classes partagées par les champs — strictement identiques à l'écran login.
const FIELD_CLASS =
  "w-full h-12 px-4 rounded-[11px] bg-white border border-jenny-divider text-[14.5px] text-jenny-text placeholder:text-jenny-text-secondary/50 outline-none transition-all duration-150 hover:border-jenny-text-secondary/30 focus:border-jenny-coral focus:ring-2 focus:ring-jenny-coral/20";

const LABEL_CLASS =
  "block font-mono text-[12px] font-semibold tracking-[0.06em] uppercase text-jenny-text-secondary mb-1.5";

type Step = "request" | "reset" | "done";

export default function ForgotPasswordPage() {
  const router = useRouter();

  const [step, setStep] = useState<Step>("request");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  // ── Étape 1 : demande d'un code de réinitialisation ──
  async function handleRequest(e: FormEvent) {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    try {
      const res = await forgotPassword(email);
      // En dev/test l'API peut renvoyer un code de debug : on le pré-remplit
      // discrètement pour faciliter les tests, sans jamais l'afficher en clair.
      if (res.debug_code) setCode(res.debug_code);
      setStep("reset");
    } catch (err) {
      if (err instanceof ApiError) {
        const detail = (err.data as { detail?: string })?.detail;
        setError(detail || "Impossible d'envoyer le code. Réessayez dans un instant.");
      } else {
        setError(
          "Impossible de se connecter au serveur. Vérifiez que le backend est lancé sur localhost:8000."
        );
      }
    } finally {
      setIsLoading(false);
    }
  }

  // ── Étape 2 : réinitialisation effective du mot de passe ──
  async function handleReset(e: FormEvent) {
    e.preventDefault();
    setError("");

    // Validations côté client avant l'appel réseau.
    if (!code.trim()) {
      setError("Saisissez le code reçu par email.");
      return;
    }
    if (password.length < 8) {
      setError("Le mot de passe doit contenir au moins 8 caractères.");
      return;
    }
    if (password !== confirm) {
      setError("Les deux mots de passe ne correspondent pas.");
      return;
    }

    setIsLoading(true);
    try {
      await resetPassword(email, code.trim(), password);
      setStep("done");
      // Bref écran de confirmation, puis retour à la connexion.
      setTimeout(() => router.push("/login"), 1800);
    } catch (err) {
      if (err instanceof ApiError) {
        const detail = (err.data as { detail?: string })?.detail;
        if (err.status === 400 || err.status === 404 || err.status === 422) {
          setError(detail || "Code invalide ou expiré, redemandez-en un.");
        } else {
          setError(detail || "La réinitialisation a échoué. Réessayez.");
        }
      } else {
        setError(
          "Impossible de se connecter au serveur. Vérifiez que le backend est lancé sur localhost:8000."
        );
      }
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="min-h-full grid grid-cols-1 lg:grid-cols-2 bg-jenny-bg">
      {/* ── Form side ── */}
      <div className="flex flex-col px-6 py-10 sm:px-12 lg:px-16 lg:py-14">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2.5">
          <span className="w-[34px] h-[34px] rounded-[9px] overflow-hidden bg-jenny-coral block">
            <Image
              src="/jenny.png"
              alt="Jenny"
              width={34}
              height={34}
              className="object-cover w-full h-full"
            />
          </span>
          <span className="text-[18px] font-bold tracking-[-0.02em] text-jenny-text">Jenny</span>
        </Link>

        <motion.div
          key={step}
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="my-auto w-full max-w-[380px] py-12"
        >
          {step === "request" && (
            <>
              <motion.div
                variants={staggerItem}
                className="font-mono text-[11px] tracking-[0.28em] uppercase text-jenny-text-secondary mb-3.5"
              >
                — accès oublié —
              </motion.div>

              <motion.h1
                variants={staggerItem}
                className="font-display font-normal text-[44px] sm:text-[56px] leading-none tracking-[-0.02em] text-jenny-text mb-4"
              >
                On vous <span className="italic text-jenny-coral">rouvre.</span>
              </motion.h1>

              <motion.p
                variants={staggerItem}
                className="text-[14.5px] leading-[1.55] text-jenny-text-secondary mb-9"
              >
                Indiquez l&apos;email de votre espace. Si un compte existe, Jenny vous envoie un{" "}
                <b className="text-jenny-text font-semibold">code de réinitialisation</b> dans la
                foulée.
              </motion.p>

              <motion.form
                variants={staggerContainer}
                onSubmit={handleRequest}
                className="flex flex-col gap-3.5"
              >
                <motion.div variants={staggerItem}>
                  <label htmlFor="email" className={LABEL_CLASS}>
                    Email
                  </label>
                  <input
                    id="email"
                    type="email"
                    placeholder="vous@exemple.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoComplete="email"
                    className={FIELD_CLASS}
                  />
                </motion.div>

                {error && (
                  <motion.div
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="p-3.5 rounded-[11px] bg-jenny-error/[0.08] border border-jenny-error/15 text-jenny-error text-sm leading-relaxed"
                  >
                    {error}
                  </motion.div>
                )}

                <motion.div variants={staggerItem}>
                  <button
                    type="submit"
                    disabled={isLoading}
                    className="w-full h-12 mt-2 rounded-[11px] bg-jenny-coral text-white text-[14.5px] font-semibold inline-flex items-center justify-center gap-2 transition-all duration-150 hover:bg-jenny-coral-dark active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none"
                    style={{ boxShadow: "0 4px 14px rgba(255,127,106,0.25)" }}
                  >
                    {isLoading && <Spinner />}
                    {isLoading ? "Envoi…" : "Envoyer le code →"}
                  </button>
                </motion.div>
              </motion.form>
            </>
          )}

          {step === "reset" && (
            <>
              <motion.div
                variants={staggerItem}
                className="font-mono text-[11px] tracking-[0.28em] uppercase text-jenny-text-secondary mb-3.5"
              >
                — nouveau mot de passe —
              </motion.div>

              <motion.h1
                variants={staggerItem}
                className="font-display font-normal text-[44px] sm:text-[56px] leading-none tracking-[-0.02em] text-jenny-text mb-4"
              >
                Presque <span className="italic text-jenny-coral">prêt.</span>
              </motion.h1>

              <motion.p
                variants={staggerItem}
                className="text-[14.5px] leading-[1.55] text-jenny-text-secondary mb-9"
              >
                Saisissez le code envoyé à{" "}
                <b className="text-jenny-text font-semibold">{email}</b> et choisissez votre nouveau
                mot de passe.
              </motion.p>

              <motion.form
                variants={staggerContainer}
                onSubmit={handleReset}
                className="flex flex-col gap-3.5"
              >
                <motion.div variants={staggerItem}>
                  <label htmlFor="code" className={LABEL_CLASS}>
                    Code de réinitialisation
                  </label>
                  <input
                    id="code"
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    pattern="[0-9]*"
                    maxLength={6}
                    placeholder="123456"
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    required
                    className={`${FIELD_CLASS} tracking-[0.4em] font-mono`}
                  />
                </motion.div>

                <motion.div variants={staggerItem}>
                  <label htmlFor="new-password" className={LABEL_CLASS}>
                    Nouveau mot de passe
                  </label>
                  <input
                    id="new-password"
                    type="password"
                    placeholder="Min. 8 caractères"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={8}
                    autoComplete="new-password"
                    className={FIELD_CLASS}
                  />
                </motion.div>

                <motion.div variants={staggerItem}>
                  <label htmlFor="confirm-password" className={LABEL_CLASS}>
                    Confirmer le mot de passe
                  </label>
                  <input
                    id="confirm-password"
                    type="password"
                    placeholder="Retapez le mot de passe"
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    required
                    minLength={8}
                    autoComplete="new-password"
                    className={FIELD_CLASS}
                  />
                </motion.div>

                {error && (
                  <motion.div
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="p-3.5 rounded-[11px] bg-jenny-error/[0.08] border border-jenny-error/15 text-jenny-error text-sm leading-relaxed"
                  >
                    {error}
                  </motion.div>
                )}

                <motion.div variants={staggerItem}>
                  <button
                    type="submit"
                    disabled={isLoading}
                    className="w-full h-12 mt-2 rounded-[11px] bg-jenny-coral text-white text-[14.5px] font-semibold inline-flex items-center justify-center gap-2 transition-all duration-150 hover:bg-jenny-coral-dark active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none"
                    style={{ boxShadow: "0 4px 14px rgba(255,127,106,0.25)" }}
                  >
                    {isLoading && <Spinner />}
                    {isLoading ? "Réinitialisation…" : "Réinitialiser →"}
                  </button>
                </motion.div>

                <motion.button
                  variants={staggerItem}
                  type="button"
                  onClick={() => {
                    setStep("request");
                    setError("");
                  }}
                  className="self-center mt-1 text-xs text-jenny-text-secondary hover:text-jenny-coral transition-colors"
                >
                  Pas reçu le code ? En redemander un
                </motion.button>
              </motion.form>
            </>
          )}

          {step === "done" && (
            <div className="text-center">
              <motion.div
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
                className="w-14 h-14 mx-auto mb-6 rounded-2xl bg-jenny-success/12 border border-jenny-success/20 flex items-center justify-center"
              >
                <Check className="w-7 h-7 text-jenny-success" />
              </motion.div>

              <motion.h1
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.05, ease: [0.16, 1, 0.3, 1] }}
                className="font-display font-normal text-[40px] sm:text-[48px] leading-none tracking-[-0.02em] text-jenny-text mb-4"
              >
                Mot de passe <span className="italic text-jenny-coral">mis à jour.</span>
              </motion.h1>

              <motion.p
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}
                className="text-[14.5px] leading-[1.55] text-jenny-text-secondary"
              >
                On vous redirige vers la connexion…
              </motion.p>
            </div>
          )}

          {step !== "done" && (
            <motion.div variants={staggerItem} className="mt-8">
              <Link
                href="/login"
                className="inline-flex items-center gap-1.5 text-[13.5px] text-jenny-text-secondary hover:text-jenny-coral transition-colors"
              >
                <ArrowLeft className="w-4 h-4" />
                Retour à la connexion
              </Link>
            </motion.div>
          )}
        </motion.div>

        <p className="font-mono text-[11px] tracking-[0.08em] text-jenny-text-secondary/60">
          © 2026 Jenny — Hébergé en France · RGPD
        </p>
      </div>

      {/* ── Visual side (panneau nuit) ── */}
      <div className="relative hidden lg:block overflow-hidden" style={{ background: NIGHT_BG }}>
        <div className="absolute inset-0 p-16 flex flex-col">
          {/* Citation */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.15, ease: [0.16, 1, 0.3, 1] }}
            className="my-auto max-w-[480px]"
          >
            <p className="font-display italic text-[48px] leading-[1.1] tracking-[-0.015em] text-[#F4F1ED]/95 mb-8">
              « Un mot de passe perdu, ce n&apos;est jamais un drame. On vous remet en selle en
              trente secondes. »
            </p>
            <div className="flex items-center gap-3.5">
              <div className="w-11 h-11 rounded-full bg-jenny-coral flex items-center justify-center text-white font-bold">
                J
              </div>
              <div>
                <div className="text-[14.5px] font-semibold text-white">Jenny</div>
                <div className="text-[12.5px] text-[#F4F1ED]/50">Votre assistante</div>
              </div>
            </div>
          </motion.div>

          {/* Mascotte flottante */}
          <div className="absolute -right-10 -bottom-16 w-[340px] h-[340px]">
            <div
              className="absolute"
              style={{
                inset: "-15%",
                background: "radial-gradient(circle, rgba(255,127,106,0.4) 0%, transparent 60%)",
                filter: "blur(16px)",
              }}
            />
            <Image
              src="/jenny.png"
              alt="Jenny, votre assistante"
              width={340}
              height={340}
              priority
              className="relative w-full h-full object-contain"
              style={{ filter: "drop-shadow(0 30px 60px rgba(255,127,106,0.4))" }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

// Spinner repris à l'identique du bouton de l'écran login.
function Spinner() {
  return (
    <svg className="animate-spin h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}

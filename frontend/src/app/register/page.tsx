"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/api";
import { JennyAvatar } from "@/components/ui/jenny-avatar";
import { BrandedLoader } from "@/components/ui/branded-loader";
import { PressableButton } from "@/components/ui/pressable-button";
import { staggerContainer, staggerItem } from "@/lib/motion";

// Page d'inscription — MÊME direction artistique que /login (split-screen :
// formulaire éditorial à gauche, panneau nuit + mascotte flottante à droite).
// La logique d'inscription (création de compte → vérification email) est conservée.

const NIGHT_BG =
  "radial-gradient(ellipse at 30% 20%, rgba(255,127,106,0.18) 0%, transparent 55%), #0E0B14";

export default function RegisterPage() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const { register } = useAuth();
  const router = useRouter();
  const reduce = useReducedMotion();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setIsLoading(true);
    try {
      await register(fullName, email, password);
      // Compte créé : on redirige vers la saisie du code de confirmation.
      router.push(`/verify?email=${encodeURIComponent(email)}`);
    } catch (err) {
      if (err instanceof ApiError) {
        const detail = (err.data as { detail?: string })?.detail;
        setError(detail || "Impossible de créer le compte.");
      } else {
        setError(
          "Impossible de se connecter au serveur. Vérifiez que le backend est lancé sur localhost:8000."
        );
      }
    } finally {
      setIsLoading(false);
    }
  }

  const fieldClass =
    "w-full h-12 px-4 rounded-[11px] bg-jenny-surface border border-jenny-divider text-[14.5px] text-jenny-text placeholder:text-jenny-text-secondary/50 outline-none transition-all duration-150 hover:border-jenny-text-secondary/30 focus:border-jenny-coral focus:ring-2 focus:ring-jenny-coral/20";
  const labelClass =
    "block font-mono text-[12px] font-semibold tracking-[0.06em] uppercase text-jenny-text-secondary mb-1.5";

  return (
    <div className="min-h-full grid grid-cols-1 lg:grid-cols-2 bg-jenny-bg">
      {/* ── Form side ── */}
      <div className="flex flex-col px-6 py-10 sm:px-12 lg:px-16 lg:py-14">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2.5">
          <JennyAvatar size={34} tone="light" />
          <span className="text-[18px] font-bold tracking-[-0.02em] text-jenny-text">Jenny</span>
        </Link>

        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="my-auto w-full max-w-[380px] py-12"
        >
          <motion.div
            variants={staggerItem}
            className="font-mono text-[11px] tracking-[0.28em] uppercase text-jenny-text-secondary mb-3.5"
          >
            — créons votre espace —
          </motion.div>

          <motion.h1
            variants={staggerItem}
            className="font-display font-normal text-[44px] sm:text-[56px] leading-none tracking-[-0.02em] text-jenny-text mb-4"
          >
            Jenny, rien qu&apos;à <span className="italic text-jenny-coral">vous.</span>
          </motion.h1>

          <motion.p
            variants={staggerItem}
            className="text-[14.5px] leading-[1.55] text-jenny-text-secondary mb-9"
          >
            Créez votre espace en quelques secondes. Jenny répondra à vos clients dans votre ton,
            sur tous vos canaux — 24/7.
          </motion.p>

          <motion.form variants={staggerContainer} onSubmit={handleSubmit} className="relative flex flex-col gap-3.5">
            {/* Nom */}
            <motion.div variants={staggerItem}>
              <label htmlFor="fullName" className={labelClass}>
                Nom complet
              </label>
              <input
                id="fullName"
                type="text"
                placeholder="Votre nom"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                required
                autoComplete="name"
                className={fieldClass}
              />
            </motion.div>

            {/* Email */}
            <motion.div variants={staggerItem}>
              <label htmlFor="email" className={labelClass}>
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
                className={fieldClass}
              />
            </motion.div>

            {/* Mot de passe */}
            <motion.div variants={staggerItem}>
              <label htmlFor="password" className={labelClass}>
                Mot de passe
              </label>
              <input
                id="password"
                type="password"
                placeholder="8 car. min., 1 majuscule, 1 chiffre, 1 spécial"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="new-password"
                minLength={8}
                className={fieldClass}
              />
            </motion.div>

            {error && (
              <motion.div
                key={error}
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                role="alert"
                aria-live="assertive"
                className={`p-3.5 rounded-[11px] bg-jenny-error/[0.08] border border-jenny-error/15 text-jenny-error text-sm leading-relaxed ${reduce ? "" : "animate-shake"}`}
              >
                {error}
              </motion.div>
            )}

            {/* Créer */}
            <motion.div variants={staggerItem}>
              <PressableButton
                type="submit"
                isLoading={isLoading}
                className="btn-fluffy w-full h-12 mt-2 bg-jenny-coral text-white text-[14.5px] font-semibold hover:bg-jenny-coral-dark"
              >
                {isLoading ? "Création…" : "Créer mon espace →"}
              </PressableButton>
            </motion.div>

            {/* Overlay de soumission : voile flouté + loader brandé au-dessus du formulaire */}
            <AnimatePresence>
              {isLoading && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.18 }}
                  aria-hidden
                  className="absolute -inset-3 z-10 flex items-center justify-center rounded-2xl bg-jenny-bg/55 backdrop-blur-sm"
                >
                  <div className="h-[180px] w-[180px] overflow-hidden rounded-2xl border border-jenny-divider/60 bg-jenny-surface/90 shadow-xl shadow-jenny-coral/10">
                    <BrandedLoader label="Création…" />
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.form>

          <motion.p variants={staggerItem} className="mt-8 text-[13.5px] text-jenny-text-secondary">
            Déjà un compte ?{" "}
            <Link
              href="/login"
              className="text-jenny-coral font-semibold hover:underline underline-offset-2"
            >
              Se connecter
            </Link>
          </motion.p>
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
              « Activation en 4 minutes. Le soir même, Jenny répondait déjà à mes clientes. »
            </p>
            <div className="flex items-center gap-3.5">
              <div className="w-11 h-11 rounded-full bg-jenny-coral flex items-center justify-center text-white font-bold">
                SM
              </div>
              <div>
                <div className="text-[14.5px] font-semibold text-white">Sarah Moreau</div>
                <div className="text-[12.5px] text-[#F4F1ED]/50">Gérante, Studio Néroli</div>
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

"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { motion } from "framer-motion";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/api";
import { staggerContainer, staggerItem } from "@/lib/motion";

// Page de connexion — DA « Jenny Front » : split-screen, formulaire sur fond
// clair à gauche, panneau nuit profonde + citation éditoriale et mascotte
// flottante à droite. Recrée l'écran ScreenLogin du handoff. La logique d'auth
// (état, handler de soumission, redirections) est strictement préservée.

const NIGHT_BG =
  "radial-gradient(ellipse at 30% 20%, rgba(255,127,106,0.18) 0%, transparent 55%), #0E0B14";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const { login } = useAuth();
  const router = useRouter();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    try {
      const u = await login(email, password);
      // Les super-admins atterrissent sur la console d'administration.
      router.push(u?.is_superuser ? "/admin" : "/chat");
    } catch (err) {
      if (err instanceof ApiError) {
        const detail = (err.data as { detail?: string })?.detail;
        // Compte non confirmé : on redirige vers la saisie du code.
        if (err.status === 403 && detail === "email_not_verified") {
          router.push(`/verify?email=${encodeURIComponent(email)}`);
          return;
        }
        setError(detail || "Email ou mot de passe incorrect.");
      } else {
        setError("Impossible de se connecter au serveur. Vérifiez que le backend est lancé sur localhost:8000.");
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
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="my-auto w-full max-w-[380px] py-12"
        >
          <motion.div
            variants={staggerItem}
            className="font-mono text-[11px] tracking-[0.28em] uppercase text-jenny-text-secondary mb-3.5"
          >
            — bon retour —
          </motion.div>

          <motion.h1
            variants={staggerItem}
            className="font-display font-normal text-[44px] sm:text-[56px] leading-none tracking-[-0.02em] text-jenny-text mb-4"
          >
            Jenny vous <span className="italic text-jenny-coral">attendait.</span>
          </motion.h1>

          <motion.p
            variants={staggerItem}
            className="text-[14.5px] leading-[1.55] text-jenny-text-secondary mb-9"
          >
            Pendant votre absence, elle a traité{" "}
            <b className="text-jenny-text font-semibold">47 conversations</b> et signalé 3 messages
            qui demandent votre attention.
          </motion.p>

          <motion.form
            variants={staggerContainer}
            onSubmit={handleSubmit}
            className="flex flex-col gap-3.5"
          >
            {/* Email */}
            <motion.div variants={staggerItem}>
              <label
                htmlFor="email"
                className="block font-mono text-[12px] font-semibold tracking-[0.06em] uppercase text-jenny-text-secondary mb-1.5"
              >
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
                className="w-full h-12 px-4 rounded-[11px] bg-white border border-jenny-divider text-[14.5px] text-jenny-text placeholder:text-jenny-text-secondary/50 outline-none transition-all duration-150 hover:border-jenny-text-secondary/30 focus:border-jenny-coral focus:ring-2 focus:ring-jenny-coral/20"
              />
            </motion.div>

            {/* Mot de passe */}
            <motion.div variants={staggerItem}>
              <div className="flex items-baseline justify-between mb-1.5">
                <label
                  htmlFor="password"
                  className="block font-mono text-[12px] font-semibold tracking-[0.06em] uppercase text-jenny-text-secondary"
                >
                  Mot de passe
                </label>
                <Link
                  href="/forgot-password"
                  className="text-xs text-jenny-text-secondary hover:text-jenny-coral transition-colors"
                >
                  Mot de passe oublié ?
                </Link>
              </div>
              <input
                id="password"
                type="password"
                placeholder="Votre mot de passe"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
                className="w-full h-12 px-4 rounded-[11px] bg-white border border-jenny-divider text-[14.5px] text-jenny-text placeholder:text-jenny-text-secondary/50 outline-none transition-all duration-150 hover:border-jenny-text-secondary/30 focus:border-jenny-coral focus:ring-2 focus:ring-jenny-coral/20"
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

            {/* Continuer */}
            <motion.div variants={staggerItem}>
              <button
                type="submit"
                disabled={isLoading}
                className="w-full h-12 mt-2 rounded-[11px] bg-jenny-coral text-white text-[14.5px] font-semibold inline-flex items-center justify-center gap-2 transition-all duration-150 hover:bg-jenny-coral-dark active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none"
                style={{ boxShadow: "0 4px 14px rgba(255,127,106,0.25)" }}
              >
                {isLoading && (
                  <svg className="animate-spin h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none">
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="3"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                    />
                  </svg>
                )}
                {isLoading ? "Connexion…" : "Continuer →"}
              </button>
            </motion.div>
          </motion.form>

          <motion.p variants={staggerItem} className="mt-8 text-[13.5px] text-jenny-text-secondary">
            Pas encore de compte ?{" "}
            <Link
              href="/register"
              className="text-jenny-coral font-semibold hover:underline underline-offset-2"
            >
              Créer mon espace
            </Link>
          </motion.p>
        </motion.div>

        <p className="font-mono text-[11px] tracking-[0.08em] text-jenny-text-secondary/60">
          © 2026 Jenny — Hébergé en France · RGPD
        </p>
      </div>

      {/* ── Visual side (panneau nuit) ── */}
      <div
        className="relative hidden lg:block overflow-hidden"
        style={{ background: NIGHT_BG }}
      >
        <div className="absolute inset-0 p-16 flex flex-col">
          {/* Citation */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.15, ease: [0.16, 1, 0.3, 1] }}
            className="my-auto max-w-[480px]"
          >
            <p className="font-display italic text-[48px] leading-[1.1] tracking-[-0.015em] text-[#F4F1ED]/95 mb-8">
              « En 3 semaines avec Jenny, on a doublé notre conversion sur Insta. Je n&apos;ouvre
              quasi plus l&apos;app moi-même. »
            </p>
            <div className="flex items-center gap-3.5">
              <div className="w-11 h-11 rounded-full bg-jenny-coral flex items-center justify-center text-white font-bold">
                CL
              </div>
              <div>
                <div className="text-[14.5px] font-semibold text-white">Camille Laurent</div>
                <div className="text-[12.5px] text-[#F4F1ED]/50">Fondatrice, Atelier Caramel</div>
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

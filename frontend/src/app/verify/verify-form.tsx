"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ClipboardEvent,
  type KeyboardEvent,
} from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Mail, ArrowRight, ShieldCheck } from "lucide-react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth-context";
import { useToast } from "@/components/ui/toast";
import { ApiError, resendCode } from "@/lib/api";
import { fadeInUp, staggerContainer, staggerItem } from "@/lib/motion";

const CODE_LENGTH = 6;
const RESEND_COOLDOWN = 60;

const EMPTY = Array.from({ length: CODE_LENGTH }, () => "");

export function VerifyForm({ initialEmail }: { initialEmail: string }) {
  const router = useRouter();
  const { verifyEmail } = useAuth();
  const toast = useToast();

  const [email, setEmail] = useState(initialEmail);
  const emailLocked = initialEmail.length > 0;

  const [digits, setDigits] = useState<string[]>(EMPTY);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isResending, setIsResending] = useState(false);
  const [cooldown, setCooldown] = useState(emailLocked ? RESEND_COOLDOWN : 0);

  const inputsRef = useRef<Array<HTMLInputElement | null>>([]);

  // Focus la première case à l'arrivée (si l'email est déjà connu).
  useEffect(() => {
    if (emailLocked) inputsRef.current[0]?.focus();
  }, [emailLocked]);

  // Décompte du cooldown de renvoi.
  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setInterval(() => setCooldown((c) => (c > 0 ? c - 1 : 0)), 1000);
    return () => clearInterval(t);
  }, [cooldown]);

  const submitCode = useCallback(
    async (code: string) => {
      if (!email) {
        setError("Veuillez renseigner votre adresse email.");
        return;
      }
      setError("");
      setIsLoading(true);
      try {
        await verifyEmail(email, code);
        toast.success("Compte confirmé. Bienvenue chez Jenny !");
        // Nouveau compte → parcours d'accueil (business → canaux → ton de Jenny).
        router.push("/onboarding");
      } catch (err) {
        const detail =
          err instanceof ApiError
            ? (err.data as { detail?: string })?.detail
            : undefined;
        setError(
          detail ||
            (err instanceof ApiError
              ? "Code invalide ou expiré."
              : "Connexion au serveur impossible (localhost:8000).")
        );
        setDigits(EMPTY);
        inputsRef.current[0]?.focus();
      } finally {
        setIsLoading(false);
      }
    },
    [email, verifyEmail, toast, router]
  );

  const maybeSubmit = useCallback(
    (next: string[]) => {
      if (next.every((d) => d !== "")) submitCode(next.join(""));
    },
    [submitCode]
  );

  function handleChange(index: number, raw: string) {
    const clean = raw.replace(/\D/g, "");
    if (!clean) {
      setDigits((d) => d.map((v, i) => (i === index ? "" : v)));
      return;
    }
    const next = [...digits];
    const chars = clean.split("");
    let cursor = index;
    for (const c of chars) {
      if (cursor >= CODE_LENGTH) break;
      next[cursor] = c;
      cursor += 1;
    }
    setDigits(next);
    inputsRef.current[Math.min(cursor, CODE_LENGTH - 1)]?.focus();
    maybeSubmit(next);
  }

  function handleKeyDown(index: number, e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && !digits[index] && index > 0) {
      e.preventDefault();
      setDigits((d) => d.map((v, i) => (i === index - 1 ? "" : v)));
      inputsRef.current[index - 1]?.focus();
    } else if (e.key === "ArrowLeft" && index > 0) {
      inputsRef.current[index - 1]?.focus();
    } else if (e.key === "ArrowRight" && index < CODE_LENGTH - 1) {
      inputsRef.current[index + 1]?.focus();
    }
  }

  function handlePaste(e: ClipboardEvent<HTMLInputElement>) {
    e.preventDefault();
    const text = e.clipboardData
      .getData("text")
      .replace(/\D/g, "")
      .slice(0, CODE_LENGTH);
    if (!text) return;
    const next = [...EMPTY];
    text.split("").forEach((c, i) => (next[i] = c));
    setDigits(next);
    inputsRef.current[Math.min(text.length, CODE_LENGTH - 1)]?.focus();
    maybeSubmit(next);
  }

  async function handleResend() {
    if (!email) {
      setError("Veuillez renseigner votre adresse email.");
      return;
    }
    setError("");
    setIsResending(true);
    try {
      await resendCode(email);
      setCooldown(RESEND_COOLDOWN);
      setDigits(EMPTY);
      inputsRef.current[0]?.focus();
      toast.success("Un nouveau code vous a été envoyé.");
    } catch (err) {
      const detail =
        err instanceof ApiError
          ? (err.data as { detail?: string })?.detail
          : undefined;
      if (err instanceof ApiError && err.status === 429) {
        setCooldown(RESEND_COOLDOWN);
      }
      toast.error(detail || "Impossible de renvoyer le code pour le moment.");
    } finally {
      setIsResending(false);
    }
  }

  return (
    <div className="min-h-full flex flex-col lg:flex-row">
      {/* Left - branding */}
      <div className="hidden lg:flex lg:w-[45%] xl:w-[40%] bg-jenny-sidebar relative overflow-hidden items-end">
        <div className="absolute inset-0">
          <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-jenny-coral/8 rounded-full blur-[120px]" />
          <div className="absolute bottom-0 left-0 w-[400px] h-[400px] bg-jenny-coral/5 rounded-full blur-[100px]" />
        </div>
        <div className="relative z-10 p-10 xl:p-14 w-full">
          <div className="flex items-center gap-3 mb-16">
            <div className="w-11 h-11 rounded-2xl bg-jenny-coral flex items-center justify-center shadow-lg shadow-jenny-coral/25">
              <span className="text-white font-bold text-lg">J</span>
            </div>
            <span className="text-white font-semibold text-xl tracking-tight">Jenny</span>
          </div>

          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
            <h1 className="text-[2.5rem] xl:text-5xl font-bold text-white leading-[1.1] mb-5 max-w-none">
              Plus qu&apos;une étape
              <br />
              <span className="text-jenny-coral">pour activer Jenny</span>
            </h1>
            <p className="text-white/50 text-base xl:text-lg leading-relaxed max-w-md mb-12">
              Nous protégeons votre compte : confirmez votre adresse email avec le code
              que nous venons de vous envoyer.
            </p>
          </motion.div>

          <div className="flex items-center gap-2.5 text-white/30 text-sm font-medium pb-2">
            <ShieldCheck className="w-4 h-4" />
            <span>Confirmation sécurisée</span>
          </div>
        </div>
      </div>

      {/* Right - form */}
      <div className="flex-1 flex items-center justify-center px-6 py-12 lg:px-12">
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="w-full max-w-[420px]"
        >
          <motion.div variants={staggerItem} className="lg:hidden flex items-center gap-3 mb-10">
            <div className="w-10 h-10 rounded-2xl bg-jenny-coral flex items-center justify-center">
              <span className="text-white font-bold text-base">J</span>
            </div>
            <span className="font-semibold text-xl tracking-tight text-jenny-text">Jenny</span>
          </motion.div>

          <motion.div variants={staggerItem} className="mb-8">
            <div className="w-12 h-12 rounded-2xl bg-jenny-coral/10 flex items-center justify-center mb-5">
              <Mail className="w-6 h-6 text-jenny-coral" />
            </div>
            <h2 className="text-[1.75rem] font-bold text-jenny-text tracking-tight">
              Confirmez votre email
            </h2>
            <p className="text-jenny-text-secondary mt-2 text-[0.9375rem] leading-relaxed">
              Entrez le code à 6 chiffres
              {email ? (
                <>
                  {" "}envoyé à <span className="font-semibold text-jenny-text">{email}</span>
                </>
              ) : (
                " que nous vous avons envoyé par email"
              )}
              .
            </p>
          </motion.div>

          {!emailLocked && (
            <motion.div variants={staggerItem} className="mb-6">
              <Input
                label="Email"
                type="email"
                placeholder="vous@exemple.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                icon={<Mail className="w-[18px] h-[18px]" />}
                autoComplete="email"
              />
            </motion.div>
          )}

          <motion.div variants={staggerItem}>
            <div className="flex items-center justify-between gap-2 sm:gap-3" onPaste={handlePaste}>
              {digits.map((d, i) => (
                <input
                  key={i}
                  ref={(el) => {
                    inputsRef.current[i] = el;
                  }}
                  type="text"
                  inputMode="numeric"
                  autoComplete={i === 0 ? "one-time-code" : "off"}
                  maxLength={1}
                  value={d}
                  disabled={isLoading}
                  aria-label={`Chiffre ${i + 1}`}
                  onChange={(e) => handleChange(i, e.target.value)}
                  onKeyDown={(e) => handleKeyDown(i, e)}
                  onFocus={(e) => e.target.select()}
                  className={`w-12 h-14 sm:w-[52px] sm:h-16 text-center text-2xl font-bold rounded-2xl bg-white border-2 text-jenny-text transition-all duration-150 focus:outline-none focus:ring-4 focus:ring-jenny-coral/15 focus:border-jenny-coral disabled:opacity-50 ${
                    d ? "border-jenny-coral/60 bg-jenny-coral/[0.04]" : "border-jenny-divider"
                  } ${error ? "border-jenny-error/50" : ""}`}
                />
              ))}
            </div>

            {error && (
              <motion.p
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                className="mt-4 text-sm text-jenny-error leading-relaxed"
              >
                {error}
              </motion.p>
            )}
          </motion.div>

          <motion.div variants={staggerItem} className="mt-7">
            <Button
              type="button"
              className="w-full"
              size="lg"
              isLoading={isLoading}
              disabled={digits.some((d) => !d)}
              onClick={() => submitCode(digits.join(""))}
            >
              Confirmer mon compte
              {!isLoading && <ArrowRight className="w-4 h-4 ml-1" />}
            </Button>
          </motion.div>

          <motion.div variants={staggerItem} className="mt-6 text-center text-sm text-jenny-text-secondary">
            Vous n&apos;avez pas reçu le code ?{" "}
            {cooldown > 0 ? (
              <span className="text-jenny-text-secondary/70">
                Renvoyer dans {cooldown}s
              </span>
            ) : (
              <button
                type="button"
                onClick={handleResend}
                disabled={isResending}
                className="text-jenny-coral font-semibold hover:underline underline-offset-2 disabled:opacity-50"
              >
                {isResending ? "Envoi…" : "Renvoyer le code"}
              </button>
            )}
          </motion.div>

          <motion.p variants={fadeInUp} className="text-center text-sm text-jenny-text-secondary mt-8">
            Mauvaise adresse ?{" "}
            <Link href="/register" className="text-jenny-coral font-semibold hover:underline underline-offset-2">
              Revenir à l&apos;inscription
            </Link>
          </motion.p>
        </motion.div>
      </div>
    </div>
  );
}

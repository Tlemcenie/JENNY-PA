"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Mail, Lock, User, ArrowRight } from "lucide-react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/api";
import { staggerContainer, staggerItem } from "@/lib/motion";

export default function RegisterPage() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const { register } = useAuth();
  const router = useRouter();

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
        setError("Impossible de se connecter au serveur. Vérifiez que le backend est lancé sur localhost:8000.");
      }
    } finally {
      setIsLoading(false);
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

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
          >
            <h1 className="text-[2.5rem] xl:text-5xl font-bold text-white leading-[1.1] mb-5 max-w-none">
              Rejoignez Jenny
              <br />
              <span className="text-jenny-coral">en quelques secondes</span>
            </h1>
            <p className="text-white/50 text-base xl:text-lg leading-relaxed max-w-md mb-12">
              Créez votre compte et commencez à utiliser l&apos;IA pour gérer vos messages clients.
            </p>
          </motion.div>

          <div className="text-white/30 text-sm font-medium pb-2">
            Inscription gratuite
          </div>
        </div>
      </div>

      {/* Right - form */}
      <div className="flex-1 flex items-center justify-center px-6 py-12 lg:px-12">
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="w-full max-w-[400px]"
        >
          <motion.div variants={staggerItem} className="lg:hidden flex items-center gap-3 mb-10">
            <div className="w-10 h-10 rounded-2xl bg-jenny-coral flex items-center justify-center">
              <span className="text-white font-bold text-base">J</span>
            </div>
            <span className="font-semibold text-xl tracking-tight text-jenny-text">Jenny</span>
          </motion.div>

          <motion.div variants={staggerItem} className="mb-8">
            <h2 className="text-[1.75rem] font-bold text-jenny-text tracking-tight">
              Créer un compte
            </h2>
            <p className="text-jenny-text-secondary mt-2 text-[0.9375rem]">
              Commencez à utiliser Jenny aujourd&apos;hui
            </p>
          </motion.div>

          <motion.form variants={staggerContainer} onSubmit={handleSubmit} className="space-y-5">
            <motion.div variants={staggerItem}>
              <Input
                label="Nom complet"
                type="text"
                placeholder="Votre nom"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                icon={<User className="w-[18px] h-[18px]" />}
                required
                autoComplete="name"
              />
            </motion.div>

            <motion.div variants={staggerItem}>
              <Input
                label="Email"
                type="email"
                placeholder="vous@exemple.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                icon={<Mail className="w-[18px] h-[18px]" />}
                required
                autoComplete="email"
              />
            </motion.div>

            <motion.div variants={staggerItem}>
              <Input
                label="Mot de passe"
                type="password"
                placeholder="Min. 8 car., 1 majuscule, 1 chiffre, 1 spécial"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                icon={<Lock className="w-[18px] h-[18px]" />}
                required
                autoComplete="new-password"
                minLength={8}
              />
            </motion.div>

            {error && (
              <motion.div
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                className="p-3.5 rounded-xl bg-jenny-error/8 border border-jenny-error/15 text-jenny-error text-sm leading-relaxed"
              >
                {error}
              </motion.div>
            )}

            <motion.div variants={staggerItem}>
              <Button type="submit" className="w-full" size="lg" isLoading={isLoading}>
                Créer mon compte
                {!isLoading && <ArrowRight className="w-4 h-4 ml-1" />}
              </Button>
            </motion.div>
          </motion.form>

          <motion.p variants={staggerItem} className="text-center text-sm text-jenny-text-secondary mt-8">
            Déjà un compte ?{" "}
            <Link href="/login" className="text-jenny-coral font-semibold hover:underline underline-offset-2">
              Se connecter
            </Link>
          </motion.p>
        </motion.div>
      </div>
    </div>
  );
}

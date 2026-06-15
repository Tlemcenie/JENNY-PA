"use client";

import { useState, useEffect, useCallback, type FormEvent } from "react";
import { motion } from "framer-motion";
import {
  Mail,
  Shield,
  UserCircle,
  Building2,
  Lock,
  CheckCircle2,
  AlertCircle,
  Save,
} from "lucide-react";
import {
  getBusiness,
  updateBusiness,
  updateMe,
  type BusinessConfig,
  ApiError,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorState } from "@/components/shared/error-state";
import { useToast } from "@/components/ui/toast";
import { TeamSection } from "@/components/settings/team-section";
import { BusinessHoursSection } from "@/components/settings/business-hours-section";
import { SlaSection } from "@/components/settings/sla-section";
import { ApiKeysSection } from "@/components/settings/api-keys-section";
import { AuditSection } from "@/components/settings/audit-section";
import { cn, roleLabel } from "@/lib/utils";

// Fuseaux horaires courants (IANA) — francophones en tête.
const TIMEZONES = [
  "Europe/Paris",
  "Europe/Brussels",
  "Europe/Zurich",
  "Europe/London",
  "Europe/Madrid",
  "Europe/Berlin",
  "Africa/Casablanca",
  "Africa/Abidjan",
  "America/Montreal",
  "America/New_York",
  "UTC",
];

type Feedback = { ok: boolean; text: string } | null;

function extractError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    return (err.data as { detail?: string })?.detail || `Erreur ${err.status}`;
  }
  return fallback;
}

function FeedbackLine({ msg }: { msg: Feedback }) {
  if (!msg) return null;
  return (
    <div
      className={cn(
        "p-3 rounded-xl text-sm flex items-center gap-2",
        msg.ok
          ? "bg-jenny-success/10 text-jenny-success"
          : "bg-jenny-error/10 text-jenny-error"
      )}
    >
      {msg.ok ? (
        <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
      ) : (
        <AlertCircle className="w-4 h-4 flex-shrink-0" />
      )}
      {msg.text}
    </div>
  );
}

export default function SettingsPage() {
  const { user, refreshUser } = useAuth();
  const toast = useToast();

  // ── Compte : nom complet ──
  const [fullName, setFullName] = useState(user?.full_name || "");
  const [savingAccount, setSavingAccount] = useState(false);
  const [accountMsg, setAccountMsg] = useState<Feedback>(null);

  // ── Compte : mot de passe ──
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  const [passwordMsg, setPasswordMsg] = useState<Feedback>(null);

  // ── Entreprise ──
  const [loadingBiz, setLoadingBiz] = useState(true);
  const [bizError, setBizError] = useState<string | null>(null);
  const [bizName, setBizName] = useState("");
  const [bizEmail, setBizEmail] = useState("");
  const [bizPhone, setBizPhone] = useState("");
  const [bizDescription, setBizDescription] = useState("");
  const [bizTimezone, setBizTimezone] = useState("Europe/Paris");
  const [bizSlug, setBizSlug] = useState("");
  const [savingBiz, setSavingBiz] = useState(false);
  const [bizMsg, setBizMsg] = useState<Feedback>(null);

  const applyBusiness = (b: BusinessConfig) => {
    setBizName(b.name || "");
    setBizEmail(b.email || "");
    setBizPhone(b.phone || "");
    setBizDescription(b.description || "");
    setBizTimezone(b.timezone || "Europe/Paris");
    setBizSlug(b.slug || "");
  };

  const loadBusiness = useCallback(async () => {
    setLoadingBiz(true);
    setBizError(null);
    try {
      applyBusiness(await getBusiness());
    } catch (err) {
      setBizError(
        extractError(err, "Impossible de charger la configuration de l'entreprise.")
      );
    } finally {
      setLoadingBiz(false);
    }
  }, []);

  useEffect(() => {
    loadBusiness();
  }, [loadBusiness]);

  useEffect(() => {
    setFullName(user?.full_name || "");
  }, [user?.full_name]);

  const handleAccount = async (e: FormEvent) => {
    e.preventDefault();
    setAccountMsg(null);
    setSavingAccount(true);
    try {
      await updateMe({ full_name: fullName.trim() });
      await refreshUser();
      setAccountMsg(null);
      toast.success("Profil mis à jour.");
    } catch (err) {
      setAccountMsg({ ok: false, text: extractError(err, "Échec de la mise à jour.") });
    } finally {
      setSavingAccount(false);
    }
  };

  const handlePassword = async (e: FormEvent) => {
    e.preventDefault();
    setPasswordMsg(null);
    setSavingPassword(true);
    try {
      await updateMe({
        current_password: currentPassword,
        new_password: newPassword,
      });
      setPasswordMsg(null);
      setCurrentPassword("");
      setNewPassword("");
      toast.success("Mot de passe modifié.");
    } catch (err) {
      setPasswordMsg({
        ok: false,
        text: extractError(err, "Échec du changement de mot de passe."),
      });
    } finally {
      setSavingPassword(false);
    }
  };

  const handleBusiness = async (e: FormEvent) => {
    e.preventDefault();
    setBizMsg(null);
    setSavingBiz(true);
    try {
      const updated = await updateBusiness({
        name: bizName.trim(),
        email: bizEmail.trim() || null,
        phone: bizPhone.trim() || null,
        description: bizDescription.trim() || null,
        timezone: bizTimezone,
      });
      applyBusiness(updated);
      await refreshUser();
      setBizMsg(null);
      toast.success("Configuration enregistrée.");
    } catch (err) {
      setBizMsg({ ok: false, text: extractError(err, "Échec de l'enregistrement.") });
    } finally {
      setSavingBiz(false);
    }
  };

  if (!user) return null;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-2xl mx-auto p-6 space-y-6">
        {/* En-tête profil */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
          <Card className="flex items-center gap-6 p-8">
            <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-jenny-coral to-jenny-coral-dark flex items-center justify-center flex-shrink-0">
              <span className="text-white text-3xl font-bold">
                {(user.full_name || user.email)?.charAt(0)?.toUpperCase() || "?"}
              </span>
            </div>
            <div className="min-w-0">
              <h2 className="text-2xl font-bold text-jenny-text truncate">
                {user.full_name || "Sans nom"}
              </h2>
              <p className="text-jenny-text-secondary flex items-center gap-2 mt-1">
                <Mail className="w-4 h-4" />
                {user.email}
              </p>
              <div className="flex items-center gap-2 mt-2">
                {user.role && (
                  <Badge variant="success">
                    <Shield className="w-3 h-3 mr-1" />
                    {roleLabel(user.role)}
                  </Badge>
                )}
                {user.business_name && <Badge>{user.business_name}</Badge>}
              </div>
            </div>
          </Card>
        </motion.div>

        {/* Compte : informations */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
        >
          <Card className="p-6">
            <div className="flex items-center gap-3 mb-5">
              <UserCircle className="w-5 h-5 text-jenny-coral" />
              <h3 className="font-semibold text-jenny-text">Informations du compte</h3>
            </div>
            <form onSubmit={handleAccount} className="space-y-4">
              <Input
                label="Nom complet"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Votre nom"
                required
              />
              <Input label="Email" value={user.email} disabled />
              <FeedbackLine msg={accountMsg} />
              <div className="flex justify-end">
                <Button type="submit" isLoading={savingAccount}>
                  <Save className="w-4 h-4" />
                  Enregistrer
                </Button>
              </div>
            </form>
          </Card>
        </motion.div>

        {/* Compte : mot de passe */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
        >
          <Card className="p-6">
            <div className="flex items-center gap-3 mb-5">
              <Lock className="w-5 h-5 text-jenny-coral" />
              <h3 className="font-semibold text-jenny-text">Mot de passe</h3>
            </div>
            <form onSubmit={handlePassword} className="space-y-4">
              <Input
                label="Mot de passe actuel"
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete="current-password"
                required
              />
              <Input
                label="Nouveau mot de passe"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="Au moins 8 caractères, 1 majuscule, 1 chiffre, 1 caractère spécial"
                autoComplete="new-password"
                required
              />
              <FeedbackLine msg={passwordMsg} />
              <div className="flex justify-end">
                <Button type="submit" isLoading={savingPassword}>
                  <Save className="w-4 h-4" />
                  Modifier le mot de passe
                </Button>
              </div>
            </form>
          </Card>
        </motion.div>

        {/* Entreprise */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15 }}
        >
          <Card className="p-6">
            <div className="flex items-center gap-3 mb-5">
              <Building2 className="w-5 h-5 text-jenny-coral" />
              <h3 className="font-semibold text-jenny-text">Entreprise</h3>
            </div>

            {loadingBiz ? (
              <div className="space-y-3">
                <div className="h-12 rounded-xl animate-shimmer" />
                <div className="h-12 rounded-xl animate-shimmer" />
                <div className="h-24 rounded-xl animate-shimmer" />
              </div>
            ) : bizError ? (
              <ErrorState message={bizError} onRetry={loadBusiness} />
            ) : (
              <form onSubmit={handleBusiness} className="space-y-4">
                <Input
                  label="Nom de l'entreprise"
                  value={bizName}
                  onChange={(e) => setBizName(e.target.value)}
                  placeholder="Ex: Ma Boutique"
                  required
                />
                <div className="grid sm:grid-cols-2 gap-4">
                  <Input
                    label="Email de contact"
                    type="email"
                    value={bizEmail}
                    onChange={(e) => setBizEmail(e.target.value)}
                    placeholder="contact@exemple.fr"
                  />
                  <Input
                    label="Téléphone"
                    value={bizPhone}
                    onChange={(e) => setBizPhone(e.target.value)}
                    placeholder="+33 1 23 45 67 89"
                  />
                </div>

                <div className="flex flex-col gap-2">
                  <label
                    htmlFor="biz-timezone"
                    className="text-[0.8125rem] font-semibold text-jenny-text"
                  >
                    Fuseau horaire
                  </label>
                  <select
                    id="biz-timezone"
                    value={bizTimezone}
                    onChange={(e) => setBizTimezone(e.target.value)}
                    className="h-12 px-4 rounded-xl bg-white border border-jenny-divider text-[0.9375rem] text-jenny-text focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral hover:border-jenny-text-secondary/30 transition-all"
                  >
                    {TIMEZONES.map((tz) => (
                      <option key={tz} value={tz}>
                        {tz}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="flex flex-col gap-2">
                  <label
                    htmlFor="biz-description"
                    className="text-[0.8125rem] font-semibold text-jenny-text"
                  >
                    Description
                  </label>
                  <textarea
                    id="biz-description"
                    value={bizDescription}
                    onChange={(e) => setBizDescription(e.target.value)}
                    placeholder="Présentez votre activité en quelques mots..."
                    rows={4}
                    className="w-full px-4 py-3 rounded-xl bg-white border border-jenny-divider text-[0.9375rem] text-jenny-text placeholder:text-jenny-text-secondary/50 focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral hover:border-jenny-text-secondary/30 transition-all resize-none"
                  />
                </div>

                {bizSlug && (
                  <p className="text-xs text-jenny-text-secondary">
                    Identifiant&nbsp;:{" "}
                    <span className="font-mono text-jenny-text">{bizSlug}</span>
                  </p>
                )}

                <FeedbackLine msg={bizMsg} />
                <div className="flex justify-end">
                  <Button type="submit" isLoading={savingBiz}>
                    <Save className="w-4 h-4" />
                    Enregistrer
                  </Button>
                </div>
              </form>
            )}
          </Card>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
        >
          <BusinessHoursSection />
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15 }}
        >
          <TeamSection />
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
        >
          <SlaSection />
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
        >
          <ApiKeysSection />
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
        >
          <AuditSection />
        </motion.div>
      </div>
    </div>
  );
}

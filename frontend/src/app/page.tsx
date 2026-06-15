"use client";

import Link from "next/link";
import Image from "next/image";
import { motion } from "framer-motion";
import {
  ArrowRight,
  Eye,
  Brain,
  Zap,
  Hash,
  Activity,
  Mic,
  TrendingUp,
  Tag,
  MessageCircle,
  AtSign,
  Mail,
  Music,
  Globe,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";

// Page d'accueil publique (DA « Jenny Front ») — nuit profonde + corail,
// titres en Instrument Serif, accents mono. Recrée fidèlement l'écran Landing
// du design handoff, adaptée à Next + au stack existant.

const NAV_LINKS = ["Produit", "Cas d'usage", "Tarifs", "Documentation"];

const FEATURES = [
  {
    icon: Brain,
    title: "Comprend l'intention",
    body: "Détecte si le client veut acheter, se plaindre, ou juste poser une question — et route au bon agent IA.",
  },
  {
    icon: Zap,
    title: "Agit, pas juste parle",
    body: "Crée un devis, prend un RDV, vérifie un stock, envoie un lien de paiement — automatiquement.",
  },
  {
    icon: Hash,
    title: "Apprend votre catalogue",
    body: "Importez vos PDF, vos FAQ, votre site — Jenny les utilise comme un employé qui connaît la maison.",
  },
  {
    icon: Activity,
    title: "Détecte ce qui compte",
    body: "Vous notifie seulement quand un humain est nécessaire. Le reste, elle s'en occupe.",
  },
  {
    icon: Mic,
    title: "Parle votre langue",
    body: "Pro, cool, vendeur, chaleureux — vous définissez le ton. Jenny s'y tient sur tous les canaux.",
  },
  {
    icon: TrendingUp,
    title: "Révèle vos angles morts",
    body: "« 80% de vos clients demandent X » — Jenny vous dit ce que vous ratez.",
  },
];

const PAGE_BG =
  "radial-gradient(ellipse at 70% 0%, rgba(255,127,106,0.18) 0%, transparent 50%), radial-gradient(ellipse at 0% 80%, rgba(114,132,168,0.12) 0%, transparent 50%), #0E0B14";

function MascotBubble() {
  return (
    <span className="w-6 h-6 rounded-full overflow-hidden shrink-0 bg-jenny-coral block relative">
      <Image
        src="/jenny.png"
        alt="Jenny"
        width={29}
        height={29}
        className="object-cover w-[120%] h-[120%] mt-0.5 max-w-none"
      />
    </span>
  );
}

export default function LandingPage() {
  const { isAuthenticated } = useAuth();
  const ctaHref = isAuthenticated ? "/chat" : "/register";

  return (
    <div
      className="h-full overflow-y-auto text-[#F4F1ED]"
      style={{ background: PAGE_BG, fontFamily: "var(--font-sans)" }}
    >
      {/* ── Nav ── */}
      <nav
        className="sticky top-0 z-20 flex items-center px-6 md:px-16 py-5"
        style={{ backdropFilter: "blur(12px)", background: "rgba(14,11,20,0.7)" }}
      >
        <Link href="/" className="flex items-center gap-2.5">
          <span className="w-9 h-9 rounded-[10px] overflow-hidden bg-jenny-coral block">
            <Image src="/jenny.png" alt="Jenny" width={36} height={36} className="object-cover w-full h-full" />
          </span>
          <span className="text-[19px] font-bold tracking-[-0.02em]">Jenny</span>
        </Link>
        <div className="hidden lg:flex gap-8 ml-16">
          {NAV_LINKS.map((t) => (
            <span
              key={t}
              className="text-[13.5px] font-medium text-[#F4F1ED]/60 hover:text-[#F4F1ED]/90 transition-colors cursor-pointer"
            >
              {t}
            </span>
          ))}
        </div>
        <div className="ml-auto flex gap-3 items-center">
          {isAuthenticated ? (
            <Link
              href="/chat"
              className="h-8 px-3 rounded-lg text-[12.5px] font-semibold inline-flex items-center gap-2 bg-jenny-coral text-white hover:bg-jenny-coral-dark transition-colors"
              style={{ boxShadow: "0 4px 14px rgba(255,127,106,0.25)" }}
            >
              Ouvrir le tableau de bord →
            </Link>
          ) : (
            <>
              <Link
                href="/login"
                className="text-[13.5px] font-medium text-[#F4F1ED]/70 hover:text-[#F4F1ED] transition-colors"
              >
                Connexion
              </Link>
              <Link
                href="/register"
                className="h-8 px-3 rounded-lg text-[12.5px] font-semibold inline-flex items-center gap-2 bg-jenny-coral text-white hover:bg-jenny-coral-dark transition-colors"
                style={{ boxShadow: "0 4px 14px rgba(255,127,106,0.25)" }}
              >
                Essayer gratuitement →
              </Link>
            </>
          )}
        </div>
      </nav>

      {/* ── Hero ── */}
      <header className="px-6 md:px-16 pt-12 md:pt-[72px] pb-16 md:pb-[100px]">
        <div className="max-w-[1100px] mx-auto">
          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
            <div
              className="inline-flex items-center gap-2 rounded-full mb-8 pl-1.5 pr-3.5 py-1.5"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
            >
              <span className="px-2.5 py-[3px] rounded-full bg-jenny-coral text-white text-[10.5px] font-bold tracking-[0.06em] uppercase font-mono">
                Nouveau
              </span>
              <span className="text-[12.5px] text-[#F4F1ED]/75">
                Auto-pilote · Jenny répond seule en moins de 2 secondes
              </span>
            </div>

            <h1 className="font-display font-normal tracking-[-0.03em] mb-7 text-[clamp(48px,9vw,116px)]" style={{ lineHeight: 0.96 }}>
              Chaque message client,
              <br />
              <span className="italic text-jenny-coral">une opportunité.</span>
            </h1>
            <p className="text-[17px] md:text-[19px] leading-[1.5] text-[#F4F1ED]/65 max-w-[580px] mb-10">
              Jenny est l&apos;assistante IA qui répond à vos clients sur WhatsApp, Instagram et Email — 24/7, dans
              votre ton, avec votre catalogue.
            </p>
            <div className="flex flex-wrap gap-3.5 items-center mb-16 md:mb-20">
              <Link
                href={ctaHref}
                className="h-[50px] px-6 rounded-xl text-[15px] font-semibold inline-flex items-center gap-2 bg-jenny-coral text-white hover:bg-jenny-coral-dark transition-colors"
                style={{ boxShadow: "0 4px 14px rgba(255,127,106,0.25)" }}
              >
                Activer Jenny pour mon business
                <ArrowRight className="w-4 h-4" />
              </Link>
              <button
                className="h-[50px] px-6 rounded-xl text-[15px] font-semibold inline-flex items-center gap-2 text-white transition-colors hover:bg-white/10"
                style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)" }}
              >
                <Eye className="w-4 h-4" />
                Voir une démo (90s)
              </button>
              <span className="text-[12.5px] text-[#F4F1ED]/40 ml-2 font-mono">Sans CB · Activation en 4 minutes</span>
            </div>
          </motion.div>

          {/* Hero visual — aperçu de chat flottant */}
          <motion.div
            initial={{ opacity: 0, y: 28 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.15 }}
            className="relative rounded-[24px] overflow-hidden p-6 md:p-12 grid md:grid-cols-2 gap-8 md:gap-12 items-center"
            style={{
              background: "linear-gradient(180deg, rgba(255,127,106,0.08) 0%, rgba(255,255,255,0.02) 100%)",
              border: "1px solid rgba(255,255,255,0.08)",
            }}
          >
            {/* Mascotte */}
            <div className="relative h-[260px] md:h-[340px] flex items-center justify-center">
              <div
                className="absolute"
                style={{
                  inset: "-20%",
                  background: "radial-gradient(circle, rgba(255,127,106,0.4) 0%, transparent 60%)",
                  filter: "blur(20px)",
                }}
              />
              <Image
                src="/jenny.png"
                alt="Jenny, votre assistante"
                width={340}
                height={340}
                priority
                className="relative h-[260px] md:h-[340px] w-auto object-contain max-w-none"
                style={{ filter: "drop-shadow(0 30px 60px rgba(255,127,106,0.4))" }}
              />
            </div>

            {/* Chat */}
            <div className="flex flex-col gap-2.5">
              <div className="self-end max-w-[85%] px-4 py-3 bg-jenny-coral text-[#1a0a08] text-[14.5px] font-medium rounded-[16px_16px_4px_16px]">
                Bonjour, vous livrez à Bordeaux ?
              </div>
              <div className="self-start flex gap-2 items-end">
                <MascotBubble />
                <div
                  className="max-w-[85%] px-4 py-3 text-[14.5px] text-[#F4F1ED]/95 rounded-[16px_16px_16px_4px]"
                  style={{ background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.08)" }}
                >
                  Oui Sophie 👋 Livraison gratuite à Bordeaux dès 50€. Vous voulez que je finalise ?
                </div>
              </div>
              <div className="self-end max-w-[85%] px-4 py-3 bg-jenny-coral text-[#1a0a08] text-[14.5px] font-medium rounded-[16px_16px_4px_16px]">
                Le sac caramel taille M.
              </div>
              <div className="self-start flex gap-2 items-end">
                <MascotBubble />
                <div
                  className="max-w-[90%] px-4 py-3 text-[14.5px] text-[#F4F1ED]/95 rounded-[16px_16px_16px_4px]"
                  style={{ background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.08)" }}
                >
                  <div className="mb-2.5">Parfait — il en reste 3. Je vous envoie le lien :</div>
                  <div
                    className="px-3 py-2.5 rounded-[10px] flex items-center gap-2.5"
                    style={{ background: "rgba(255,127,106,0.12)", border: "1px solid rgba(255,127,106,0.25)" }}
                  >
                    <Tag className="w-4 h-4 text-jenny-coral shrink-0" />
                    <div className="flex-1">
                      <div className="text-[13px] font-semibold text-white">Sac Caramel · Taille M</div>
                      <div className="text-[11px] text-[#F4F1ED]/50 font-mono">89,00 € · 3 en stock</div>
                    </div>
                    <ArrowRight className="w-3.5 h-3.5 text-jenny-coral" />
                  </div>
                </div>
              </div>
              <div
                className="self-start px-3.5 py-2 rounded-full flex gap-1.5 mt-1"
                style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
              >
                {[0, 1, 2].map((i) => (
                  <motion.span
                    key={i}
                    className="w-1.5 h-1.5 rounded-full bg-jenny-coral"
                    animate={{ opacity: [0.3, 1, 0.3] }}
                    transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.2 }}
                  />
                ))}
              </div>
            </div>
          </motion.div>

          {/* Trust / canaux */}
          <div className="mt-16 md:mt-20 flex flex-wrap gap-8 md:gap-12 items-center justify-center opacity-50">
            <span className="font-mono text-[11px] tracking-[0.18em] uppercase">Connectez en un clic ·</span>
            <MessageCircle className="w-6 h-6" />
            <AtSign className="w-6 h-6" />
            <Mail className="w-6 h-6" />
            <Music className="w-6 h-6" />
            <Globe className="w-6 h-6" />
          </div>
        </div>
      </header>

      {/* ── Features ── */}
      <section
        className="px-6 md:px-16 py-16 md:py-20"
        style={{
          background: "rgba(255,255,255,0.02)",
          borderTop: "1px solid rgba(255,255,255,0.05)",
          borderBottom: "1px solid rgba(255,255,255,0.05)",
        }}
      >
        <div className="max-w-[1100px] mx-auto">
          <div className="font-mono text-[11px] tracking-[0.32em] uppercase text-jenny-coral mb-[18px]">
            — ce que jenny fait —
          </div>
          <h2 className="font-display text-[40px] md:text-[64px] leading-[1.05] tracking-[-0.02em] mb-12 md:mb-16 max-w-[800px]">
            Une IA qui ne se contente pas de <span className="italic text-jenny-coral">répondre.</span>
          </h2>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {FEATURES.map((f) => {
              const Icon = f.icon;
              return (
                <motion.div
                  key={f.title}
                  initial={{ opacity: 0, y: 16 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, margin: "-40px" }}
                  transition={{ duration: 0.4 }}
                  className="p-7 rounded-[18px]"
                  style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)" }}
                >
                  <div
                    className="w-11 h-11 rounded-[11px] flex items-center justify-center mb-[18px] text-jenny-coral"
                    style={{ background: "rgba(255,127,106,0.12)" }}
                  >
                    <Icon className="w-6 h-6" />
                  </div>
                  <div className="text-[17px] font-semibold mb-2 tracking-[-0.01em]">{f.title}</div>
                  <div className="text-[14px] leading-[1.55] text-[#F4F1ED]/55">{f.body}</div>
                </motion.div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── CTA final ── */}
      <section className="px-6 md:px-16 py-20 md:py-[100px] text-center">
        <h2 className="font-display text-[44px] md:text-[80px] leading-none tracking-[-0.025em] mb-6">
          Prêt à arrêter de répondre
          <br />
          aux <span className="italic text-jenny-coral">mêmes questions ?</span>
        </h2>
        <p className="text-[17px] text-[#F4F1ED]/55 mb-9 max-w-[540px] mx-auto">
          14 jours gratuits. Aucun engagement. Annulez en un clic.
        </p>
        <Link
          href={ctaHref}
          className="h-[58px] px-8 rounded-xl text-[16px] font-semibold inline-flex items-center gap-2 bg-jenny-coral text-white hover:bg-jenny-coral-dark transition-colors"
          style={{ boxShadow: "0 4px 14px rgba(255,127,106,0.25)" }}
        >
          Activer Jenny maintenant
          <ArrowRight className="w-[18px] h-[18px]" />
        </Link>
      </section>

      {/* ── Footer ── */}
      <footer
        className="px-6 md:px-16 py-8 flex flex-wrap gap-3 items-center justify-between"
        style={{ borderTop: "1px solid rgba(255,255,255,0.05)" }}
      >
        <span className="text-[11px] text-[#F4F1ED]/40 font-mono tracking-[0.08em]">
          © 2026 Jenny — Hébergé en France · RGPD
        </span>
        <div className="flex gap-5 text-[12.5px] text-[#F4F1ED]/50">
          <span className="hover:text-[#F4F1ED]/80 transition-colors cursor-pointer">Confidentialité</span>
          <span className="hover:text-[#F4F1ED]/80 transition-colors cursor-pointer">Conditions</span>
          <span className="hover:text-[#F4F1ED]/80 transition-colors cursor-pointer">Contact</span>
        </div>
      </footer>
    </div>
  );
}

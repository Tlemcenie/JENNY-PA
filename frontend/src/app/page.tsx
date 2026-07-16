"use client";

import { useRef } from "react";
import Link from "next/link";
import Image from "next/image";
import { motion, useScroll, useTransform, useReducedMotion } from "framer-motion";
import {
  ArrowRight,
  Check,
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
  ChevronDown,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { JennyAvatar } from "@/components/ui/jenny-avatar";
import { staggerContainer, staggerItem } from "@/lib/motion";

// landing publique, hero animé

// ancres de nav
const NAV_LINKS: { label: string; target: string }[] = [
  { label: "Produit", target: "produit" },
  { label: "Cas d'usage", target: "apercu" },
  { label: "Tarifs", target: "tarifs" },
  { label: "FAQ", target: "faq" },
];

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

// avatar des bulles
function MascotBubble() {
  return <JennyAvatar size={24} tone="dark" />;
}

export default function LandingPage() {
  const { isAuthenticated } = useAuth();
  const ctaHref = isAuthenticated ? "/chat" : "/register";
  const reduce = useReducedMotion();

  // scroll dans ce conteneur
  const scrollRef = useRef<HTMLDivElement>(null);
  const heroRef = useRef<HTMLElement>(null);

  const { scrollYProgress } = useScroll({
    container: scrollRef,
    target: heroRef,
    offset: ["start start", "end start"],
  });

  // parallaxe du hero
  const videoY = useTransform(scrollYProgress, [0, 1], ["0%", "16%"]);
  const videoScale = useTransform(scrollYProgress, [0, 1], [1, 1.14]);
  // wordmark en fond
  const wordmarkY = useTransform(scrollYProgress, [0, 1], ["0%", "-12%"]);
  const mascotY = useTransform(scrollYProgress, [0, 1], ["0%", "20%"]);
  const contentY = useTransform(scrollYProgress, [0, 1], ["0%", "-14%"]);
  // cta visible longtemps
  const contentFade = useTransform(scrollYProgress, [0, 0.95], [1, 0]);

  return (
    <div
      ref={scrollRef}
      className="relative h-full overflow-y-auto text-[#F4F1ED]"
      style={{ background: PAGE_BG, fontFamily: "var(--font-sans)", scrollbarGutter: "stable" }}
    >
      {/* nav */}
      <nav
        className="sticky top-0 z-30 flex items-center px-6 md:px-16 py-5"
        style={{ backdropFilter: "blur(12px)", background: "rgba(14,11,20,0.7)" }}
      >
        <Link href="/" className="flex items-center gap-2.5 group">
          <JennyAvatar size={38} tone="dark" />
          <span className="text-[20px] font-bold tracking-[-0.02em] group-hover:text-jenny-coral transition-colors">
            Jenny
          </span>
        </Link>
        <div className="hidden lg:flex gap-8 ml-16">
          {NAV_LINKS.map((item) => (
            <a
              key={item.target}
              href={`#${item.target}`}
              className="text-[13.5px] font-medium text-[#F4F1ED]/60 hover:text-[#F4F1ED]/90 transition-colors cursor-pointer"
            >
              {item.label}
            </a>
          ))}
        </div>
        <div className="ml-auto flex gap-3 items-center">
          {isAuthenticated ? (
            <Link
              href="/chat"
              className="btn-fluffy h-9 px-4 text-[12.5px] font-semibold inline-flex items-center gap-2 bg-jenny-coral text-white hover:bg-jenny-coral-dark"
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
                className="btn-fluffy h-9 px-4 text-[12.5px] font-semibold inline-flex items-center gap-2 bg-jenny-coral text-white hover:bg-jenny-coral-dark"
              >
                Essayer gratuitement →
              </Link>
            </>
          )}
        </div>
      </nav>

      {/* hero en couches */}
      <header
        ref={heroRef}
        className="relative isolate overflow-hidden flex flex-col justify-center min-h-[600px] md:min-h-[90vh]"
      >
        {/* couche 0 : vidéo en fond */}
        <motion.div
          aria-hidden
          style={reduce ? undefined : { y: videoY, scale: videoScale }}
          className="absolute inset-0 z-0 will-change-transform"
        >
          <iframe
            src="/jenny-intro/index.html?embed=1"
            title="Jenny en action"
            loading="lazy"
            scrolling="no"
            tabIndex={-1}
            aria-hidden
            className="pointer-events-none absolute inset-0 h-full w-full"
            style={{ border: 0 }}
          />
        </motion.div>

        {/* couche 1 : wordmark fantôme */}
        <motion.div
          aria-hidden
          style={reduce ? undefined : { y: wordmarkY }}
          className="pointer-events-none absolute inset-x-0 bottom-[-4%] z-[1] flex justify-center select-none will-change-transform"
        >
          <span
            className="font-display leading-[0.8] tracking-[-0.04em] text-[30vw] md:text-[24vw]"
            style={{
              // longhand, sinon warning react
              backgroundImage:
                "linear-gradient(180deg, rgba(255,127,106,0.30) 0%, rgba(255,127,106,0.10) 58%, transparent 88%)",
              WebkitBackgroundClip: "text",
              backgroundClip: "text",
              color: "transparent",
              // halo corail
              filter: "drop-shadow(0 0 48px rgba(255,127,106,0.18))",
            }}
          >
            Jenny
          </span>
        </motion.div>

        {/* couche 2 : voiles lisibilité */}
        <div
          aria-hidden
          className="absolute inset-0 z-[2] pointer-events-none"
          style={{
            // léger, vidéo visible derrière
            background:
              "linear-gradient(180deg, rgba(14,11,20,0.78) 0%, rgba(14,11,20,0.40) 46%, rgba(14,11,20,0.72) 100%), linear-gradient(100deg, rgba(14,11,20,0.70) 0%, rgba(14,11,20,0.06) 72%)",
          }}
        />

        {/* couche 3 : mascotte */}
        <motion.div
          style={reduce ? undefined : { y: mascotY }}
          className="pointer-events-none absolute right-[-2%] bottom-[-2%] z-[3] hidden lg:block w-[40vw] max-w-[500px] will-change-transform"
        >
          <div
            className="absolute"
            style={{
              inset: "-12%",
              background: "radial-gradient(circle, rgba(255,127,106,0.40) 0%, transparent 62%)",
              filter: "blur(28px)",
            }}
          />
          <Image
            src="/jenny.png"
            alt=""
            width={500}
            height={500}
            priority
            className="relative w-full h-auto object-contain"
            style={{ filter: "drop-shadow(0 40px 80px rgba(255,127,106,0.45))" }}
          />
        </motion.div>

        {/* couche 10 : contenu */}
        <motion.div
          style={reduce ? undefined : { y: contentY, opacity: contentFade }}
          className="relative z-10 w-full max-w-[1100px] mx-auto px-6 md:px-16 py-20 md:py-0 will-change-transform"
        >
          <motion.div variants={staggerContainer} initial="hidden" animate="show" className="max-w-[680px]">
            <motion.div
              variants={staggerItem}
              className="inline-flex items-center gap-2 rounded-full mb-8 pl-1.5 pr-3.5 py-1.5"
              style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.10)" }}
            >
              <span className="px-2.5 py-[3px] rounded-full bg-jenny-coral text-white text-[10.5px] font-bold tracking-[0.06em] uppercase font-mono">
                Nouveau
              </span>
              <span className="text-[12.5px] text-[#F4F1ED]/80">
                Auto-pilote · Jenny répond seule en moins de 2 secondes
              </span>
            </motion.div>

            <motion.h1
              variants={staggerContainer}
              className="font-display font-normal tracking-[-0.03em] mb-7 text-[clamp(48px,9vw,116px)]"
              style={{ lineHeight: 0.96 }}
            >
              {["Chaque", "message", "client,"].map((w) => (
                <motion.span key={w} variants={staggerItem} className="inline-block mr-[0.22em]">
                  {w}
                </motion.span>
              ))}
              <br />
              {["une", "opportunité."].map((w) => (
                <motion.span
                  key={w}
                  variants={staggerItem}
                  className="inline-block mr-[0.22em] italic text-jenny-coral"
                >
                  {w}
                </motion.span>
              ))}
            </motion.h1>
            <motion.p
              variants={staggerItem}
              className="text-[17px] md:text-[19px] leading-[1.5] text-[#F4F1ED]/75 max-w-[560px] mb-10"
            >
              Jenny est l&apos;assistante IA qui répond à vos clients sur WhatsApp, Instagram et Email — 24/7, dans
              votre ton, avec votre catalogue.
            </motion.p>
            <motion.div variants={staggerItem} className="flex flex-wrap gap-3.5 items-center">
              <Link
                href={ctaHref}
                className="btn-fluffy h-[50px] px-7 text-[15px] font-semibold inline-flex items-center gap-2 bg-jenny-coral text-white hover:bg-jenny-coral-dark"
              >
                Activer Jenny pour mon business
                <ArrowRight className="w-4 h-4" />
              </Link>
              <span className="text-[12.5px] text-[#F4F1ED]/45 ml-2 font-mono">Sans CB · Activation en 4 minutes</span>
            </motion.div>
          </motion.div>
        </motion.div>

        {/* indice de scroll */}
        {!reduce && (
          <motion.div
            aria-hidden
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 1.1, duration: 0.6 }}
            className="absolute left-1/2 -translate-x-1/2 bottom-6 z-10 flex flex-col items-center gap-1.5 text-[#F4F1ED]/45"
          >
            <span className="font-mono text-[10px] tracking-[0.3em] uppercase">défilez</span>
            <motion.span
              animate={{ y: [0, 6, 0] }}
              transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
            >
              <ChevronDown className="w-4 h-4" />
            </motion.span>
          </motion.div>
        )}
      </header>

      {/* bandeau canaux */}
      <div className="px-6 md:px-16 py-10 md:py-12">
        <div className="max-w-[1100px] mx-auto flex flex-wrap gap-8 md:gap-12 items-center justify-center opacity-50">
          <span className="font-mono text-[11px] tracking-[0.18em] uppercase">Connectez en un clic ·</span>
          <MessageCircle className="w-6 h-6" />
          <AtSign className="w-6 h-6" />
          <Mail className="w-6 h-6" />
          <Music className="w-6 h-6" />
          <Globe className="w-6 h-6" />
        </div>
      </div>

      {/* cas d'usage */}
      <section id="apercu" className="px-6 md:px-16 pb-16 md:pb-24 scroll-mt-24">
        <div className="max-w-[1100px] mx-auto grid lg:grid-cols-[0.85fr_1.15fr] gap-12 lg:gap-16 items-center">
          {/* colonne éditoriale */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-60px" }}
            transition={{ duration: 0.5 }}
          >
            <div className="font-mono text-[11px] tracking-[0.32em] uppercase text-jenny-coral mb-[18px]">
              — cas d&apos;usage —
            </div>
            <h2 className="font-display text-[40px] md:text-[60px] leading-[1.04] tracking-[-0.02em] mb-5">
              Une conversation,
              <br />
              pas un <span className="italic text-jenny-coral">formulaire.</span>
            </h2>
            <p className="text-[15.5px] leading-[1.6] text-[#F4F1ED]/60 mb-8 max-w-[440px]">
              Le client écrit comme à un ami. Jenny comprend l&apos;intention, vérifie le stock,
              et conclut la vente — en quelques secondes.
            </p>
            <ul className="space-y-3.5">
              {[
                { t: "Comprend", d: "l'intention réelle derrière le message" },
                { t: "Agit", d: "vérifie le stock, prépare le lien de paiement" },
                { t: "Conclut", d: "sans formulaire, sans attente, 24/7" },
              ].map((s) => (
                <li key={s.t} className="flex items-start gap-3">
                  <span
                    className="mt-0.5 w-6 h-6 rounded-full flex items-center justify-center text-jenny-coral shrink-0"
                    style={{ background: "rgba(255,127,106,0.14)" }}
                  >
                    <Check className="w-3.5 h-3.5" />
                  </span>
                  <span className="text-[14.5px] text-[#F4F1ED]/85">
                    <b className="font-semibold text-white">{s.t}</b> — {s.d}
                  </span>
                </li>
              ))}
            </ul>
          </motion.div>

          {/* carte chat */}
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-60px" }}
            transition={{ duration: 0.55, delay: 0.1 }}
            className="relative rounded-[24px] p-6 md:p-8"
            style={{
              background: "linear-gradient(180deg, rgba(255,127,106,0.08) 0%, rgba(255,255,255,0.02) 100%)",
              border: "1px solid rgba(255,255,255,0.08)",
              boxShadow: "0 40px 120px rgba(255,127,106,0.14)",
            }}
          >
            <div className="flex items-center gap-2.5 mb-5 pb-4 border-b border-white/[0.07]">
              <JennyAvatar size={30} tone="dark" />
              <div>
                <div className="text-[13.5px] font-semibold text-white">Jenny</div>
                <div className="text-[11px] text-jenny-success font-mono flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-jenny-success inline-block" /> en ligne
                </div>
              </div>
            </div>
            <div className="flex flex-col gap-2.5" role="group" aria-label="Exemple de conversation avec Jenny">
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
                aria-hidden
                className="self-start px-3.5 py-2 rounded-full flex gap-1.5 mt-1"
                style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
              >
                {[0, 1, 2].map((i) => (
                  <motion.span
                    key={i}
                    className="w-1.5 h-1.5 rounded-full bg-jenny-coral"
                    style={reduce ? { opacity: 0.6 } : undefined}
                    animate={reduce ? undefined : { opacity: [0.3, 1, 0.3] }}
                    transition={reduce ? undefined : { duration: 1.2, repeat: Infinity, delay: i * 0.2 }}
                  />
                ))}
              </div>
            </div>
          </motion.div>
        </div>
      </section>

      {/* features */}
      <section
        id="produit"
        className="px-6 md:px-16 py-16 md:py-20 scroll-mt-20"
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

      {/* tarifs */}
      <section id="tarifs" className="px-6 md:px-16 py-16 md:py-20 scroll-mt-20">
        <div className="max-w-[1100px] mx-auto">
          <div className="font-mono text-[11px] tracking-[0.32em] uppercase text-jenny-coral mb-[18px]">
            — tarifs —
          </div>
          <h2 className="font-display text-[40px] md:text-[64px] leading-[1.05] tracking-[-0.02em] mb-12 md:mb-16 max-w-[800px]">
            Essayez, puis <span className="italic text-jenny-coral">décidez.</span>
          </h2>
          <div
            className="max-w-[480px] rounded-[20px] p-8"
            style={{
              background: "linear-gradient(180deg, rgba(255,127,106,0.10) 0%, rgba(255,255,255,0.02) 100%)",
              border: "1px solid rgba(255,127,106,0.20)",
            }}
          >
            <div className="font-mono text-[11px] tracking-[0.18em] uppercase text-jenny-coral mb-3">
              Essai
            </div>
            <div className="flex items-baseline gap-2 mb-1">
              <span className="font-display text-[56px] leading-none">14 jours</span>
              <span className="text-[17px] text-[#F4F1ED]/55">gratuits</span>
            </div>
            <p className="text-[14px] text-[#F4F1ED]/55 mb-6">
              Sans carte bancaire. Tous les canaux, toutes les fonctions. Annulez en un clic.
            </p>
            <ul className="space-y-2.5 mb-7">
              {[
                "WhatsApp, Instagram & email illimités",
                "Réservations & agenda automatiques",
                "Votre ton, votre catalogue, vos règles",
                "Hébergement en France · RGPD",
              ].map((f) => (
                <li key={f} className="flex items-center gap-2.5 text-[14px] text-[#F4F1ED]/80">
                  <Check className="w-4 h-4 text-jenny-coral shrink-0" />
                  {f}
                </li>
              ))}
            </ul>
            <Link
              href={ctaHref}
              className="btn-fluffy h-[50px] w-full text-[15px] font-semibold inline-flex items-center justify-center gap-2 bg-jenny-coral text-white hover:bg-jenny-coral-dark"
            >
              Commencer gratuitement
              <ArrowRight className="w-4 h-4" />
            </Link>
            <p className="text-[12.5px] text-[#F4F1ED]/45 mt-4 text-center">
              Une question sur le tarif après l&apos;essai ?{" "}
              <a href="mailto:azsay12@gmail.com?subject=Tarifs%20Jenny" className="text-jenny-coral hover:underline">
                Écrivez-nous
              </a>
            </p>
          </div>
        </div>
      </section>

      {/* faq */}
      <section
        id="faq"
        className="px-6 md:px-16 py-16 md:py-20 scroll-mt-20"
        style={{
          background: "rgba(255,255,255,0.02)",
          borderTop: "1px solid rgba(255,255,255,0.05)",
          borderBottom: "1px solid rgba(255,255,255,0.05)",
        }}
      >
        <div className="max-w-[820px] mx-auto">
          <div className="font-mono text-[11px] tracking-[0.32em] uppercase text-jenny-coral mb-[18px]">
            — questions fréquentes —
          </div>
          <h2 className="font-display text-[40px] md:text-[56px] leading-[1.05] tracking-[-0.02em] mb-12">
            Tout ce qu&apos;il faut <span className="italic text-jenny-coral">savoir.</span>
          </h2>
          <div className="divide-y divide-white/[0.07]">
            {[
              {
                q: "Sur quels canaux Jenny répond-elle ?",
                a: "WhatsApp, Instagram et email — gérés depuis un seul tableau de bord. Vous gardez la main : Jenny vous passe le relais quand c'est nécessaire.",
              },
              {
                q: "Est-ce que Jenny invente des réponses ?",
                a: "Non. Elle s'appuie sur votre catalogue et votre base de connaissances. Quand elle ne sait pas, elle propose de vérifier et vous remonte la question — plutôt que d'inventer.",
              },
              {
                q: "Mes données sont-elles en sécurité ?",
                a: "Hébergement en France, conforme RGPD. Vous pouvez exporter ou supprimer toutes les données d'un client à tout moment, en un clic.",
              },
              {
                q: "Combien de temps pour démarrer ?",
                a: "Quelques minutes : connectez vos canaux, renseignez vos prestations, choisissez le ton de Jenny — et elle commence à répondre.",
              },
            ].map((item) => (
              <div key={item.q} className="py-6">
                <h3 className="text-[18px] font-semibold mb-2 tracking-[-0.01em]">{item.q}</h3>
                <p className="text-[14.5px] leading-[1.6] text-[#F4F1ED]/60">{item.a}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* cta final */}
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
          className="btn-fluffy h-[58px] px-9 text-[16px] font-semibold inline-flex items-center gap-2 bg-jenny-coral text-white hover:bg-jenny-coral-dark"
        >
          Activer Jenny maintenant
          <ArrowRight className="w-[18px] h-[18px]" />
        </Link>
      </section>

      {/* footer */}
      <footer
        className="px-6 md:px-16 py-8 flex flex-wrap gap-3 items-center justify-between"
        style={{ borderTop: "1px solid rgba(255,255,255,0.05)" }}
      >
        <span className="text-[11px] text-[#F4F1ED]/40 font-mono tracking-[0.08em]">
          © 2026 Jenny — Hébergé en France · RGPD
        </span>
        <div className="flex gap-5 text-[12.5px] text-[#F4F1ED]/50">
          <Link href="/confidentialite" className="hover:text-[#F4F1ED]/80 transition-colors">
            Confidentialité
          </Link>
          <Link href="/conditions" className="hover:text-[#F4F1ED]/80 transition-colors">
            Conditions
          </Link>
          <a
            href="mailto:azsay12@gmail.com?subject=Contact%20Jenny"
            className="hover:text-[#F4F1ED]/80 transition-colors"
          >
            Contact
          </a>
        </div>
      </footer>
    </div>
  );
}

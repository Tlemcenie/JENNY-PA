"use client";

import Link from "next/link";
import Image from "next/image";
import { motion } from "framer-motion";
import { ArrowRight, Home, LayoutDashboard } from "lucide-react";
import { easeOutExpo } from "@/lib/motion";

export default function NotFound() {
  return (
    <main className="h-full min-h-[60vh] flex items-center justify-center bg-jenny-bg p-6">
      <motion.div
        className="text-center max-w-md"
        initial="hidden"
        animate="show"
        variants={{
          hidden: {},
          show: { transition: { staggerChildren: 0.08, delayChildren: 0.04 } },
        }}
      >
        {/* Mascotte */}
        <motion.div
          variants={{
            hidden: { opacity: 0, scale: 0.9, y: 8 },
            show: {
              opacity: 1,
              scale: 1,
              y: 0,
              transition: { duration: 0.5, ease: easeOutExpo },
            },
          }}
          className="mx-auto mb-6 w-24 h-24 rounded-3xl bg-jenny-surface border border-jenny-divider overflow-hidden flex items-center justify-center shadow-sm"
        >
          <Image
            src="/jenny.png"
            alt="Jenny"
            width={96}
            height={96}
            priority
            className="object-cover w-full h-full"
          />
        </motion.div>

        {/* Eyebrow */}
        <motion.div
          variants={{
            hidden: { opacity: 0, y: 8 },
            show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: easeOutExpo } },
          }}
          className="font-mono text-[11px] tracking-[0.22em] uppercase text-jenny-coral mb-3"
        >
          — Erreur 404 —
        </motion.div>

        {/* Titre */}
        <motion.h1
          variants={{
            hidden: { opacity: 0, y: 12 },
            show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: easeOutExpo } },
          }}
          className="font-display text-[clamp(30px,5vw,44px)] leading-[1.05] tracking-[-0.02em] text-jenny-text"
        >
          Page <span className="italic text-jenny-coral">introuvable.</span>
        </motion.h1>

        {/* Texte secondaire */}
        <motion.p
          variants={{
            hidden: { opacity: 0, y: 10 },
            show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: easeOutExpo } },
          }}
          className="text-[0.95rem] text-jenny-text-secondary mt-3 mb-7 leading-relaxed"
        >
          Cette page n&apos;existe pas ou a été déplacée. Revenons à votre espace de travail.
        </motion.p>

        {/* Actions */}
        <motion.div
          variants={{
            hidden: { opacity: 0, y: 10 },
            show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: easeOutExpo } },
          }}
          className="flex flex-wrap items-center justify-center gap-2.5"
        >
          <Link
            href="/dashboard"
            className="group inline-flex items-center gap-2 h-11 px-5 rounded-xl bg-jenny-coral text-white text-[14px] font-semibold shadow-sm shadow-jenny-coral/20 hover:bg-jenny-coral-dark active:scale-[0.98] transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-jenny-coral/30 focus-visible:ring-offset-2 focus-visible:ring-offset-jenny-bg"
          >
            <LayoutDashboard className="w-4 h-4" />
            Tableau de bord
            <ArrowRight className="w-4 h-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
          <Link
            href="/"
            className="inline-flex items-center gap-2 h-11 px-5 rounded-xl border border-jenny-divider bg-jenny-surface text-[14px] font-semibold text-jenny-text hover:border-jenny-text-secondary/30 active:scale-[0.98] transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-jenny-coral/30 focus-visible:ring-offset-2 focus-visible:ring-offset-jenny-bg"
          >
            <Home className="w-4 h-4 text-jenny-coral" />
            Accueil
          </Link>
        </motion.div>
      </motion.div>
    </main>
  );
}

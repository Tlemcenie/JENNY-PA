"use client";

import { motion } from "framer-motion";
import { Cpu } from "lucide-react";
import { LlmSwitcher } from "@/components/layout/llm-switcher";
import { fadeInUp } from "@/lib/motion";

// ── Bloc « Cerveau plateforme » : réglage GLOBAL du moteur d'IA de Jenny
// (Ollama / Groq / NanoGPT). Réutilise tel quel le composant LlmSwitcher
// (endpoints /settings/llm réels, déjà branchés). Ici on l'expose côté admin
// avec un libellé explicite : ce choix s'applique à toute la plateforme.

export function PlatformBrainCard() {
  return (
    <motion.div
      variants={fadeInUp}
      initial="hidden"
      animate="show"
      className="rounded-[20px] p-5"
      style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}
    >
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <span
          className="w-11 h-11 rounded-[12px] flex items-center justify-center text-jenny-coral shrink-0"
          style={{ background: "rgba(255,127,106,0.12)" }}
        >
          <Cpu className="w-5 h-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[15px] font-semibold tracking-[-0.01em]">Cerveau plateforme</div>
          <p className="text-[13px] text-[#F4F1ED]/55 leading-snug mt-0.5">
            Moteur d&apos;IA qui répond aux clients, pour toute la plateforme. Le choix s&apos;applique
            immédiatement et globalement.
          </p>
        </div>
        {/* Le sélecteur réel (Ollama / Groq / NanoGPT) — endpoints /settings/llm. */}
        <div className="shrink-0">
          <LlmSwitcher />
        </div>
      </div>
    </motion.div>
  );
}

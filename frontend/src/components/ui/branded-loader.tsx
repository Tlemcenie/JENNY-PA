"use client";

import { motion } from "framer-motion";
import { JennyAvatar } from "@/components/ui/jenny-avatar";

// Loader brandé, calme et élégant (esprit Claude/Anthropic) : la mascotte
// « respire » au centre d'un halo doux qui pulse, puis trois points discrets.
// Pas de spinner agressif — un chargement posé et chaleureux.
export function BrandedLoader({ label = "Un instant…" }: { label?: string }) {
  return (
    <div className="h-full w-full flex items-center justify-center bg-jenny-bg">
      <div className="flex flex-col items-center gap-6">
        <div className="relative">
          {/* Halo corail qui respire */}
          <motion.span
            aria-hidden
            className="absolute inset-0 rounded-full bg-jenny-coral/25 blur-2xl"
            animate={{ scale: [1, 1.4, 1], opacity: [0.45, 0.8, 0.45] }}
            transition={{ duration: 2.4, ease: "easeInOut", repeat: Infinity }}
          />
          {/* Mascotte qui respire doucement */}
          <motion.div
            className="relative"
            animate={{ scale: [1, 1.06, 1], y: [0, -3, 0] }}
            transition={{ duration: 2.4, ease: "easeInOut", repeat: Infinity }}
          >
            <JennyAvatar size={66} tone="light" priority className="shadow-lg shadow-jenny-coral/20" />
          </motion.div>
        </div>

        {/* Trois points qui s'allument tour à tour */}
        <div className="flex items-center gap-1.5" aria-hidden>
          {[0, 1, 2].map((i) => (
            <motion.span
              key={i}
              className="w-1.5 h-1.5 rounded-full bg-jenny-coral/60"
              animate={{ opacity: [0.2, 1, 0.2] }}
              transition={{ duration: 1.2, ease: "easeInOut", repeat: Infinity, delay: i * 0.18 }}
            />
          ))}
        </div>

        {label && (
          <p className="text-jenny-text-secondary text-[13px] tracking-wide">{label}</p>
        )}
      </div>
    </div>
  );
}

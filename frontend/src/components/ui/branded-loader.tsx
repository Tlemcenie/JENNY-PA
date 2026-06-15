"use client";

import { motion } from "framer-motion";

// Loader brandé : logo « J » qui pulse à l'intérieur d'un anneau qui tourne.
export function BrandedLoader({ label = "Chargement..." }: { label?: string }) {
  return (
    <div className="h-full w-full flex items-center justify-center bg-jenny-bg">
      <div className="flex flex-col items-center gap-5">
        <div className="relative w-14 h-14">
          <motion.span
            className="absolute inset-0 rounded-2xl border-2 border-jenny-coral/20 border-t-jenny-coral"
            animate={{ rotate: 360 }}
            transition={{ duration: 0.9, ease: "linear", repeat: Infinity }}
          />
          <motion.div
            className="absolute inset-[5px] rounded-xl bg-jenny-coral flex items-center justify-center shadow-sm shadow-jenny-coral/25"
            animate={{ scale: [1, 0.9, 1] }}
            transition={{ duration: 1.4, ease: "easeInOut", repeat: Infinity }}
          >
            <span className="text-white font-bold text-lg">J</span>
          </motion.div>
        </div>
        {label && <p className="text-jenny-text-secondary text-sm">{label}</p>}
      </div>
    </div>
  );
}

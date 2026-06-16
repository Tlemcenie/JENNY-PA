"use client";

import { motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";
import { staggerContainer, staggerItem } from "@/lib/motion";

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

/**
 * État vide partagé — apparition douce en cascade (icône → titre → texte →
 * action), neutralisée sous prefers-reduced-motion. Réutilisé par les pages
 * métier (connaissances, prestations, calendrier…) pour un « vide » premium.
 */
export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  const reduce = useReducedMotion();

  return (
    <motion.div
      variants={staggerContainer}
      initial={reduce ? false : "hidden"}
      animate="show"
      className={cn("flex flex-col items-center justify-center py-16 px-4 text-center", className)}
    >
      {icon && (
        <motion.div
          variants={staggerItem}
          className="w-16 h-16 rounded-2xl bg-jenny-divider/50 flex items-center justify-center text-jenny-text-secondary mb-4"
        >
          {icon}
        </motion.div>
      )}
      <motion.h3 variants={staggerItem} className="text-lg font-semibold text-jenny-text mb-1">
        {title}
      </motion.h3>
      {description && (
        <motion.p variants={staggerItem} className="text-sm text-jenny-text-secondary max-w-sm">
          {description}
        </motion.p>
      )}
      {action && (
        <motion.div variants={staggerItem} className="mt-4">
          {action}
        </motion.div>
      )}
    </motion.div>
  );
}

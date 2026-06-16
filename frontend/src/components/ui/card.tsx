"use client";

import { motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";
import { springSoft } from "@/lib/motion";

interface CardProps {
  children: React.ReactNode;
  className?: string;
  hover?: boolean;
  onClick?: () => void;
}

export function Card({ children, className, hover, onClick }: CardProps) {
  const reduce = useReducedMotion();

  // Lift premium piloté par un spring (springSoft) au lieu du translate CSS
  // statique. Neutralisé proprement en mode mouvement réduit, et seulement
  // quand `hover` est demandé. Les classes/props publiques restent identiques.
  const lift = hover && !reduce ? { whileHover: { y: -2 }, transition: springSoft } : {};

  return (
    <motion.div
      className={cn(
        "bg-jenny-surface rounded-2xl border border-jenny-divider p-6",
        "transition-colors duration-200",
        hover && "hover:shadow-md hover:border-jenny-coral/20 cursor-pointer",
        onClick &&
          "cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-jenny-coral/40 focus-visible:ring-offset-2 focus-visible:ring-offset-jenny-bg",
        className
      )}
      onClick={onClick}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      {...lift}
    >
      {children}
    </motion.div>
  );
}

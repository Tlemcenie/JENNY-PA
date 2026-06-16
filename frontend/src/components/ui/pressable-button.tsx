"use client";

import { forwardRef } from "react";
import { motion, useReducedMotion, type HTMLMotionProps } from "framer-motion";
import { cn } from "@/lib/utils";
import { springSnappy } from "@/lib/motion";

// Drop-in du `Button` existant (mêmes variants / sizes / isLoading), enrichi
// d'une micro-interaction « pressable » : léger lift au survol + écrasement au
// clic (springSnappy). Désactivé proprement quand `prefers-reduced-motion`.
//
// On garde `button.tsx` intact : utiliser PressableButton là où l'on veut le
// ressenti tactile premium, le Button classique partout ailleurs.

type MotionButtonProps = HTMLMotionProps<"button">;

// On part des props natives de <motion.button> (qui incluent déjà disabled,
// onClick, type, etc.) et on y ajoute l'API publique du Button. On exclut les
// handlers d'animation que framer pilote lui-même (whileHover/whileTap/transition)
// pour qu'ils ne soient pas surchargés par l'appelant.
interface PressableButtonProps
  extends Omit<MotionButtonProps, "whileHover" | "whileTap" | "transition"> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  isLoading?: boolean;
  className?: string;
  children?: React.ReactNode;
}

const PressableButton = forwardRef<HTMLButtonElement, PressableButtonProps>(
  (
    { className, variant = "primary", size = "md", isLoading, disabled, children, ...props },
    ref
  ) => {
    const reduce = useReducedMotion();

    const base =
      "inline-flex items-center justify-center font-semibold rounded-xl transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-jenny-coral/30 focus-visible:ring-offset-2 disabled:opacity-40 disabled:pointer-events-none select-none";

    const variants = {
      primary:
        "bg-jenny-coral text-white hover:bg-jenny-coral-dark shadow-sm shadow-jenny-coral/20 hover:shadow-md hover:shadow-jenny-coral/25",
      secondary:
        "bg-white text-jenny-text border border-jenny-divider hover:bg-jenny-bg hover:border-jenny-text-secondary/25",
      ghost:
        "text-jenny-text-secondary hover:text-jenny-text hover:bg-jenny-divider/40",
      danger: "bg-jenny-error text-white hover:bg-red-600",
    };

    const sizes = {
      sm: "h-9 px-3.5 text-[0.8125rem] gap-1.5",
      md: "h-10 px-4 text-[0.875rem] gap-2",
      lg: "h-12 px-5 text-[0.9375rem] gap-2",
    };

    const isDisabled = disabled || isLoading;
    // Pas de micro-interaction quand le bouton est inactif ou en mode mouvement réduit.
    const motionProps =
      reduce || isDisabled
        ? {}
        : {
            whileHover: { y: -1 },
            whileTap: { scale: 0.97 },
            transition: springSnappy,
          };

    return (
      <motion.button
        ref={ref}
        className={cn(base, variants[variant], sizes[size], className)}
        disabled={isDisabled}
        {...motionProps}
        {...props}
      >
        {isLoading && (
          <svg className="animate-spin h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            />
          </svg>
        )}
        {children}
      </motion.button>
    );
  }
);

PressableButton.displayName = "PressableButton";
export { PressableButton };

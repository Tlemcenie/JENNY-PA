"use client";

import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  isLoading?: boolean;
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "md", isLoading, disabled, children, ...props }, ref) => {
    const base =
      "inline-flex items-center justify-center font-semibold rounded-xl transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-jenny-coral/30 focus-visible:ring-offset-2 disabled:opacity-40 disabled:pointer-events-none select-none";

    const variants = {
      primary:
        "bg-jenny-coral text-white hover:bg-jenny-coral-dark shadow-sm shadow-jenny-coral/20 hover:shadow-md hover:shadow-jenny-coral/25 active:scale-[0.98]",
      secondary:
        "bg-white text-jenny-text border border-jenny-divider hover:bg-jenny-bg hover:border-jenny-text-secondary/25 active:scale-[0.98]",
      ghost:
        "text-jenny-text-secondary hover:text-jenny-text hover:bg-jenny-divider/40",
      danger:
        "bg-jenny-error text-white hover:bg-red-600 active:scale-[0.98]",
    };

    const sizes = {
      sm: "h-9 px-3.5 text-[0.8125rem] gap-1.5",
      md: "h-10 px-4 text-[0.875rem] gap-2",
      lg: "h-12 px-5 text-[0.9375rem] gap-2",
    };

    return (
      <button
        ref={ref}
        className={cn(base, variants[variant], sizes[size], className)}
        disabled={disabled || isLoading}
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
      </button>
    );
  }
);

Button.displayName = "Button";
export { Button };

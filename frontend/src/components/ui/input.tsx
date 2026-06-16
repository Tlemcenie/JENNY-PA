"use client";

import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  icon?: ReactNode;
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, error, icon, id, ...props }, ref) => {
    const inputId = id || label?.toLowerCase().replace(/\s/g, "-");

    return (
      <div className="flex flex-col gap-2">
        {label && (
          <label htmlFor={inputId} className="text-[0.8125rem] font-semibold text-jenny-text">
            {label}
          </label>
        )}
        <div className="relative">
          {icon && (
            <div className="absolute left-3.5 top-1/2 -translate-y-1/2 text-jenny-text-secondary/60">
              {icon}
            </div>
          )}
          <input
            ref={ref}
            id={inputId}
            className={cn(
              "w-full h-12 pr-4 rounded-xl bg-jenny-surface border text-[0.9375rem] text-jenny-text",
              icon ? "pl-11" : "pl-4",
              "placeholder:text-jenny-text-secondary/50",
              "transition-all duration-150",
              "focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral",
              "hover:border-jenny-text-secondary/30",
              error
                ? "border-jenny-error focus:ring-jenny-error/20"
                : "border-jenny-divider",
              className
            )}
            {...props}
          />
        </div>
        {error && <p className="text-[0.8125rem] text-jenny-error leading-snug">{error}</p>}
      </div>
    );
  }
);

Input.displayName = "Input";
export { Input };

"use client";

import { cn } from "@/lib/utils";

/**
 * Switch « premium / soft UI » — capsule très arrondie, fond beige/blanc cassé,
 * bouton mobile circulaire à l'accent lavande, ombre douce sous le bouton, et
 * micro-interactions fluides (slide à la bascule, lift au survol, légère
 * compression au clic). Pensé clair ET sombre, desktop + mobile, accessible
 * (role="switch", clavier natif). Aucune bordure lourde, beaucoup d'air.
 */

interface SwitchProps {
  checked: boolean;
  onCheckedChange: (value: boolean) => void;
  disabled?: boolean;
  size?: "sm" | "md";
  id?: string;
  className?: string;
  "aria-label"?: string;
}

const SIZES = {
  sm: { trackW: 38, trackH: 22, knob: 16, pad: 3 },
  md: { trackW: 48, trackH: 28, knob: 22, pad: 3 },
};

export function Switch({
  checked,
  onCheckedChange,
  disabled = false,
  size = "md",
  id,
  className,
  ...rest
}: SwitchProps) {
  const s = SIZES[size];
  const travel = s.trackW - s.knob - s.pad * 2;

  return (
    <button
      type="button"
      role="switch"
      id={id}
      aria-checked={checked}
      aria-label={rest["aria-label"]}
      disabled={disabled}
      onClick={() => !disabled && onCheckedChange(!checked)}
      className={cn(
        "group relative inline-flex shrink-0 items-center rounded-full outline-none",
        "transition-[background-color,box-shadow] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
        "focus-visible:ring-2 focus-visible:ring-[#A78BFA]/45 focus-visible:ring-offset-2 focus-visible:ring-offset-transparent",
        disabled ? "opacity-45 cursor-not-allowed" : "cursor-pointer",
        // Piste : beige/blanc cassé éteint → lavande très doux allumé (clair & sombre)
        checked
          ? "bg-[#E9E1FB] dark:bg-[#322A4A]"
          : "bg-[#ECE6DC] dark:bg-[#2A2A32]",
        className
      )}
      style={{
        width: s.trackW,
        height: s.trackH,
        // Liseré interne ultra-léger (définition sans bordure lourde)
        boxShadow: checked
          ? "inset 0 0 0 1px rgba(124,92,246,0.18)"
          : "inset 0 0 0 1px rgba(0,0,0,0.05)",
      }}
    >
      {/* Position du bouton (slide) */}
      <span
        className="absolute top-1/2 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
        style={{
          left: s.pad,
          width: s.knob,
          height: s.knob,
          transform: `translateY(-50%) translateX(${checked ? travel : 0}px)`,
        }}
      >
        {/* Bouton mobile (couleur + ombre douce + micro-interactions) */}
        <span
          className={cn(
            "block h-full w-full rounded-full",
            "transition-[background-color,box-shadow,transform] duration-200 ease-out",
            "group-hover:scale-[1.07] group-active:scale-90",
            checked ? "bg-[#A78BFA]" : "bg-white dark:bg-[#5A5A68]"
          )}
          style={{
            boxShadow: checked
              ? "0 4px 10px rgba(124,92,246,0.45), 0 1px 2px rgba(0,0,0,0.10)"
              : "0 2px 5px rgba(0,0,0,0.18), 0 1px 1px rgba(0,0,0,0.06)",
          }}
        />
      </span>
    </button>
  );
}

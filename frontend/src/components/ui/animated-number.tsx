"use client";

import { useEffect, useRef, useState } from "react";
import { animate, useReducedMotion } from "framer-motion";
import { easeOutExpo } from "@/lib/motion";

interface AnimatedNumberProps {
  value: number;
  duration?: number;
  // Formatage optionnel (euros, %, séparateurs de milliers…)
  format?: (n: number) => string;
}

// Compteur animé : la valeur « grimpe » de l'ancienne valeur vers la nouvelle.
// Respecte `prefers-reduced-motion` (affichage instantané le cas échéant).
export function AnimatedNumber({ value, duration = 0.9, format }: AnimatedNumberProps) {
  const reduce = useReducedMotion();
  const [display, setDisplay] = useState(0);
  const fromRef = useRef(0);

  useEffect(() => {
    if (reduce) return;
    const controls = animate(fromRef.current, value, {
      duration,
      ease: easeOutExpo,
      onUpdate: (v) => setDisplay(v),
    });
    fromRef.current = value;
    return () => controls.stop();
  }, [value, duration, reduce]);

  // En mode « mouvement réduit », on affiche la valeur finale sans animation.
  const shown = reduce ? value : display;
  return <>{format ? format(shown) : Math.round(shown).toLocaleString("fr-FR")}</>;
}

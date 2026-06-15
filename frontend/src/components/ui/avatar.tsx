"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

// Palette de couleurs « clients » — couleur déterministe par nom/email, pour
// reconnaître un client d'un coup d'œil (toujours la même teinte).
const PALETTE = [
  "#FF7F6A",
  "#3B82F6",
  "#8B5CF6",
  "#10B981",
  "#F59E0B",
  "#EC4899",
  "#14B8A6",
  "#6366F1",
  "#EF4444",
  "#0EA5E9",
];

function hashString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

export function initials(name?: string | null, fallback?: string | null): string {
  const src = (name || fallback || "?").trim();
  const parts = src.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return src.slice(0, 2).toUpperCase();
}

async function sha256Hex(input: string): Promise<string> {
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

interface AvatarProps {
  name?: string | null;
  email?: string | null;
  /** Utilise le dégradé de marque au lieu d'une couleur déterministe. */
  gradient?: boolean;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const SIZES = {
  sm: "w-9 h-9 text-xs",
  md: "w-11 h-11 text-sm",
  lg: "w-12 h-12 text-base",
};

const PX = { sm: 36, md: 44, lg: 48 };

export function Avatar({ name, email, gradient, size = "md", className }: AvatarProps) {
  const seed = (name || email || "?").toLowerCase();
  const color = PALETTE[hashString(seed) % PALETTE.length];

  // Photo Gravatar (#11) : on tente le hash SHA-256 de l'email (supporté par
  // Gravatar au même titre que MD5, sans dépendance — via Web Crypto natif).
  // `d=404` → Gravatar renvoie 404 si le client n'a pas de photo, et on
  // retombe alors proprement sur les initiales colorées.
  const [gravatar, setGravatar] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    const addr = (email || "").trim().toLowerCase();
    if (!addr || gradient) {
      // Reset différé (microtask) pour ne pas appeler setState de façon
      // synchrone dans le corps de l'effet (cascade de rendus).
      queueMicrotask(() => {
        if (!active) return;
        setGravatar(null);
        setFailed(false);
      });
      return () => {
        active = false;
      };
    }
    sha256Hex(addr)
      .then((hex) => {
        if (!active) return;
        setGravatar(`https://www.gravatar.com/avatar/${hex}?d=404&s=${PX[size] * 2}`);
        setFailed(false);
      })
      .catch(() => {
        if (active) setGravatar(null);
      });
    return () => {
      active = false;
    };
  }, [email, gradient, size]);

  if (gravatar && !failed) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={gravatar}
        alt={name || email || "Client"}
        width={PX[size]}
        height={PX[size]}
        onError={() => setFailed(true)}
        className={cn("rounded-2xl object-cover shrink-0 select-none", SIZES[size], className)}
      />
    );
  }

  return (
    <span
      className={cn(
        "rounded-2xl text-white flex items-center justify-center font-semibold shrink-0 select-none",
        SIZES[size],
        gradient && "bg-brand-gradient",
        className
      )}
      style={gradient ? undefined : { backgroundColor: color }}
      aria-hidden="true"
    >
      {initials(name, email)}
    </span>
  );
}

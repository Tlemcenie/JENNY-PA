"use client";

import { useId } from "react";
import { MessageCircle, AtSign, Mail, Globe, Sparkles, Check } from "lucide-react";

/**
 * Primitives visuelles de la refonte « JENNY Front » (handoff design).
 * Reproduisent jenny-shared.jsx (MiniSpark, Avatar, ChannelChip, ChannelAvatar,
 * badges de statut) avec les tokens de l'app. À utiliser dans un conteneur `.jx`.
 */

// ── Sparkline (aire + trait) ──────────────────────────────────────────────
export function MiniSpark({
  values,
  color = "var(--coral)",
  width = 100,
  height = 28,
}: {
  values: number[];
  color?: string;
  width?: number;
  height?: number;
}) {
  const gid = useId();
  if (!values || values.length < 2) {
    return <div style={{ width, height }} />;
  }
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = Math.max(1, max - min);
  const path = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width;
      const y = height - ((v - min) / range) * (height - 4) - 2;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <defs>
        <linearGradient id={gid} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${path} L${width},${height} L0,${height} Z`} fill={`url(#${gid})`} />
      <path
        d={path}
        stroke={color}
        strokeWidth="1.6"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// ── Avatar initiales (couleur dérivée du nom) ─────────────────────────────
const AV_COLORS = ["#FF7F6A", "#7284A8", "#10B981", "#F59E0B", "#3B82F6", "#A855F7", "#EC4899"];

export function InitialsAvatar({
  name,
  size = 36,
  color,
}: {
  name: string;
  size?: number;
  color?: string;
}) {
  const safe = name?.trim() || "?";
  const initials = safe
    .split(/\s+/)
    .map((s) => s[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  const c = color || AV_COLORS[safe.charCodeAt(0) % AV_COLORS.length];
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        background: c,
        color: "white",
        fontWeight: 600,
        fontSize: size * 0.36,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}
    >
      {initials}
    </div>
  );
}

// ── Canal : métadonnées partagées ─────────────────────────────────────────
type Channel = "whatsapp" | "instagram" | "email" | "twitter" | string;

const CH_META: Record<string, { cls: string; label: string; color: string; Icon: typeof Mail }> = {
  whatsapp: { cls: "jchip--wa", label: "WhatsApp", color: "#25D366", Icon: MessageCircle },
  instagram: { cls: "jchip--ig", label: "Instagram", color: "#E4405F", Icon: AtSign },
  email: { cls: "jchip--em", label: "Email", color: "#3B82F6", Icon: Mail },
  twitter: { cls: "jchip--tw", label: "Twitter", color: "#1DA1F2", Icon: Globe },
};

function chMeta(ch: Channel) {
  return CH_META[ch] || CH_META.email;
}

export function ChannelChip({ ch }: { ch: Channel }) {
  const m = chMeta(ch);
  return (
    <span className={`jchip ${m.cls}`}>
      <span className="dot" />
      {m.label}
    </span>
  );
}

export function ChannelAvatar({ name, ch, size = 40 }: { name: string; ch: Channel; size?: number }) {
  const m = chMeta(ch);
  const Icon = m.Icon;
  return (
    <div className="jchav" style={{ width: size, height: size }}>
      <InitialsAvatar name={name} size={size} />
      <span className="badge-ch" style={{ background: m.color }}>
        <Icon style={{ width: 9, height: 9, color: "#fff" }} />
      </span>
    </div>
  );
}

// ── Badge de statut de conversation ───────────────────────────────────────
export function StatusBadge({ status }: { status: "jenny" | "human" | "resolved" | string }) {
  if (status === "jenny")
    return (
      <span className="jbadge jbadge--coral">
        <Sparkles style={{ width: 10, height: 10 }} />
        JENNY
      </span>
    );
  if (status === "human") return <span className="jbadge jbadge--warn">→ VOUS</span>;
  if (status === "resolved")
    return (
      <span className="jbadge jbadge--mint">
        <Check style={{ width: 10, height: 10 }} />
        RÉSOLU
      </span>
    );
  return null;
}

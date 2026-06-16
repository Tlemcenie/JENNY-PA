"use client";

import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import {
  AtSign,
  Camera,
  Check,
  Globe,
  Mail,
  MessageCircle,
  MessageSquare,
  Send,
} from "lucide-react";
import { listChannels, type ChannelStatus } from "@/lib/api";

/**
 * Page « Intégrations » — refonte fidèle à l'écran de design `ScreenIntegrations`.
 *
 * Le contenu (état de connexion, libellé, compte) provient en totalité de
 * l'API réelle `GET /api/v1/channels` (cf. `listChannels`). Aucune intégration
 * « connectée » n'est inventée : on reflète exactement ce que le backend renvoie.
 * L'API ne suit pas (encore) de volume mensuel par canal, donc on n'affiche
 * pas de chiffre « ce mois » fictif — on s'en tient aux faits.
 *
 * Mise en page : on rend UNIQUEMENT la zone de contenu. La sidebar + la topbar
 * viennent de `(dashboard)/layout.tsx`.
 */

// Présentation par canal : icône lucide (pas d'icône de marque dans cette
// version → icône générique colorée à la marque) + description métier.
const CHANNEL_PRESETS: Record<
  string,
  { icon: ReactNode; desc: string }
> = {
  whatsapp: {
    icon: <MessageCircle style={{ width: 32, height: 32, color: "#25D366" }} />,
    desc: "Recevoir et répondre aux messages WhatsApp via Meta Cloud API.",
  },
  instagram: {
    icon: <AtSign style={{ width: 32, height: 32, color: "#E4405F" }} />,
    desc: "DM Instagram + commentaires de posts, triés et traités par Jenny.",
  },
  messenger: {
    icon: <MessageSquare style={{ width: 32, height: 32, color: "#0084FF" }} />,
    desc: "Conversations Messenger reliées à votre page Facebook.",
  },
  twitter: {
    icon: <Globe style={{ width: 32, height: 32, color: "#1DA1F2" }} />,
    desc: "Messages privés et mentions. Surveillance de votre marque.",
  },
  snapchat: {
    icon: <Camera style={{ width: 32, height: 32, color: "#FFC700" }} />,
    desc: "Messages Snapchat de vos clients, centralisés au même endroit.",
  },
  email: {
    icon: <Mail style={{ width: 32, height: 32, color: "#3B82F6" }} />,
    desc: "Boîte e-mail reliée. Tri automatique par intention.",
  },
  form: {
    icon: <Send style={{ width: 32, height: 32, color: "#8B5CF6" }} />,
    desc: "Formulaire web de contact intégré à votre site, prêt à l'emploi.",
  },
};

// Repli pour un éventuel canal inconnu renvoyé par l'API.
const FALLBACK_PRESET = {
  icon: <Globe style={{ width: 32, height: 32, color: "#7284A8" }} />,
  desc: "Canal de messagerie connecté à Jenny.",
};

const ghostBtn: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  height: 32,
  padding: "0 14px",
  borderRadius: "var(--r-btn)",
  fontSize: 12.5,
  fontWeight: 600,
  fontFamily: "var(--font-sans)",
  background: "transparent",
  color: "var(--text)",
  border: "1px solid var(--divider)",
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const primaryBtn: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  height: 32,
  padding: "0 16px",
  borderRadius: "var(--r-btn)",
  fontSize: 12.5,
  fontWeight: 600,
  fontFamily: "var(--font-sans)",
  background: "var(--coral)",
  color: "#fff",
  border: "1px solid transparent",
  boxShadow: "var(--shadow-pop)",
  cursor: "pointer",
  whiteSpace: "nowrap",
};

function IntegrationCard({ channel }: { channel: ChannelStatus }) {
  const preset = CHANNEL_PRESETS[channel.channel] ?? FALLBACK_PRESET;
  // Méta mono : le compte réel s'il existe, sinon « Intégré nativement » pour
  // les canaux builtin (email / formulaire), sinon rien.
  const meta = channel.account ?? (channel.builtin ? "Intégré nativement" : null);

  return (
    <div className="jcard jlift" style={{ padding: 22, display: "flex", gap: 16 }}>
      <div
        style={{
          width: 56,
          height: 56,
          borderRadius: 14,
          background: "var(--bg)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        {preset.icon}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4, flexWrap: "wrap" }}>
          <span style={{ fontSize: 15, fontWeight: 600, color: "var(--text)" }}>{channel.label}</span>
          {channel.connected ? (
            <span className="jbadge jbadge--mint">
              <Check style={{ width: 10, height: 10 }} />
              CONNECTÉ
            </span>
          ) : (
            <span className="jbadge jbadge--slate">DISPONIBLE</span>
          )}
        </div>
        {meta && (
          <div
            className="jmono"
            style={{
              fontSize: 12,
              color: "var(--text-2)",
              marginBottom: 8,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {meta}
          </div>
        )}
        <div style={{ fontSize: 13, color: "var(--text-2)", lineHeight: 1.5, marginBottom: 14 }}>
          {preset.desc}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {channel.connected ? (
            <button type="button" className="jlift" style={ghostBtn}>
              Configurer
            </button>
          ) : (
            <button type="button" className="jlift" style={primaryBtn}>
              Connecter →
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function CardSkeleton() {
  return (
    <div className="jcard" style={{ padding: 22, display: "flex", gap: 16 }}>
      <div
        style={{
          width: 56,
          height: 56,
          borderRadius: 14,
          background: "var(--bg-tint)",
          flexShrink: 0,
        }}
        className="animate-pulse"
      />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          className="animate-pulse"
          style={{ height: 14, width: "55%", borderRadius: 6, background: "var(--bg-tint)", marginBottom: 10 }}
        />
        <div
          className="animate-pulse"
          style={{ height: 11, width: "40%", borderRadius: 6, background: "var(--bg-tint)", marginBottom: 12 }}
        />
        <div
          className="animate-pulse"
          style={{ height: 11, width: "90%", borderRadius: 6, background: "var(--bg-tint)", marginBottom: 14 }}
        />
        <div
          className="animate-pulse"
          style={{ height: 32, width: 110, borderRadius: "var(--r-btn)", background: "var(--bg-tint)" }}
        />
      </div>
    </div>
  );
}

export default function ChannelsPage() {
  const [channels, setChannels] = useState<ChannelStatus[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listChannels()
      .then(setChannels)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const connectedCount = channels.filter((c) => c.connected).length;

  return (
    <div className="jx h-full overflow-y-auto" style={{ background: "var(--bg)", padding: "28px 32px" }}>
      <h1
        className="jserif"
        style={{ fontSize: 40, lineHeight: 1, letterSpacing: "-0.02em", color: "var(--text)", margin: 0, marginBottom: 8 }}
      >
        Là où <span style={{ fontStyle: "italic", color: "var(--coral)" }}>Jenny travaille.</span>
      </h1>
      <p style={{ fontSize: 14, color: "var(--text-2)", marginBottom: 28, maxWidth: 560 }}>
        {connectedCount} intégration{connectedCount > 1 ? "s" : ""} active{connectedCount > 1 ? "s" : ""}.
        Connectez d&apos;autres canaux pour centraliser tous vos messages.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 14 }}>
        {loading
          ? Array.from({ length: 6 }).map((_, i) => <CardSkeleton key={i} />)
          : channels.map((c) => <IntegrationCard key={c.channel} channel={c} />)}
      </div>
    </div>
  );
}

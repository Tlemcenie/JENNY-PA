"use client";

import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";
import {
  AtSign,
  Camera,
  Check,
  Copy,
  Globe,
  Mail,
  MessageCircle,
  MessageSquare,
  Send,
  X,
} from "lucide-react";
import {
  connectChannel,
  disconnectChannel,
  getChannelFields,
  getChannelWebhookInfo,
  listChannels,
  testChannel,
  type ChannelFieldSpec,
  type ChannelStatus,
  type ChannelWebhookInfo,
} from "@/lib/api";

/**
 * Page « Intégrations » — état RÉEL des canaux + connexion/déconnexion réelle.
 *
 * `GET /api/v1/channels` donne l'état ; les boutons ouvrent un dialogue qui
 * récupère les champs attendus (`/channels/{c}/fields`), l'URL de webhook à
 * coller dans Meta (`/channels/{c}/webhook-info`), puis enregistre les
 * identifiants (`POST /channels/{c}/connect`), les teste (`POST .../test`) ou
 * les supprime (`DELETE`). Les identifiants sont chiffrés au repos côté API.
 * Tant qu'aucun identifiant n'est présent, le canal reçoit toujours (webhook)
 * mais l'envoi est désactivé — fallback gracieux, jamais d'erreur bloquante.
 */

const CHANNEL_PRESETS: Record<string, { icon: ReactNode; desc: string }> = {
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
    desc: "Boîte e-mail reliée (SMTP envoi + IMAP réception). Tri par intention.",
  },
  form: {
    icon: <Send style={{ width: 32, height: 32, color: "#8B5CF6" }} />,
    desc: "Formulaire web de contact intégré à votre site, prêt à l'emploi.",
  },
};

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

const inputStyle: CSSProperties = {
  width: "100%",
  height: 40,
  padding: "0 12px",
  borderRadius: 10,
  fontSize: 13.5,
  fontFamily: "var(--font-sans)",
  background: "var(--surface)",
  color: "var(--text)",
  border: "1px solid var(--divider)",
  outline: "none",
};

function CopyRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div style={{ marginBottom: 10 }}>
      <div className="jmono" style={{ fontSize: 11, color: "var(--text-2)", marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <code
          style={{
            flex: 1,
            minWidth: 0,
            fontSize: 12,
            padding: "8px 10px",
            borderRadius: 8,
            background: "var(--bg-tint)",
            color: "var(--text)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {value}
        </code>
        <button
          type="button"
          className="jlift"
          style={{ ...ghostBtn, height: 34, padding: "0 10px" }}
          onClick={() => {
            navigator.clipboard?.writeText(value).then(
              () => {
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              },
              () => {}
            );
          }}
        >
          {copied ? <Check style={{ width: 13, height: 13 }} /> : <Copy style={{ width: 13, height: 13 }} />}
          {copied ? "Copié" : "Copier"}
        </button>
      </div>
    </div>
  );
}

function ChannelDialog({
  channel,
  onClose,
  onSaved,
}: {
  channel: ChannelStatus;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [fields, setFields] = useState<ChannelFieldSpec[] | null>(null);
  const [webhook, setWebhook] = useState<ChannelWebhookInfo | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [displayName, setDisplayName] = useState(channel.account ?? "");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    getChannelFields(channel.channel).then(setFields).catch(() => setFields([]));
    getChannelWebhookInfo(channel.channel)
      .then(setWebhook)
      .catch(() => setWebhook(null));
  }, [channel.channel]);

  async function handleSave() {
    setSaving(true);
    setMsg(null);
    try {
      await connectChannel(channel.channel, {
        display_name: displayName || undefined,
        credentials: values,
      });
      onSaved();
      onClose();
    } catch (e) {
      const detail =
        (e as { data?: { detail?: string } })?.data?.detail || "Échec de l'enregistrement.";
      setMsg({ kind: "err", text: detail });
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    setMsg(null);
    try {
      const r = await testChannel(channel.channel);
      setMsg({ kind: r.ok ? "ok" : "err", text: r.detail });
    } catch {
      setMsg({ kind: "err", text: "Test impossible (enregistrez d'abord les identifiants)." });
    } finally {
      setTesting(false);
    }
  }

  async function handleDisconnect() {
    setSaving(true);
    setMsg(null);
    try {
      await disconnectChannel(channel.channel);
      onSaved();
      onClose();
    } catch {
      setMsg({ kind: "err", text: "Échec de la déconnexion." });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 60,
        background: "rgba(14,11,20,0.55)",
        backdropFilter: "blur(4px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="jcard"
        style={{
          width: "100%",
          maxWidth: 520,
          maxHeight: "88vh",
          overflowY: "auto",
          padding: 24,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
          <h2 className="jserif" style={{ fontSize: 26, margin: 0, color: "var(--text)" }}>
            Connecter <span style={{ fontStyle: "italic", color: "var(--coral)" }}>{channel.label}</span>
          </h2>
          <button type="button" onClick={onClose} style={{ ...ghostBtn, height: 32, padding: "0 8px", border: "none" }}>
            <X style={{ width: 18, height: 18 }} />
          </button>
        </div>
        <p style={{ fontSize: 13, color: "var(--text-2)", marginTop: 0, marginBottom: 18, lineHeight: 1.5 }}>
          {CHANNEL_PRESETS[channel.channel]?.desc ?? FALLBACK_PRESET.desc}
        </p>

        {/* Info webhook à coller dans Meta (WhatsApp/Instagram) */}
        {webhook && (
          <div
            style={{
              background: "var(--bg-tint)",
              border: "1px solid var(--divider)",
              borderRadius: 12,
              padding: 14,
              marginBottom: 18,
            }}
          >
            <CopyRow label="URL DU WEBHOOK" value={webhook.url} />
            {webhook.verify_token && <CopyRow label="VERIFY TOKEN" value={webhook.verify_token} />}
            {webhook.note && (
              <div style={{ fontSize: 11.5, color: "var(--text-2)", lineHeight: 1.5 }}>{webhook.note}</div>
            )}
          </div>
        )}

        {/* Nom affiché */}
        <label className="jmono" style={{ fontSize: 11, color: "var(--text-2)", display: "block", marginBottom: 4 }}>
          NOM AFFICHÉ (OPTIONNEL)
        </label>
        <input
          style={{ ...inputStyle, marginBottom: 14 }}
          value={displayName}
          placeholder="ex. Salon Néroli — WhatsApp"
          onChange={(e) => setDisplayName(e.target.value)}
        />

        {/* Champs d'identifiants par canal */}
        {fields === null ? (
          <div style={{ fontSize: 13, color: "var(--text-2)" }}>Chargement…</div>
        ) : (
          fields.map((f) => (
            <div key={f.key} style={{ marginBottom: 12 }}>
              <label
                className="jmono"
                style={{ fontSize: 11, color: "var(--text-2)", display: "block", marginBottom: 4 }}
              >
                {f.label.toUpperCase()}
                {f.required && <span style={{ color: "var(--coral)" }}> *</span>}
              </label>
              <input
                style={inputStyle}
                type={f.secret ? "password" : "text"}
                autoComplete="off"
                placeholder={f.placeholder}
                value={values[f.key] ?? ""}
                onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
              />
            </div>
          ))
        )}

        {msg && (
          <div
            role="alert"
            style={{
              marginTop: 14,
              padding: "10px 12px",
              borderRadius: 10,
              fontSize: 12.5,
              lineHeight: 1.5,
              background: msg.kind === "ok" ? "rgba(16,185,129,0.10)" : "rgba(239,68,68,0.10)",
              border: `1px solid ${msg.kind === "ok" ? "rgba(16,185,129,0.30)" : "rgba(239,68,68,0.30)"}`,
              color: msg.kind === "ok" ? "var(--success, #10B981)" : "#ef4444",
            }}
          >
            {msg.text}
          </div>
        )}

        <div style={{ display: "flex", gap: 10, marginTop: 20, flexWrap: "wrap" }}>
          <button type="button" className="jlift" style={primaryBtn} disabled={saving} onClick={handleSave}>
            {saving ? "Enregistrement…" : "Enregistrer"}
          </button>
          <button type="button" className="jlift" style={ghostBtn} disabled={testing} onClick={handleTest}>
            {testing ? "Test…" : "Tester la connexion"}
          </button>
          {channel.connected && !channel.builtin && (
            <button
              type="button"
              className="jlift"
              style={{ ...ghostBtn, color: "#ef4444", borderColor: "rgba(239,68,68,0.4)", marginLeft: "auto" }}
              disabled={saving}
              onClick={handleDisconnect}
            >
              Déconnecter
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function IntegrationCard({
  channel,
  onConfigure,
}: {
  channel: ChannelStatus;
  onConfigure: (c: ChannelStatus) => void;
}) {
  const preset = CHANNEL_PRESETS[channel.channel] ?? FALLBACK_PRESET;
  const meta = channel.account ?? (channel.builtin ? "Intégré nativement" : null);
  const configurable = channel.configurable ?? false;
  // Reçu mais envoi désactivé (pas d'identifiants sortants) → chip d'avertissement.
  const inboundOnly = channel.connected && !channel.builtin && channel.outbound_ready === false;

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
          {inboundOnly && (
            <span className="jbadge jbadge--slate" style={{ color: "#d97706" }}>
              ENVOI DÉSACTIVÉ
            </span>
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
          {configurable ? (
            <button
              type="button"
              className="jlift"
              style={channel.connected ? ghostBtn : primaryBtn}
              onClick={() => onConfigure(channel)}
            >
              {channel.connected ? "Configurer" : "Connecter →"}
            </button>
          ) : (
            <span className="jmono" style={{ fontSize: 11.5, color: "var(--text-2)" }}>
              {channel.builtin ? "Toujours actif" : "Bientôt disponible"}
            </span>
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
        style={{ width: 56, height: 56, borderRadius: 14, background: "var(--bg-tint)", flexShrink: 0 }}
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
  const [editing, setEditing] = useState<ChannelStatus | null>(null);

  const refresh = useCallback(() => {
    return listChannels()
      .then(setChannels)
      .catch(() => {});
  }, []);

  useEffect(() => {
    refresh().finally(() => setLoading(false));
  }, [refresh]);

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
          : channels.map((c) => (
              <IntegrationCard key={c.channel} channel={c} onConfigure={setEditing} />
            ))}
      </div>

      {editing && (
        <ChannelDialog channel={editing} onClose={() => setEditing(null)} onSaved={refresh} />
      )}
    </div>
  );
}

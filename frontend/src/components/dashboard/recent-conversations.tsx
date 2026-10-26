"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { humanError, listConversations, type ConversationSummary } from "@/lib/api";
import { channelLabel, intentLabel } from "@/lib/utils";
import { RelativeTime } from "@/components/ui/relative-time";
import { InitialsAvatar } from "@/components/jenny/jenny-ui";
import {
  useRealtimeRefresh,
  useRealtimeStatus,
} from "@/components/providers/realtime-provider";

/** dernières conversations, en direct */

// statut lisible d'une conversation
function statusOf(c: ConversationSummary): { label: string; cls: string } {
  if (c.is_escalated) return { label: "→ VOUS", cls: "jbadge--warn" };
  if (c.awaiting_reply) return { label: c.overdue ? "EN RETARD" : "À TRAITER", cls: c.overdue ? "jbadge--urgent" : "jbadge--slate" };
  if (c.status === "closed") return { label: "CLOSE", cls: "jbadge--mint" };
  return { label: "RÉPONDU", cls: "jbadge--coral" };
}

export function RecentConversations({ limit = 6 }: { limit?: number }) {
  const live = useRealtimeStatus();
  const [items, setItems] = useState<ConversationSummary[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await listConversations({ sort_by: "recent", limit });
      setItems(res.conversations);
      setTotal(res.total);
      setError(null);
    } catch (err) {
      setError(humanError(err, "Impossible de charger les conversations."));
    }
  }, [limit]);

  useEffect(() => {
    // synchro avec l'api
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  useRealtimeRefresh(load, 500);

  return (
    <div className="jcard" style={{ padding: 20 }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 14, gap: 10, flexWrap: "wrap" }}>
        <h2 style={{ fontSize: 14, fontWeight: 600, letterSpacing: "-0.01em", color: "var(--text)", margin: 0 }}>
          Dernières conversations
        </h2>
        <span
          style={{
            padding: "2px 8px",
            background: live ? "color-mix(in srgb, var(--success) 12%, transparent)" : "color-mix(in srgb, var(--warning) 14%, transparent)",
            color: live ? "var(--success)" : "var(--warning)",
            borderRadius: 999,
            fontSize: 10,
            fontWeight: 700,
            fontFamily: "var(--mono)",
            display: "flex",
            alignItems: "center",
            gap: 5,
          }}
          title={live ? "Mise à jour en temps réel" : "Reconnexion au flux…"}
        >
          <span
            className={live ? "animate-pulse" : undefined}
            style={{ width: 6, height: 6, background: "currentColor", borderRadius: "50%" }}
          />
          {live ? "EN DIRECT" : "RECONNEXION…"}
        </span>
        <Link
          href="/conversations"
          style={{ marginLeft: "auto", fontSize: 12.5, fontWeight: 600, color: "var(--coral)", display: "inline-flex", alignItems: "center", gap: 4, textDecoration: "none" }}
        >
          Tout voir{total > 0 ? ` (${total})` : ""}
          <ArrowRight style={{ width: 13, height: 13 }} />
        </Link>
      </div>

      {error && !items ? (
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", padding: "8px 0" }}>
          <span style={{ fontSize: 13, color: "var(--text-2)", flex: 1 }}>{error}</span>
          <button type="button" className="jpill" onClick={() => void load()}>
            Réessayer
          </button>
        </div>
      ) : items === null ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="animate-pulse" style={{ height: 44, borderRadius: 10, background: "var(--divider-soft)" }} />
          ))}
        </div>
      ) : items.length === 0 ? (
        <p style={{ fontSize: 13, color: "var(--text-2)", padding: "8px 0" }}>
          Aucune conversation pour le moment. Testez Jenny depuis{" "}
          <Link href="/chat" style={{ color: "var(--coral)", fontWeight: 600 }}>
            la page de test
          </Link>
          .
        </p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {items.map((c, i) => {
            const st = statusOf(c);
            const name = c.customer_name || "Client";
            return (
              <li key={c.id} style={{ borderBottom: i < items.length - 1 ? "1px solid var(--divider-soft)" : "none" }}>
                <Link
                  href={`/conversations?open=${c.id}`}
                  style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 0", textDecoration: "none", color: "inherit" }}
                >
                  <InitialsAvatar name={name} size={34} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2, minWidth: 0 }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {name}
                      </span>
                      <span className="jmono" style={{ fontSize: 10, color: "var(--text-3)", whiteSpace: "nowrap" }}>
                        {channelLabel(c.channel)}
                        {c.current_intent ? ` · ${intentLabel(c.current_intent)}` : ""}
                      </span>
                    </div>
                    <div style={{ fontSize: 12.5, color: "var(--text-2)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {c.last_message_preview || "—"}
                    </div>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, flexShrink: 0 }}>
                    <span className={`jbadge ${st.cls}`}>{st.label}</span>
                    {c.last_message_at && (
                      <RelativeTime date={c.last_message_at} className="jmono text-[10px] text-jenny-text-secondary" />
                    )}
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

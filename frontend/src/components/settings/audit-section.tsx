"use client";

import { useCallback, useEffect, useState } from "react";
import {
  History,
  RefreshCw,
  CheckCircle2,
  UserCheck,
  Flag,
  Tag,
  Send,
  GitMerge,
  KeyRound,
  Layers,
  Activity,
} from "lucide-react";
import { listAudit, type AuditItem } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { RelativeTime } from "@/components/ui/relative-time";
import { Avatar } from "@/components/ui/avatar";

// Icône + teinte par type d'action, pour lire la timeline d'un coup d'œil.
const ACTION_META: Record<string, { icon: typeof Activity; tint: string }> = {
  "conversation.status_changed": { icon: CheckCircle2, tint: "text-jenny-success" },
  "conversation.assigned": { icon: UserCheck, tint: "text-jenny-email" },
  "conversation.priority_changed": { icon: Flag, tint: "text-jenny-warning" },
  "conversation.tags_updated": { icon: Tag, tint: "text-jenny-coral" },
  "conversation.replied": { icon: Send, tint: "text-jenny-coral" },
  "conversation.merged": { icon: GitMerge, tint: "text-jenny-instagram" },
  "api_key.created": { icon: KeyRound, tint: "text-jenny-success" },
  "api_key.revoked": { icon: KeyRound, tint: "text-jenny-error" },
};

function metaFor(action: string) {
  if (ACTION_META[action]) return ACTION_META[action];
  if (action.startsWith("conversation.bulk_"))
    return { icon: Layers, tint: "text-jenny-text-secondary" };
  return { icon: Activity, tint: "text-jenny-text-secondary" };
}

export function AuditSection() {
  const [items, setItems] = useState<AuditItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [limit, setLimit] = useState(15);

  const load = useCallback(async (lim: number) => {
    setLoading(true);
    try {
      const data = await listAudit({ limit: lim });
      setItems(data.items);
      setTotal(data.total);
    } catch {
      // silencieux
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(limit);
  }, [load, limit]);

  return (
    <Card className="p-6">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <History className="w-5 h-5 text-jenny-coral" />
          <h3 className="font-semibold text-jenny-text">Journal d&apos;activité</h3>
        </div>
        <button
          onClick={() => void load(limit)}
          aria-label="Rafraîchir le journal"
          title="Rafraîchir"
          className="p-1.5 rounded-lg text-jenny-text-secondary hover:text-jenny-coral hover:bg-jenny-coral/10 transition-colors"
        >
          <RefreshCw className={loading ? "w-4 h-4 animate-spin" : "w-4 h-4"} />
        </button>
      </div>

      {loading && items.length === 0 ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-10 rounded-xl animate-shimmer" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <p className="text-sm text-jenny-text-secondary text-center py-6">
          Aucune activité enregistrée pour le moment.
        </p>
      ) : (
        <>
          <div className="relative pl-2">
            {/* Ligne verticale de la timeline */}
            <span className="absolute left-[1.1rem] top-2 bottom-2 w-px bg-jenny-divider" />
            <div className="space-y-1">
              {items.map((a) => {
                const { icon: Icon, tint } = metaFor(a.action);
                return (
                  <div key={a.id} className="relative flex items-start gap-3 py-1.5">
                    <span className="relative z-10 w-7 h-7 rounded-full bg-jenny-surface border border-jenny-divider flex items-center justify-center flex-shrink-0">
                      <Icon className={`w-3.5 h-3.5 ${tint}`} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-jenny-text leading-snug">{a.summary}</p>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        {a.actor ? (
                          <>
                            <Avatar name={a.actor} size="sm" className="!w-4 !h-4 !text-[8px]" />
                            <span className="text-[11px] text-jenny-text-secondary truncate">
                              {a.actor}
                            </span>
                          </>
                        ) : (
                          <span className="text-[11px] text-jenny-text-secondary">
                            Système
                          </span>
                        )}
                        <span className="text-jenny-text-secondary/40">·</span>
                        <RelativeTime
                          date={a.created_at}
                          className="text-[11px] text-jenny-text-secondary/70"
                        />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {items.length < total && (
            <div className="flex justify-center mt-3">
              <button
                onClick={() => setLimit((l) => l + 25)}
                className="text-xs font-medium text-jenny-coral hover:underline underline-offset-2"
              >
                Voir plus ({total - items.length})
              </button>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

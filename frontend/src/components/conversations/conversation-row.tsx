"use client";

import { memo } from "react";
import {
  Clock,
  MessageSquare,
  ArrowRight,
  AlertTriangle,
  Flag,
  CornerUpLeft,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { RelativeTime } from "@/components/ui/relative-time";
import { Avatar } from "@/components/ui/avatar";
import { cn, channelLabel, statusLabel, intentLabel } from "@/lib/utils";
import type { ConversationSummary } from "@/lib/api";

function statusColor(status: string) {
  if (status === "open") return "success" as const;
  return "default" as const;
}

function formatWait(minutes: number): string {
  if (minutes >= 1440) return `${Math.floor(minutes / 1440)}j`;
  if (minutes >= 60) return `${Math.floor(minutes / 60)}h`;
  return `${minutes}min`;
}

// Priorités mises en avant (low/medium = pas de pastille, pour éviter le bruit).
const PRIORITY_META: Record<string, { label: string; cls: string }> = {
  critical: { label: "Critique", cls: "bg-jenny-error/15 text-jenny-error" },
  high: { label: "Haute", cls: "bg-jenny-warning/15 text-jenny-warning" },
};

interface Props {
  conv: ConversationSummary;
  selected: boolean;
  onSelect: (id: string) => void;
  onTagClick: (tag: string) => void;
  // Mode sélection multiple (#1).
  selectable?: boolean;
  checked?: boolean;
  onToggle?: (id: string) => void;
  // Réponse rapide depuis la liste (#2).
  onQuickReply?: (id: string) => void;
}

function ConversationRowImpl({
  conv,
  selected,
  onSelect,
  onTagClick,
  selectable,
  checked,
  onToggle,
  onQuickReply,
}: Props) {
  const prio = PRIORITY_META[conv.priority_level];
  return (
    <div
      className={cn(
        "flex items-stretch border-l-2 border-b border-b-jenny-divider transition-colors",
        selected
          ? "bg-jenny-coral/5 border-l-jenny-coral"
          : conv.awaiting_reply
          ? "border-l-jenny-coral/40 hover:bg-jenny-bg/50"
          : "border-l-transparent hover:bg-jenny-bg/50"
      )}
    >
      {selectable && (
        <label
          className="flex items-center pl-3 cursor-pointer"
          onClick={(e) => e.stopPropagation()}
        >
          <input
            type="checkbox"
            checked={!!checked}
            onChange={() => onToggle?.(conv.id)}
            aria-label="Sélectionner la conversation"
            className="w-4 h-4 rounded border-jenny-divider text-jenny-coral focus:ring-jenny-coral/30 cursor-pointer accent-jenny-coral"
          />
        </label>
      )}
      <button onClick={() => onSelect(conv.id)} className="flex-1 min-w-0 text-left p-4 block">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-2.5 min-w-0 flex-1">
            <Avatar name={conv.customer_name} email={null} size="sm" className="mt-0.5" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 mb-1">
                {conv.awaiting_reply && (
                  <span
                    className="w-2 h-2 rounded-full bg-jenny-coral flex-shrink-0 animate-pulse"
                    title="En attente de réponse"
                  />
                )}
                <span
                  className={cn(
                    "text-sm text-jenny-text truncate",
                    conv.awaiting_reply ? "font-semibold" : "font-medium"
                  )}
                >
                  {conv.customer_name || "Client inconnu"}
                </span>
                <Badge variant="channel" channel={conv.channel}>
                  {channelLabel(conv.channel)}
                </Badge>
              </div>
              <p
                className={cn(
                  "text-sm line-clamp-2",
                  conv.awaiting_reply ? "text-jenny-text/80" : "text-jenny-text-secondary"
                )}
              >
                {conv.last_message_preview || "(Pas de message)"}
              </p>
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <Badge variant={statusColor(conv.status)}>{statusLabel(conv.status)}</Badge>
                {prio && (
                  <span
                    className={cn(
                      "inline-flex items-center gap-0.5 text-[10px] font-semibold rounded-full px-1.5 py-0.5",
                      prio.cls
                    )}
                    title={`Priorité ${prio.label.toLowerCase()}`}
                  >
                    <Flag className="w-2.5 h-2.5" />
                    {prio.label}
                  </span>
                )}
                {conv.overdue && conv.waiting_minutes != null && (
                  <Badge variant="error">
                    <Clock className="w-3 h-3 mr-1" />
                    En retard · {formatWait(conv.waiting_minutes)}
                  </Badge>
                )}
                {conv.is_escalated && (
                  <Badge variant="error">
                    <AlertTriangle className="w-3 h-3 mr-1" />
                    Escaladée
                  </Badge>
                )}
                {conv.current_intent && (
                  <span className="text-[10px] text-jenny-text-secondary/60">
                    {intentLabel(conv.current_intent)}
                  </span>
                )}
                {conv.tags.map((t) => (
                  <span
                    key={t}
                    role="button"
                    tabIndex={0}
                    onClick={(e) => {
                      e.stopPropagation();
                      onTagClick(t);
                    }}
                    className="text-[10px] bg-jenny-coral/10 text-jenny-coral rounded-full px-1.5 py-0.5 hover:bg-jenny-coral/20 transition-colors cursor-pointer"
                  >
                    {t}
                  </span>
                ))}
              </div>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1 flex-shrink-0">
            <span className="text-[10px] text-jenny-text-secondary flex items-center gap-1">
              <Clock className="w-3 h-3" />
              <RelativeTime date={conv.last_message_at || conv.created_at} />
            </span>
            <span className="text-[10px] text-jenny-text-secondary/60 flex items-center gap-1">
              <MessageSquare className="w-3 h-3" />
              {conv.message_count}
            </span>
            {onQuickReply && conv.awaiting_reply ? (
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => {
                  e.stopPropagation();
                  onQuickReply(conv.id);
                }}
                title="Réponse rapide"
                aria-label="Réponse rapide"
                className="text-jenny-text-secondary/50 hover:text-jenny-coral transition-colors cursor-pointer"
              >
                <CornerUpLeft className="w-3.5 h-3.5" />
              </span>
            ) : (
              <ArrowRight className="w-3.5 h-3.5 text-jenny-text-secondary/40" />
            )}
          </div>
        </div>
      </button>
    </div>
  );
}

export const ConversationRow = memo(ConversationRowImpl);

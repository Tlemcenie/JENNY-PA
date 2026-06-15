"use client";

import {
  Activity,
  MessageSquare,
  ShoppingBag,
  CreditCard,
  LifeBuoy,
} from "lucide-react";
import { RelativeTime } from "@/components/ui/relative-time";
import { channelLabel, statusLabel, formatMoney, cn } from "@/lib/utils";
import type { Customer360 } from "@/lib/api";

type Kind = "conversation" | "order" | "transaction" | "ticket";

interface TimelineEvent {
  id: string;
  kind: Kind;
  date: string;
  title: string;
  subtitle: string;
  amount?: number | null;
  currency?: string;
  conversationId?: string;
}

const KIND_META: Record<Kind, { icon: typeof Activity; tint: string }> = {
  conversation: { icon: MessageSquare, tint: "text-jenny-coral" },
  order: { icon: ShoppingBag, tint: "text-jenny-email" },
  transaction: { icon: CreditCard, tint: "text-jenny-success" },
  ticket: { icon: LifeBuoy, tint: "text-jenny-warning" },
};

/** Fusionne conversations, commandes, transactions et tickets en une seule
 *  timeline chronologique (#9). */
function buildEvents(data: Customer360): TimelineEvent[] {
  const events: TimelineEvent[] = [];
  for (const c of data.conversations) {
    events.push({
      id: `c-${c.id}`,
      kind: "conversation",
      date: c.last_message_at || c.created_at,
      title: `Conversation ${channelLabel(c.channel)}`,
      subtitle: `${statusLabel(c.status)} · ${c.message_count} message${c.message_count > 1 ? "s" : ""}`,
      conversationId: c.id,
    });
  }
  for (const o of data.orders) {
    events.push({
      id: `o-${o.id}`,
      kind: "order",
      date: o.created_at,
      title: o.reference || "Commande",
      subtitle: statusLabel(o.status),
      amount: o.total_amount_minor,
      currency: o.currency,
    });
  }
  for (const t of data.transactions) {
    events.push({
      id: `t-${t.id}`,
      kind: "transaction",
      date: t.occurred_at,
      title: t.label,
      subtitle: statusLabel(t.status),
      amount: t.amount_minor,
      currency: t.currency,
    });
  }
  for (const k of data.tickets) {
    events.push({
      id: `k-${k.id}`,
      kind: "ticket",
      date: k.created_at,
      title: k.subject || k.reference || "Ticket",
      subtitle: statusLabel(k.status),
    });
  }
  return events.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
}

export function ActivityTimeline({
  data,
  onOpenConversation,
}: {
  data: Customer360;
  onOpenConversation?: (conversationId: string) => void;
}) {
  const events = buildEvents(data);

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <Activity className="w-3.5 h-3.5 text-jenny-text-secondary" />
        <h3 className="text-xs font-semibold uppercase tracking-wide text-jenny-text-secondary">
          Activité
        </h3>
        <span className="text-[11px] text-jenny-text-secondary/60">{events.length}</span>
      </div>

      {events.length === 0 ? (
        <p className="text-sm text-jenny-text-secondary">Aucune activité.</p>
      ) : (
        <div className="relative pl-1">
          <span className="absolute left-[0.85rem] top-1.5 bottom-1.5 w-px bg-jenny-divider" />
          <div className="space-y-0.5">
            {events.map((e) => {
              const { icon: Icon, tint } = KIND_META[e.kind];
              const clickable = e.kind === "conversation" && e.conversationId;
              const Wrapper: React.ElementType = clickable ? "button" : "div";
              return (
                <Wrapper
                  key={e.id}
                  {...(clickable
                    ? { onClick: () => onOpenConversation?.(e.conversationId!) }
                    : {})}
                  className={cn(
                    "relative w-full flex items-start gap-3 py-1.5 pr-1 text-left rounded-lg transition-colors",
                    clickable && "hover:bg-jenny-bg cursor-pointer"
                  )}
                >
                  <span className="relative z-10 w-6 h-6 rounded-full bg-jenny-surface border border-jenny-divider flex items-center justify-center flex-shrink-0">
                    <Icon className={cn("w-3 h-3", tint)} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm text-jenny-text truncate">{e.title}</span>
                      {e.amount != null && (
                        <span className="text-sm font-medium text-jenny-text tabular-nums shrink-0">
                          {formatMoney(e.amount, e.currency)}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 text-[11px] text-jenny-text-secondary">
                      <span className="truncate">{e.subtitle}</span>
                      <span className="text-jenny-text-secondary/40">·</span>
                      <RelativeTime date={e.date} className="shrink-0" />
                    </div>
                  </div>
                </Wrapper>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

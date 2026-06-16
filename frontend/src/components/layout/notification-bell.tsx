"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { Bell, AlertTriangle, UserPlus, Clock, CheckCheck, Inbox } from "lucide-react";
import {
  listNotifications,
  getUnreadNotificationCount,
  markNotificationRead,
  markAllNotificationsRead,
  subscribeToConversationEvents,
  type NotificationItem,
} from "@/lib/api";
import { RelativeTime } from "@/components/ui/relative-time";
import { listStagger, listItem } from "@/lib/motion";

const KIND_ICON: Record<string, typeof Bell> = {
  assigned: UserPlus,
  escalated: AlertTriangle,
  snooze_due: Clock,
};

const KIND_TINT: Record<string, string> = {
  assigned: "text-jenny-email",
  escalated: "text-jenny-error",
  snooze_due: "text-jenny-warning",
};

export function NotificationBell() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const refreshCount = useCallback(() => {
    getUnreadNotificationCount()
      .then((r) => setUnread(r.unread))
      .catch(() => {});
  }, []);

  const loadList = useCallback(() => {
    setLoading(true);
    listNotifications(false, 30)
      .then((r) => {
        setItems(r.notifications);
        setUnread(r.unread);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  // Compteur initial + rafraîchissement sur événements temps réel et en
  // secours toutes les 60 s (certaines notifs viennent du worker, hors SSE).
  useEffect(() => {
    refreshCount();
    const unsub = subscribeToConversationEvents(() => refreshCount());
    const poll = setInterval(refreshCount, 60000);
    return () => {
      unsub();
      clearInterval(poll);
    };
  }, [refreshCount]);

  // Charge la liste à l'ouverture (synchro avec un système externe : l'API).
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (open) loadList();
  }, [open, loadList]);

  // Fermeture au clic extérieur + Échap.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const openConversation = (n: NotificationItem) => {
    if (!n.read) {
      markNotificationRead(n.id).then((r) => setUnread(r.unread)).catch(() => {});
      setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
    }
    setOpen(false);
    if (n.conversation_id) {
      // Si déjà sur la page Conversations : événement window (pas de remontage).
      // Sinon : navigation avec ?open=<id> (lu au montage par la page).
      window.dispatchEvent(
        new CustomEvent("jenny:open-conversation", { detail: n.conversation_id })
      );
      router.push(`/conversations?open=${n.conversation_id}`);
    }
  };

  const markAll = () => {
    markAllNotificationsRead()
      .then(() => {
        setUnread(0);
        setItems((prev) => prev.map((x) => ({ ...x, read: true })));
      })
      .catch(() => {});
  };

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label="Notifications"
        title="Notifications"
        className="relative w-9 h-9 rounded-xl flex items-center justify-center text-jenny-text-secondary hover:text-jenny-coral hover:bg-jenny-coral/10 transition-colors"
      >
        <Bell className="w-[18px] h-[18px]" />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-jenny-error text-white text-[10px] font-bold flex items-center justify-center">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.14 }}
            className="absolute right-0 mt-2 w-80 max-w-[calc(100vw-1.5rem)] rounded-2xl bg-jenny-surface border border-jenny-divider shadow-xl z-50 overflow-hidden"
          >
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-jenny-divider">
              <span className="text-sm font-semibold text-jenny-text">Notifications</span>
              {items.some((n) => !n.read) && (
                <button
                  onClick={markAll}
                  className="flex items-center gap-1 text-[11px] text-jenny-text-secondary hover:text-jenny-coral transition-colors"
                >
                  <CheckCheck className="w-3.5 h-3.5" />
                  Tout lire
                </button>
              )}
            </div>

            <div className="max-h-96 overflow-y-auto">
              {loading && items.length === 0 ? (
                <div className="px-4 py-8 text-center text-sm text-jenny-text-secondary">
                  Chargement…
                </div>
              ) : items.length === 0 ? (
                <div className="px-4 py-10 flex flex-col items-center gap-2 text-jenny-text-secondary">
                  <Inbox className="w-7 h-7 opacity-40" />
                  <span className="text-sm">Aucune notification</span>
                </div>
              ) : (
                // Apparition en cascade des notifications (listStagger/listItem).
                // Respecte prefers-reduced-motion : listItem n'anime que opacity/y
                // et framer neutralise le mouvement quand l'utilisateur le demande.
                <motion.div variants={listStagger} initial="hidden" animate="show">
                  {items.map((n) => {
                    const Icon = KIND_ICON[n.kind] || Bell;
                    const tint = KIND_TINT[n.kind] || "text-jenny-text-secondary";
                    return (
                      <motion.button
                        key={n.id}
                        variants={listItem}
                        onClick={() => openConversation(n)}
                        className={`w-full text-left flex gap-3 px-4 py-3 border-b border-jenny-divider/60 last:border-0 hover:bg-jenny-bg transition-colors ${
                          n.read ? "" : "bg-jenny-coral/[0.04]"
                        }`}
                      >
                        <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${tint}`} />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-jenny-text truncate">
                              {n.title}
                            </span>
                            {!n.read && (
                              <span className="w-1.5 h-1.5 rounded-full bg-jenny-coral shrink-0" />
                            )}
                          </div>
                          {n.body && (
                            <p className="text-xs text-jenny-text-secondary truncate mt-0.5">
                              {n.body}
                            </p>
                          )}
                          <RelativeTime
                            date={n.created_at}
                            className="text-[10px] text-jenny-text-secondary/70"
                          />
                        </div>
                      </motion.button>
                    );
                  })}
                </motion.div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

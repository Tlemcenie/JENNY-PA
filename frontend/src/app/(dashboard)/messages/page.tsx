"use client";

import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search,
  Filter,
  ChevronDown,
  ArrowRight,
  Clock,
  Inbox,
  RefreshCw,
} from "lucide-react";
import { listMessages, type Message, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatRelativeTime, channelLabel, statusLabel, categoryLabel, cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SkeletonCard } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { fadeInUp } from "@/lib/motion";

const channels = ["all", "whatsapp", "instagram", "email", "twitter", "form"];
const statuses = ["all", "received", "processing", "responded"];

export default function MessagesPage() {
  const { user } = useAuth();
  const businessId = user?.business_id;
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedChannel, setSelectedChannel] = useState("all");
  const [selectedStatus, setSelectedStatus] = useState("all");
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedMessage, setSelectedMessage] = useState<Message | null>(null);

  const fetchMessages = useCallback(async (resetCursor = true) => {
    if (!businessId) return;
    setIsLoading(true);
    setError(null);
    try {
      const params: Record<string, string> = { limit: "20" };
      if (selectedChannel !== "all") params.channel = selectedChannel;
      if (selectedStatus !== "all") params.status = selectedStatus;
      if (!resetCursor && cursor) params.cursor = cursor;

      const data = await listMessages(businessId, params);
      if (resetCursor) {
        setMessages(data.messages || []);
      } else {
        setMessages((prev) => [...prev, ...(data.messages || [])]);
      }
      setCursor(data.next_cursor);
      setHasMore(!!data.next_cursor);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`Erreur ${err.status}: ${(err.data as { detail?: string })?.detail || err.statusText}`);
      } else {
        setError("Impossible de charger les messages. Vérifiez que le backend est démarré.");
      }
    } finally {
      setIsLoading(false);
    }
  }, [selectedChannel, selectedStatus, cursor, businessId]);

  useEffect(() => {
    fetchMessages(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedChannel, selectedStatus, businessId]);

  const filteredMessages = search
    ? messages.filter(
        (m) =>
          m.content?.toLowerCase().includes(search.toLowerCase()) ||
          m.sender_name?.toLowerCase().includes(search.toLowerCase())
      )
    : messages;

  const statusColor = (status: string) => {
    switch (status) {
      case "responded":
        return "success" as const;
      case "processing":
        return "warning" as const;
      case "received":
        return "default" as const;
      default:
        return "default" as const;
    }
  };

  const priorityLabel = (p: number) => {
    if (p >= 8) return { text: "Haute", color: "bg-jenny-error" };
    if (p >= 5) return { text: "Moyenne", color: "bg-jenny-warning" };
    return { text: "Basse", color: "bg-jenny-success" };
  };

  return (
    <div className="h-full flex">
      {/* List panel */}
      <div className={cn("flex flex-col border-r border-jenny-divider bg-jenny-surface", selectedMessage ? "w-[420px]" : "flex-1")}>
        {/* Filters */}
        <motion.div
          variants={fadeInUp}
          initial="hidden"
          animate="show"
          className="p-4 border-b border-jenny-divider space-y-3"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-jenny-text-secondary">
              {messages.length} message{messages.length > 1 ? "s" : ""}
              {hasMore ? "+" : ""}
            </span>
            <button
              onClick={() => fetchMessages(true)}
              disabled={isLoading}
              title="Rafraîchir"
              aria-label="Rafraîchir les messages"
              className="p-1.5 rounded-lg text-jenny-text-secondary hover:text-jenny-coral hover:bg-jenny-coral/10 disabled:opacity-50 transition-colors"
            >
              <RefreshCw className={cn("w-4 h-4", isLoading && "animate-spin")} />
            </button>
          </div>

          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-jenny-text-secondary" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Rechercher dans les messages..."
              className="w-full h-10 pl-10 pr-4 rounded-xl bg-jenny-bg border border-jenny-divider text-sm focus:outline-none focus:ring-2 focus:ring-jenny-coral/30 focus:border-jenny-coral transition-all"
            />
          </div>

          <div className="flex items-center gap-2 overflow-x-auto pb-1">
            <Filter className="w-4 h-4 text-jenny-text-secondary flex-shrink-0" />
            {channels.map((ch) => (
              <button
                key={ch}
                onClick={() => setSelectedChannel(ch)}
                className={cn(
                  "px-3 py-1 rounded-full text-xs font-medium transition-all whitespace-nowrap",
                  selectedChannel === ch
                    ? "bg-jenny-coral text-white"
                    : "bg-jenny-divider/50 text-jenny-text-secondary hover:bg-jenny-divider"
                )}
              >
                {ch === "all" ? "Tous" : channelLabel(ch)}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <ChevronDown className="w-3.5 h-3.5 text-jenny-text-secondary" />
            {statuses.map((st) => (
              <button
                key={st}
                onClick={() => setSelectedStatus(st)}
                className={cn(
                  "px-2.5 py-0.5 rounded-full text-[11px] font-medium transition-all",
                  selectedStatus === st
                    ? "bg-jenny-text text-white"
                    : "bg-jenny-divider/30 text-jenny-text-secondary hover:bg-jenny-divider"
                )}
              >
                {st === "all" ? "Tous" : statusLabel(st)}
              </button>
            ))}
          </div>
        </motion.div>

        {/* Messages list */}
        <div className="flex-1 overflow-y-auto">
          {isLoading && messages.length === 0 ? (
            <div className="p-4 space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <SkeletonCard key={i} />
              ))}
            </div>
          ) : error ? (
            <ErrorState message={error} onRetry={() => fetchMessages(true)} />
          ) : filteredMessages.length === 0 ? (
            <EmptyState
              icon={<Inbox className="w-8 h-8" />}
              title="Aucun message"
              description="Aucun message ne correspond aux filtres sélectionnés. Les messages apparaîtront ici quand ils seront reçus via les canaux configurés."
            />
          ) : (
            <div className="divide-y divide-jenny-divider">
              <AnimatePresence>
                {filteredMessages.map((msg, i) => (
                  <motion.button
                    key={msg.id}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.03 }}
                    onClick={() => setSelectedMessage(msg)}
                    className={cn(
                      "w-full text-left p-4 hover:bg-jenny-bg/50 transition-colors",
                      selectedMessage?.id === msg.id && "bg-jenny-coral/5 border-l-2 border-l-jenny-coral"
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-medium text-sm text-jenny-text truncate">
                            {msg.sender_name || "Inconnu"}
                          </span>
                          <Badge variant="channel" channel={msg.channel}>
                            {channelLabel(msg.channel)}
                          </Badge>
                        </div>
                        <p className="text-sm text-jenny-text-secondary line-clamp-2">
                          {msg.content || "(Pas de contenu)"}
                        </p>
                        <div className="flex items-center gap-2 mt-2">
                          <Badge variant={statusColor(msg.status)}>{statusLabel(msg.status)}</Badge>
                          {msg.priority > 0 && (
                            <span className="flex items-center gap-1 text-[10px] text-jenny-text-secondary">
                              <span className={cn("w-1.5 h-1.5 rounded-full", priorityLabel(msg.priority).color)} />
                              {priorityLabel(msg.priority).text}
                            </span>
                          )}
                          {msg.category && (
                            <span className="text-[10px] text-jenny-text-secondary/60">{categoryLabel(msg.category)}</span>
                          )}
                        </div>
                      </div>
                      <div className="flex flex-col items-end gap-1 flex-shrink-0">
                        <span className="text-[10px] text-jenny-text-secondary flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {formatRelativeTime(msg.created_at)}
                        </span>
                        <ArrowRight className="w-3.5 h-3.5 text-jenny-text-secondary/40" />
                      </div>
                    </div>
                  </motion.button>
                ))}
              </AnimatePresence>

              {hasMore && (
                <div className="p-4 flex justify-center">
                  <Button variant="ghost" size="sm" onClick={() => fetchMessages(false)} isLoading={isLoading}>
                    Charger plus
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Detail panel */}
      {selectedMessage && (
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          className="flex-1 p-6 overflow-y-auto"
        >
          <div className="max-w-2xl mx-auto">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-xl font-semibold text-jenny-text">{selectedMessage.sender_name || "Inconnu"}</h2>
                <div className="flex items-center gap-2 mt-1">
                  <Badge variant="channel" channel={selectedMessage.channel}>
                    {channelLabel(selectedMessage.channel)}
                  </Badge>
                  <Badge variant={statusColor(selectedMessage.status)}>{statusLabel(selectedMessage.status)}</Badge>
                  <span className="text-xs text-jenny-text-secondary">
                    {formatRelativeTime(selectedMessage.created_at)}
                  </span>
                </div>
              </div>
              <button
                onClick={() => setSelectedMessage(null)}
                className="text-jenny-text-secondary hover:text-jenny-text text-sm"
              >
                Fermer
              </button>
            </div>

            <Card className="mb-4">
              <h3 className="text-sm font-medium text-jenny-text-secondary mb-2">Contenu du message</h3>
              <p className="text-sm text-jenny-text leading-relaxed whitespace-pre-wrap">
                {selectedMessage.content || "(Pas de contenu)"}
              </p>
            </Card>

            <div className="grid grid-cols-2 gap-3">
              <Card className="p-4">
                <span className="text-xs text-jenny-text-secondary">Direction</span>
                <p className="text-sm font-medium text-jenny-text mt-0.5">
                  {selectedMessage.direction === "inbound" ? "Entrant" : "Sortant"}
                </p>
              </Card>
              <Card className="p-4">
                <span className="text-xs text-jenny-text-secondary">Priorité</span>
                <p className="text-sm font-medium text-jenny-text mt-0.5 flex items-center gap-1.5">
                  <span className={cn("w-2 h-2 rounded-full", priorityLabel(selectedMessage.priority).color)} />
                  {priorityLabel(selectedMessage.priority).text} ({selectedMessage.priority}/10)
                </p>
              </Card>
              {selectedMessage.category && (
                <Card className="p-4">
                  <span className="text-xs text-jenny-text-secondary">Catégorie</span>
                  <p className="text-sm font-medium text-jenny-text mt-0.5">{categoryLabel(selectedMessage.category)}</p>
                </Card>
              )}
              {selectedMessage.conversation_id && (
                <Card className="p-4">
                  <span className="text-xs text-jenny-text-secondary">Conversation</span>
                  <p className="text-xs font-mono text-jenny-text-secondary mt-0.5 truncate">
                    {selectedMessage.conversation_id}
                  </p>
                </Card>
              )}
            </div>
          </div>
        </motion.div>
      )}
    </div>
  );
}

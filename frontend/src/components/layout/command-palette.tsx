"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { Command } from "cmdk";
import { Search, MessagesSquare, Users, BookOpen, CalendarClock, CornerDownLeft } from "lucide-react";
import {
  globalSearch,
  listKnowledgeEntries,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { channelLabel } from "@/lib/utils";

type ResultKind = "conversation" | "customer" | "appointment" | "knowledge";

interface Result {
  kind: ResultKind;
  id: string;
  label: string;
  sub: string;
}

const KIND_META: Record<ResultKind, { icon: typeof Search; label: string; heading: string }> = {
  conversation: { icon: MessagesSquare, label: "Conversation", heading: "Conversations" },
  customer: { icon: Users, label: "Client", heading: "Clients" },
  appointment: { icon: CalendarClock, label: "Rendez-vous", heading: "Rendez-vous" },
  knowledge: { icon: BookOpen, label: "Connaissance", heading: "Connaissances" },
};

const ORDER: ResultKind[] = ["conversation", "customer", "appointment", "knowledge"];

function formatApptDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString("fr-FR", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

export function CommandPalette() {
  const router = useRouter();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Result[]>([]);
  const [loading, setLoading] = useState(false);

  // ⌘K / Ctrl+K, événement topbar, Échap.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    const onOpenEvent = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("jenny:command-open", onOpenEvent);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("jenny:command-open", onOpenEvent);
    };
  }, []);

  useEffect(() => {
    if (open) {
      setQuery("");
      setResults([]);
    }
  }, [open]);

  // Recherche (debounce) sur les trois sources.
  useEffect(() => {
    if (!open) return;
    const q = query.trim();
    if (!q) {
      setResults([]);
      return;
    }
    let cancelled = false;
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        // Recherche transversale unifiée (conversations + clients + RDV) en un
        // seul appel scopé au business, + connaissances (source distincte).
        const [global, knowledge] = await Promise.all([
          globalSearch(q, 5).catch(() => null),
          user?.business_id
            ? listKnowledgeEntries(user.business_id).catch(() => null)
            : Promise.resolve(null),
        ]);
        if (cancelled) return;
        const merged: Result[] = [];
        global?.conversations.forEach((c) =>
          merged.push({
            kind: "conversation",
            id: c.id,
            label: c.customer_name || "Client inconnu",
            sub: `${channelLabel(c.channel)} · ${c.preview || ""}`.trim(),
          })
        );
        global?.customers.forEach((c) =>
          merged.push({
            kind: "customer",
            id: c.id,
            label: c.full_name || c.email || "Client",
            sub: c.email || "",
          })
        );
        global?.appointments.forEach((a) =>
          merged.push({
            kind: "appointment",
            id: a.id,
            label: a.title,
            sub: formatApptDate(a.start_at),
          })
        );
        knowledge
          ?.filter((k) => k.title.toLowerCase().includes(q.toLowerCase()))
          .slice(0, 5)
          .forEach((k) =>
            merged.push({ kind: "knowledge", id: k.id, label: k.title, sub: k.category })
          );
        setResults(merged);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [query, open, user?.business_id]);

  const activate = (r: Result) => {
    setOpen(false);
    if (r.kind === "conversation") router.push(`/conversations?open=${r.id}`);
    else if (r.kind === "customer") router.push(`/customers?open=${r.id}`);
    else if (r.kind === "appointment") router.push("/calendar");
    else router.push("/knowledge");
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="fixed inset-0 z-[70] bg-black/40 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={() => setOpen(false)}
          />
          <motion.div
            className="fixed left-1/2 top-[12vh] z-[71] w-[min(92vw,600px)] -translate-x-1/2"
            initial={{ opacity: 0, scale: 0.97, y: -8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: -8 }}
            transition={{ duration: 0.18 }}
          >
            <Command
              shouldFilter={false}
              label="Recherche globale"
              className="bg-jenny-surface border border-jenny-divider rounded-2xl shadow-2xl overflow-hidden"
            >
              <div className="flex items-center gap-2.5 px-4 border-b border-jenny-divider">
                <Search className="w-4 h-4 text-jenny-text-secondary shrink-0" />
                <Command.Input
                  autoFocus
                  value={query}
                  onValueChange={setQuery}
                  placeholder="Rechercher une conversation, un client, une connaissance…"
                  className="flex-1 h-12 bg-transparent text-sm text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none"
                />
                <kbd className="text-[10px] text-jenny-text-secondary bg-jenny-divider/50 rounded px-1.5 py-0.5">
                  Esc
                </kbd>
              </div>

              <Command.List className="max-h-[50vh] overflow-y-auto p-2">
                {loading && results.length === 0 && (
                  <Command.Loading className="text-sm text-jenny-text-secondary text-center py-6">
                    Recherche…
                  </Command.Loading>
                )}
                {!query.trim() ? (
                  <p className="text-sm text-jenny-text-secondary text-center py-6">
                    Tapez pour rechercher partout.
                  </p>
                ) : (
                  <Command.Empty className="text-sm text-jenny-text-secondary text-center py-6">
                    Aucun résultat.
                  </Command.Empty>
                )}

                {ORDER.map((kind) => {
                  const items = results.filter((r) => r.kind === kind);
                  if (items.length === 0) return null;
                  const Icon = KIND_META[kind].icon;
                  return (
                    <Command.Group
                      key={kind}
                      heading={KIND_META[kind].heading}
                      className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:text-jenny-text-secondary/70"
                    >
                      {items.map((r) => (
                        <Command.Item
                          key={`${r.kind}-${r.id}`}
                          value={`${r.kind}-${r.id}-${r.label}`}
                          onSelect={() => activate(r)}
                          className="flex items-center gap-3 px-3 py-2.5 rounded-xl cursor-pointer text-left transition-colors data-[selected=true]:bg-jenny-coral/10"
                        >
                          <span className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 bg-jenny-divider/50 text-jenny-text-secondary group-data-[selected=true]:bg-jenny-coral/15">
                            <Icon className="w-4 h-4" />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block text-sm text-jenny-text truncate">{r.label}</span>
                            {r.sub && (
                              <span className="block text-xs text-jenny-text-secondary truncate">
                                {r.sub}
                              </span>
                            )}
                          </span>
                          <CornerDownLeft className="w-3.5 h-3.5 text-jenny-coral shrink-0 opacity-0 data-[selected=true]:opacity-100" />
                        </Command.Item>
                      ))}
                    </Command.Group>
                  );
                })}
              </Command.List>
            </Command>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

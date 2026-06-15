"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X, Plus, Trash2, MessageSquareText } from "lucide-react";
import {
  listCannedResponses,
  createCannedResponse,
  deleteCannedResponse,
  type CannedResponse,
} from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { useFocusTrap } from "@/lib/use-focus-trap";
import { easeOutExpo } from "@/lib/motion";

interface CannedManagerProps {
  open: boolean;
  onClose: () => void;
  /** Notifie le parent quand la liste change (pour rafraîchir les chips). */
  onChanged?: () => void;
}

export function CannedManager({ open, onClose, onChanged }: CannedManagerProps) {
  const toast = useToast();
  const confirm = useConfirm();
  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(open, dialogRef);
  const [items, setItems] = useState<CannedResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [title, setTitle] = useState("");
  const [shortcut, setShortcut] = useState("");
  const [content, setContent] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      setItems(await listCannedResponses());
    } catch {
      toast.error("Impossible de charger les réponses.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const add = async () => {
    if (!title.trim() || !content.trim() || saving) return;
    setSaving(true);
    try {
      await createCannedResponse({
        title: title.trim(),
        content: content.trim(),
        shortcut: shortcut.trim() || null,
      });
      setTitle("");
      setShortcut("");
      setContent("");
      await load();
      onChanged?.();
      toast.success("Réponse enregistrée.");
    } catch {
      toast.error("Échec de l'enregistrement.");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string, title: string) => {
    const ok = await confirm({
      title: "Supprimer cette réponse ?",
      message: `« ${title} » sera définitivement supprimée.`,
      confirmLabel: "Supprimer",
      danger: true,
    });
    if (!ok) return;
    try {
      await deleteCannedResponse(id);
      setItems((prev) => prev.filter((c) => c.id !== id));
      onChanged?.();
    } catch {
      toast.error("Suppression impossible.");
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="fixed inset-0 z-[60] bg-black/40 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
          />
          <motion.div
            ref={dialogRef}
            className="fixed left-1/2 top-1/2 z-[61] w-[min(92vw,560px)] max-h-[85vh] -translate-x-1/2 -translate-y-1/2 bg-jenny-surface border border-jenny-divider rounded-2xl shadow-2xl flex flex-col overflow-hidden"
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 8 }}
            transition={{ duration: 0.25, ease: easeOutExpo }}
            role="dialog"
            aria-label="Réponses enregistrées"
          >
            <div className="flex items-center justify-between p-4 border-b border-jenny-divider">
              <h2 className="flex items-center gap-2 font-semibold text-jenny-text">
                <MessageSquareText className="w-4 h-4 text-jenny-coral" />
                Réponses enregistrées
              </h2>
              <button
                onClick={onClose}
                aria-label="Fermer"
                className="p-1.5 rounded-lg text-jenny-text-secondary hover:text-jenny-text hover:bg-jenny-divider/40 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Formulaire d'ajout */}
            <div className="p-4 border-b border-jenny-divider space-y-2">
              <div className="flex gap-2">
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Titre (ex. Horaires)"
                  className="flex-1 h-9 px-3 text-sm rounded-lg bg-jenny-bg border border-jenny-divider text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:border-jenny-coral/50"
                />
                <input
                  value={shortcut}
                  onChange={(e) => setShortcut(e.target.value)}
                  placeholder="Raccourci"
                  className="w-32 h-9 px-3 text-sm rounded-lg bg-jenny-bg border border-jenny-divider text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:border-jenny-coral/50"
                />
              </div>
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="Contenu de la réponse…"
                rows={2}
                className="w-full px-3 py-2 text-sm rounded-lg bg-jenny-bg border border-jenny-divider text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:border-jenny-coral/50 resize-none"
              />
              <button
                onClick={add}
                disabled={!title.trim() || !content.trim() || saving}
                className="w-full h-9 flex items-center justify-center gap-1.5 rounded-lg bg-jenny-coral text-white text-sm font-medium hover:bg-jenny-coral-dark disabled:opacity-50 transition-colors"
              >
                <Plus className="w-4 h-4" />
                Ajouter
              </button>
            </div>

            {/* Liste */}
            <div className="flex-1 overflow-y-auto p-4 space-y-2">
              {loading ? (
                <p className="text-sm text-jenny-text-secondary text-center py-6">Chargement…</p>
              ) : items.length === 0 ? (
                <p className="text-sm text-jenny-text-secondary text-center py-6">
                  Aucune réponse enregistrée pour le moment.
                </p>
              ) : (
                items.map((c) => (
                  <div
                    key={c.id}
                    className="flex items-start justify-between gap-3 rounded-xl border border-jenny-divider p-3"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-sm text-jenny-text">{c.title}</span>
                        {c.shortcut && (
                          <span className="text-[10px] font-medium bg-jenny-coral/10 text-jenny-coral rounded px-1.5 py-0.5">
                            /{c.shortcut}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-jenny-text-secondary mt-0.5 line-clamp-2">
                        {c.content}
                      </p>
                    </div>
                    <button
                      onClick={() => remove(c.id, c.title)}
                      aria-label={`Supprimer ${c.title}`}
                      className="p-1.5 rounded-lg text-jenny-text-secondary hover:text-jenny-error hover:bg-jenny-error/10 transition-colors shrink-0"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                ))
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

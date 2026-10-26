"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertCircle, ArrowRight, Check, HelpCircle, RotateCcw, Send, X } from "lucide-react";
import {
  answerKnowledgeGap,
  humanError,
  listKnowledgeGaps,
  type KnowledgeGap,
} from "@/lib/api";
import { channelLabel, formatRelativeTime } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";

const NOT_IN_KB = "Réponse enregistrée, mais pas encore dans la base. Réessayez.";

/** vraies questions sans réponse */
export function GapsCard({ limit = 3 }: { limit?: number }) {
  const toast = useToast();
  const [gaps, setGaps] = useState<KnowledgeGap[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  // réponses pas encore en base
  const [notInKb, setNotInKb] = useState<Record<string, string>>({});
  const [retryingId, setRetryingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await listKnowledgeGaps("open");
      setGaps(res.gaps);
      setTotal(res.total);
      setError(null);
    } catch (err) {
      setError(humanError(err, "Impossible de charger les questions sans réponse."));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // carte traitée, on la retire
  const dropGap = (id: string) => {
    setGaps((prev) => (prev ? prev.filter((g) => g.id !== id) : prev));
    setTotal((t) => Math.max(0, t - 1));
    setNotInKb((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  };

  const submit = async (gap: KnowledgeGap) => {
    const answer = draft.trim();
    if (!answer) return;
    setSaving(true);
    try {
      const res = await answerKnowledgeGap(gap.id, answer, true);
      setOpenId(null);
      setDraft("");
      if (res.saved_to_kb) {
        toast.success("Réponse ajoutée à la base : Jenny saura répondre.");
        dropGap(gap.id);
      } else {
        // la carte reste, on peut réessayer
        toast.warning(NOT_IN_KB);
        setNotInKb((prev) => ({ ...prev, [gap.id]: answer }));
      }
    } catch (err) {
      toast.error(humanError(err, "Impossible d'enregistrer la réponse."));
    } finally {
      setSaving(false);
    }
  };

  // relance l'ajout à la base
  const retry = async (gap: KnowledgeGap) => {
    const answer = notInKb[gap.id];
    if (!answer) return;
    setRetryingId(gap.id);
    try {
      const res = await answerKnowledgeGap(gap.id, answer, true);
      if (res.saved_to_kb) {
        toast.success("Réponse ajoutée à la base : Jenny saura répondre.");
        dropGap(gap.id);
      } else {
        toast.warning(NOT_IN_KB);
      }
    } catch (err) {
      toast.error(humanError(err, "Impossible d'ajouter la réponse à la base."));
    } finally {
      setRetryingId(null);
    }
  };

  const shown = (gaps ?? []).slice(0, limit);

  return (
    <Card className="p-[22px]">
      <div className="flex items-center gap-2 mb-1">
        <div className="w-9 h-9 rounded-xl bg-jenny-coral/10 text-jenny-coral flex items-center justify-center">
          <HelpCircle className="w-[18px] h-[18px]" />
        </div>
        <h2 className="font-semibold text-jenny-text text-sm">Questions que Jenny n&apos;a pas su traiter</h2>
        <Link
          href="/learning"
          className="ml-auto inline-flex items-center gap-1 text-[12.5px] font-semibold text-jenny-coral hover:text-jenny-coral-dark"
        >
          Tout voir{total > 0 ? ` (${total})` : ""}
          <ArrowRight className="w-3.5 h-3.5" />
        </Link>
      </div>
      <p className="text-[12.5px] text-jenny-text-secondary mb-4">
        Une réponse ici part dans la base de connaissances : Jenny s&apos;en servira dès le prochain client.
      </p>

      {error && !gaps ? (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-[13px] text-jenny-text-secondary flex-1">{error}</span>
          <Button size="sm" variant="secondary" onClick={() => void load()}>
            Réessayer
          </Button>
        </div>
      ) : gaps === null ? (
        <div className="space-y-2">
          {Array.from({ length: 2 }).map((_, i) => (
            <div key={i} className="h-12 rounded-xl bg-jenny-divider/40 animate-pulse" />
          ))}
        </div>
      ) : shown.length === 0 ? (
        <div className="flex items-center gap-2 text-[13px] text-jenny-text-secondary">
          <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-jenny-success/15 text-jenny-success shrink-0">
            <Check className="w-3.5 h-3.5" />
          </span>
          Aucune question en attente.
        </div>
      ) : (
        <ul className="space-y-3">
          {shown.map((g) => (
            <li key={g.id} className="rounded-xl border border-jenny-divider p-3.5">
              <div className="flex items-start gap-3 flex-wrap">
                <div className="flex-1 min-w-[200px]">
                  <p className="text-[13.5px] font-medium text-jenny-text leading-snug">{g.question}</p>
                  <p className="text-[11.5px] text-jenny-text-secondary mt-1">
                    {g.occurrences > 1 ? `posée ${g.occurrences} fois · ` : ""}
                    {g.channel ? `${channelLabel(g.channel)} · ` : ""}
                    {formatRelativeTime(g.last_seen_at || g.created_at)}
                  </p>
                </div>
                {openId !== g.id && !notInKb[g.id] && (
                  <Button
                    size="sm"
                    onClick={() => {
                      setOpenId(g.id);
                      setDraft("");
                    }}
                  >
                    <Send className="w-3.5 h-3.5" />
                    Répondre
                  </Button>
                )}
              </div>
              {notInKb[g.id] && (
                <div
                  role="status"
                  className="mt-3 p-2.5 rounded-xl bg-jenny-warning/10 text-jenny-text text-[12.5px] flex items-center gap-2 flex-wrap"
                >
                  <AlertCircle className="w-4 h-4 text-jenny-warning shrink-0" />
                  <span className="flex-1 min-w-[180px]">{NOT_IN_KB}</span>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => void retry(g)}
                    isLoading={retryingId === g.id}
                  >
                    <RotateCcw className="w-3.5 h-3.5" />
                    Réessayer
                  </Button>
                </div>
              )}
              {openId === g.id && (
                <div className="mt-3 space-y-2">
                  <label className="sr-only" htmlFor={`gap-${g.id}`}>
                    Réponse pour Jenny
                  </label>
                  <textarea
                    id={`gap-${g.id}`}
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    rows={3}
                    autoFocus
                    placeholder="La réponse que Jenny donnera la prochaine fois…"
                    className="w-full px-3 py-2.5 rounded-[10px] bg-jenny-bg border border-jenny-divider text-[13px] text-jenny-text focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral resize-y"
                  />
                  <div className="flex items-center gap-2">
                    <Button size="sm" onClick={() => void submit(g)} isLoading={saving} disabled={!draft.trim()}>
                      <Check className="w-3.5 h-3.5" />
                      Enregistrer
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setOpenId(null)} disabled={saving}>
                      <X className="w-3.5 h-3.5" />
                      Annuler
                    </Button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

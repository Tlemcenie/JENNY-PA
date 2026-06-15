"use client";

import { useEffect, useState } from "react";
import { Clock } from "lucide-react";
import {
  getBusiness,
  updateBusiness,
  type BusinessHours,
} from "@/lib/api";
import { useToast } from "@/components/ui/toast";

const DAYS: Array<{ key: string; label: string }> = [
  { key: "mon", label: "Lundi" },
  { key: "tue", label: "Mardi" },
  { key: "wed", label: "Mercredi" },
  { key: "thu", label: "Jeudi" },
  { key: "fri", label: "Vendredi" },
  { key: "sat", label: "Samedi" },
  { key: "sun", label: "Dimanche" },
];

type DayState = { open: boolean; from: string; to: string };

function emptyState(): Record<string, DayState> {
  const s: Record<string, DayState> = {};
  for (const d of DAYS) s[d.key] = { open: false, from: "09:00", to: "19:00" };
  return s;
}

export function BusinessHoursSection() {
  const toast = useToast();
  const [days, setDays] = useState<Record<string, DayState>>(emptyState);
  const [autoReply, setAutoReply] = useState("");
  const [sla, setSla] = useState(30);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getBusiness()
      .then((b) => {
        const next = emptyState();
        const bh = b.business_hours || {};
        for (const d of DAYS) {
          const rng = bh[d.key];
          if (Array.isArray(rng) && rng.length === 2) {
            next[d.key] = { open: true, from: rng[0], to: rng[1] };
          }
        }
        setDays(next);
        setAutoReply(b.auto_reply_message ?? "");
        setSla(b.sla_minutes ?? 30);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      const bh: BusinessHours = {};
      let anyOpen = false;
      for (const d of DAYS) {
        const s = days[d.key];
        if (s.open) {
          bh[d.key] = [s.from, s.to];
          anyOpen = true;
        } else {
          bh[d.key] = null;
        }
      }
      await updateBusiness({
        business_hours: anyOpen ? bh : null,
        auto_reply_message: autoReply.trim() || null,
        sla_minutes: sla,
      });
      toast.success("Horaires et préférences enregistrés.");
    } catch {
      toast.error("Échec de l'enregistrement.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="bg-jenny-surface border border-jenny-divider rounded-2xl p-6 animate-pulse">
        <div className="h-5 w-40 bg-jenny-divider/50 rounded mb-4" />
        <div className="h-32 bg-jenny-divider/40 rounded" />
      </div>
    );
  }

  return (
    <div className="bg-jenny-surface border border-jenny-divider rounded-2xl p-6">
      <h2 className="flex items-center gap-2 text-base font-semibold text-jenny-text mb-1">
        <Clock className="w-4 h-4 text-jenny-coral" />
        Horaires & réponses automatiques
      </h2>
      <p className="text-sm text-jenny-text-secondary mb-4">
        Hors de ces horaires, Jenny envoie automatiquement le message ci-dessous au lieu de répondre.
      </p>

      <div className="space-y-1.5 mb-5">
        {DAYS.map((d) => {
          const s = days[d.key];
          return (
            <div key={d.key} className="flex items-center gap-3">
              <label className="flex items-center gap-2 w-28 shrink-0 cursor-pointer">
                <input
                  type="checkbox"
                  checked={s.open}
                  onChange={(e) =>
                    setDays((prev) => ({ ...prev, [d.key]: { ...prev[d.key], open: e.target.checked } }))
                  }
                  className="accent-jenny-coral"
                />
                <span className="text-sm text-jenny-text">{d.label}</span>
              </label>
              {s.open ? (
                <div className="flex items-center gap-2">
                  <input
                    type="time"
                    value={s.from}
                    onChange={(e) =>
                      setDays((prev) => ({ ...prev, [d.key]: { ...prev[d.key], from: e.target.value } }))
                    }
                    className="h-8 px-2 text-sm rounded-lg bg-jenny-bg border border-jenny-divider text-jenny-text focus:outline-none focus:border-jenny-coral/50"
                  />
                  <span className="text-jenny-text-secondary text-xs">à</span>
                  <input
                    type="time"
                    value={s.to}
                    onChange={(e) =>
                      setDays((prev) => ({ ...prev, [d.key]: { ...prev[d.key], to: e.target.value } }))
                    }
                    className="h-8 px-2 text-sm rounded-lg bg-jenny-bg border border-jenny-divider text-jenny-text focus:outline-none focus:border-jenny-coral/50"
                  />
                </div>
              ) : (
                <span className="text-xs text-jenny-text-secondary italic">Fermé</span>
              )}
            </div>
          );
        })}
      </div>

      <label className="block text-xs font-semibold uppercase tracking-wide text-jenny-text-secondary mb-1.5">
        Message automatique hors horaires
      </label>
      <textarea
        value={autoReply}
        onChange={(e) => setAutoReply(e.target.value)}
        rows={2}
        placeholder="Merci pour votre message ! Nous sommes actuellement fermés et reviendrons vers vous dès la réouverture."
        className="w-full px-3 py-2 text-sm rounded-xl bg-jenny-bg border border-jenny-divider text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:border-jenny-coral/50 resize-none mb-4"
      />

      <div className="flex items-center gap-2 mb-5">
        <label className="text-sm text-jenny-text">Seuil « en retard » (SLA)</label>
        <input
          type="number"
          min={1}
          value={sla}
          onChange={(e) => setSla(Math.max(1, Number(e.target.value) || 30))}
          className="w-20 h-9 px-2 text-sm rounded-lg bg-jenny-bg border border-jenny-divider text-jenny-text focus:outline-none focus:border-jenny-coral/50"
        />
        <span className="text-sm text-jenny-text-secondary">minutes</span>
      </div>

      <button
        onClick={save}
        disabled={saving}
        className="h-10 px-4 rounded-xl bg-jenny-coral text-white text-sm font-medium hover:bg-jenny-coral-dark disabled:opacity-50 transition-colors"
      >
        {saving ? "Enregistrement…" : "Enregistrer"}
      </button>
    </div>
  );
}

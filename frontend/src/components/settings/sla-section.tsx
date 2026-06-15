"use client";

import { useCallback, useEffect, useState } from "react";
import { Timer, Save, CheckCircle2, AlertCircle } from "lucide-react";
import {
  getBusiness,
  updateBusiness,
  type SlaRules,
  ApiError,
} from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";

const PRIORITY_ROWS: { key: string; label: string }[] = [
  { key: "critical", label: "Critique" },
  { key: "high", label: "Haute" },
  { key: "medium", label: "Normale" },
  { key: "low", label: "Basse" },
];

const CHANNEL_ROWS: { key: string; label: string }[] = [
  { key: "whatsapp", label: "WhatsApp" },
  { key: "instagram", label: "Instagram" },
  { key: "email", label: "Email" },
  { key: "form", label: "Formulaire" },
];

function extractError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    return (err.data as { detail?: string })?.detail || `Erreur ${err.status}`;
  }
  return fallback;
}

// Champ minutes : "" = pas de surcharge.
function MinutesField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3">
      <span className="text-sm text-jenny-text">{label}</span>
      <span className="flex items-center gap-1.5">
        <input
          type="number"
          min={1}
          max={10080}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="—"
          className="w-20 h-9 px-2.5 rounded-lg bg-jenny-bg border border-jenny-divider text-sm text-jenny-text text-right focus:outline-none focus:border-jenny-coral/50"
        />
        <span className="text-xs text-jenny-text-secondary w-8">min</span>
      </span>
    </label>
  );
}

export function SlaSection() {
  const toast = useToast();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const [defaultMins, setDefaultMins] = useState("30");
  const [priority, setPriority] = useState<Record<string, string>>({});
  const [channel, setChannel] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const b = await getBusiness();
      setDefaultMins(String(b.sla_minutes ?? 30));
      const rules = b.sla_rules || {};
      const p: Record<string, string> = {};
      Object.entries(rules.priority || {}).forEach(([k, v]) => (p[k] = String(v)));
      setPriority(p);
      const c: Record<string, string> = {};
      Object.entries(rules.channel || {}).forEach(([k, v]) => (c[k] = String(v)));
      setChannel(c);
    } catch {
      // silencieux
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const buildRules = (): SlaRules | null => {
    const p: Record<string, number> = {};
    for (const { key } of PRIORITY_ROWS) {
      const n = parseInt(priority[key] || "", 10);
      if (Number.isFinite(n) && n > 0) p[key] = n;
    }
    const c: Record<string, number> = {};
    for (const { key } of CHANNEL_ROWS) {
      const n = parseInt(channel[key] || "", 10);
      if (Number.isFinite(n) && n > 0) c[key] = n;
    }
    const rules: SlaRules = {};
    if (Object.keys(p).length) rules.priority = p as SlaRules["priority"];
    if (Object.keys(c).length) rules.channel = c;
    return Object.keys(rules).length ? rules : null;
  };

  const handleSave = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const mins = Math.max(1, Math.min(10080, parseInt(defaultMins || "30", 10) || 30));
      await updateBusiness({ sla_minutes: mins, sla_rules: buildRules() });
      setMsg({ ok: true, text: "SLA enregistrés." });
      toast.success("Règles SLA enregistrées.");
    } catch (err) {
      setMsg({ ok: false, text: extractError(err, "Échec de l'enregistrement.") });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="p-6">
      <div className="flex items-center gap-3 mb-2">
        <Timer className="w-5 h-5 text-jenny-coral" />
        <h3 className="font-semibold text-jenny-text">Délais de réponse (SLA)</h3>
      </div>
      <p className="text-sm text-jenny-text-secondary mb-5">
        Une conversation en attente au-delà du délai applicable est signalée « en
        retard ». La règle la plus stricte (priorité ou canal) s&apos;applique.
      </p>

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-9 rounded-xl animate-shimmer" />
          ))}
        </div>
      ) : (
        <div className="space-y-5">
          <MinutesField
            label="Délai par défaut"
            value={defaultMins}
            onChange={setDefaultMins}
          />

          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-jenny-text-secondary mb-2">
              Par priorité
            </p>
            <div className="space-y-2">
              {PRIORITY_ROWS.map((r) => (
                <MinutesField
                  key={r.key}
                  label={r.label}
                  value={priority[r.key] || ""}
                  onChange={(v) => setPriority((p) => ({ ...p, [r.key]: v }))}
                />
              ))}
            </div>
          </div>

          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-jenny-text-secondary mb-2">
              Par canal
            </p>
            <div className="space-y-2">
              {CHANNEL_ROWS.map((r) => (
                <MinutesField
                  key={r.key}
                  label={r.label}
                  value={channel[r.key] || ""}
                  onChange={(v) => setChannel((c) => ({ ...c, [r.key]: v }))}
                />
              ))}
            </div>
          </div>

          {msg && (
            <div
              className={cn(
                "p-3 rounded-xl text-sm flex items-center gap-2",
                msg.ok
                  ? "bg-jenny-success/10 text-jenny-success"
                  : "bg-jenny-error/10 text-jenny-error"
              )}
            >
              {msg.ok ? (
                <CheckCircle2 className="w-4 h-4" />
              ) : (
                <AlertCircle className="w-4 h-4" />
              )}
              {msg.text}
            </div>
          )}

          <div className="flex justify-end">
            <Button onClick={handleSave} isLoading={saving}>
              <Save className="w-4 h-4" />
              Enregistrer
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}

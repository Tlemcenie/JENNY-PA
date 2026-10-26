"use client";

import { useEffect, useState } from "react";
import { BellOff, BellRing } from "lucide-react";
import { getMarketingOptOut, setMarketingOptOut, type OptOutState } from "@/lib/api-campaigns";
import { Switch } from "@/components/ui/switch";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";

// refus des offres (STOP)

function shortDay(iso: string): string {
  return new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" }).format(
    new Date(iso)
  );
}

export function MarketingOptOut({
  customerId,
  onChange,
}: {
  customerId: string;
  onChange?: (state: OptOutState) => void;
}) {
  const toast = useToast();
  const confirm = useConfirm();
  const [state, setState] = useState<OptOutState | null>(null);
  const [failed, setFailed] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    setState(null);
    setFailed(false);
    getMarketingOptOut(customerId)
      .then((s) => alive && setState(s))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [customerId]);

  const toggle = async (accepts: boolean) => {
    if (!state || saving) return;
    if (accepts) {
      // réinscrire : son accord d'abord
      const ok = await confirm({
        title: "Réactiver les offres ?",
        message:
          "Cette cliente a refusé les offres. Ne les réactivez que si elle vous l'a demandé.",
        confirmLabel: "Elle est d'accord",
      });
      if (!ok) return;
    }
    setSaving(true);
    try {
      const next = await setMarketingOptOut(customerId, !accepts);
      setState(next);
      onChange?.(next);
      toast.success(accepts ? "Offres réactivées." : "Elle ne recevra plus d'offres.");
    } catch {
      toast.error("Modification impossible.");
    } finally {
      setSaving(false);
    }
  };

  if (failed) {
    return (
      <p className="text-xs text-jenny-text-secondary px-1">
        Préférence d&apos;offres indisponible pour le moment.
      </p>
    );
  }

  const accepts = state ? !state.opt_out : true;
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-jenny-divider px-3 py-2">
      <div className="flex items-start gap-2 min-w-0">
        {accepts ? (
          <BellRing className="w-4 h-4 shrink-0 mt-0.5 text-jenny-text-secondary" />
        ) : (
          <BellOff className="w-4 h-4 shrink-0 mt-0.5 text-jenny-warning" />
        )}
        <div className="min-w-0">
          <p className="text-sm text-jenny-text">Offres et relances</p>
          <p className="text-[11px] text-jenny-text-secondary">
            {!state
              ? "Chargement…"
              : state.opt_out
                ? `Refusées${state.opt_out_at ? ` depuis le ${shortDay(state.opt_out_at)}` : ""} (STOP) · rappels de RDV maintenus`
                : "1 offre max par semaine · elle peut répondre STOP"}
          </p>
        </div>
      </div>
      <Switch
        size="sm"
        checked={accepts}
        disabled={!state || saving}
        onCheckedChange={toggle}
        aria-label="Recevoir les offres et relances"
      />
    </div>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import { KeyRound, Plus, Trash2, Copy, Check, ShieldAlert } from "lucide-react";
import {
  listApiKeys,
  createApiKey,
  revokeApiKey,
  type ApiKeyInfo,
  type ApiKeyCreated,
  ApiError,
} from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { RelativeTime } from "@/components/ui/relative-time";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm-dialog";

function extractError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    return (err.data as { detail?: string })?.detail || `Erreur ${err.status}`;
  }
  return fallback;
}

export function ApiKeysSection() {
  const toast = useToast();
  const confirm = useConfirm();
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  // Secret affiché une seule fois après création.
  const [fresh, setFresh] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setKeys(await listApiKeys());
    } catch {
      // silencieux
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreate = async () => {
    const n = name.trim();
    if (!n || creating) return;
    setCreating(true);
    try {
      const created = await createApiKey({ name: n });
      setFresh(created);
      setName("");
      setCopied(false);
      await load();
      toast.success("Clé API créée. Copiez-la maintenant.");
    } catch (err) {
      toast.error(extractError(err, "Création impossible."));
    } finally {
      setCreating(false);
    }
  };

  const copySecret = async () => {
    if (!fresh) return;
    try {
      await navigator.clipboard.writeText(fresh.secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Copie impossible.");
    }
  };

  const handleRevoke = async (k: ApiKeyInfo) => {
    const ok = await confirm({
      title: "Révoquer cette clé ?",
      message: `« ${k.name} » cessera immédiatement de fonctionner. Cette action est irréversible.`,
      confirmLabel: "Révoquer",
    });
    if (!ok) return;
    try {
      await revokeApiKey(k.id);
      if (fresh?.id === k.id) setFresh(null);
      await load();
      toast.success("Clé révoquée.");
    } catch (err) {
      toast.error(extractError(err, "Révocation impossible."));
    }
  };

  return (
    <Card className="p-6">
      <div className="flex items-center gap-3 mb-5">
        <KeyRound className="w-5 h-5 text-jenny-coral" />
        <h3 className="font-semibold text-jenny-text">Clés API</h3>
      </div>

      <p className="text-sm text-jenny-text-secondary mb-4">
        Générez des clés pour intégrer Jenny à vos systèmes (en-tête{" "}
        <span className="font-mono text-jenny-text">X-API-Key</span>). Le secret
        n&apos;est affiché qu&apos;une seule fois à la création.
      </p>

      {/* Secret fraîchement créé */}
      {fresh && (
        <div className="mb-4 p-3 rounded-xl bg-jenny-coral/[0.06] border border-jenny-coral/30">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-jenny-coral mb-2">
            <ShieldAlert className="w-3.5 h-3.5" />
            Copiez votre clé maintenant — elle ne sera plus jamais affichée
          </div>
          <div className="flex items-center gap-2">
            <code className="flex-1 min-w-0 text-xs font-mono bg-jenny-bg rounded-lg px-2.5 py-2 text-jenny-text break-all">
              {fresh.secret}
            </code>
            <button
              onClick={copySecret}
              aria-label="Copier la clé"
              className="p-2 rounded-lg text-jenny-text-secondary hover:text-jenny-coral hover:bg-jenny-coral/10 transition-colors flex-shrink-0"
            >
              {copied ? (
                <Check className="w-4 h-4 text-jenny-success" />
              ) : (
                <Copy className="w-4 h-4" />
              )}
            </button>
          </div>
        </div>
      )}

      {/* Création */}
      <div className="flex items-end gap-2 mb-5">
        <div className="flex-1">
          <Input
            label="Nom de la clé"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Ex: Intégration CRM"
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void handleCreate();
              }
            }}
          />
        </div>
        <Button onClick={handleCreate} isLoading={creating} disabled={!name.trim()}>
          <Plus className="w-4 h-4" />
          Générer
        </Button>
      </div>

      {/* Liste */}
      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 2 }).map((_, i) => (
            <div key={i} className="h-14 rounded-xl animate-shimmer" />
          ))}
        </div>
      ) : keys.length === 0 ? (
        <p className="text-sm text-jenny-text-secondary text-center py-4">
          Aucune clé API pour le moment.
        </p>
      ) : (
        <div className="space-y-2">
          {keys.map((k) => (
            <div
              key={k.id}
              className="flex items-center justify-between gap-3 p-3 rounded-xl border border-jenny-divider"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-jenny-text truncate">
                    {k.name}
                  </span>
                  <code className="text-[11px] font-mono text-jenny-text-secondary bg-jenny-bg rounded px-1.5 py-0.5">
                    {k.key_prefix}…
                  </code>
                </div>
                <p className="text-[11px] text-jenny-text-secondary mt-0.5">
                  Créée <RelativeTime date={k.created_at} />
                  {k.last_used_at ? (
                    <>
                      {" · "}utilisée <RelativeTime date={k.last_used_at} />
                    </>
                  ) : (
                    " · jamais utilisée"
                  )}
                </p>
              </div>
              <button
                onClick={() => handleRevoke(k)}
                aria-label={`Révoquer ${k.name}`}
                title="Révoquer"
                className="p-2 rounded-lg text-jenny-text-secondary hover:text-jenny-error hover:bg-jenny-error/10 transition-colors flex-shrink-0"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

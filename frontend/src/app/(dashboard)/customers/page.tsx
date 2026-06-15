"use client";

import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";
import { motion } from "framer-motion";
import { useRouter } from "next/navigation";
import { Search, Users, Mail, Phone, MessagesSquare, RefreshCw, Download, Upload } from "lucide-react";
import {
  listCustomers,
  exportCustomersCsv,
  importCustomersCsv,
  type CustomerListItem,
  ApiError,
} from "@/lib/api";
import { CustomerPanel } from "@/components/customer/customer-panel";
import { useToast } from "@/components/ui/toast";
import { Avatar } from "@/components/ui/avatar";
import { RelativeTime } from "@/components/ui/relative-time";
import { SkeletonCard } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { cn } from "@/lib/utils";
import { staggerContainer, staggerItem } from "@/lib/motion";

const PAGE = 36;

function extractError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    return `Erreur ${err.status}: ${
      (err.data as { detail?: string })?.detail || err.statusText
    }`;
  }
  return fallback;
}

export default function CustomersPage() {
  const router = useRouter();
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [customers, setCustomers] = useState<CustomerListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [isPaging, setIsPaging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [panelId, setPanelId] = useState<string | null>(null);

  const fetchCustomers = useCallback(
    async (reset = true) => {
      if (reset) setIsLoading(true);
      else setIsPaging(true);
      setError(null);
      try {
        const nextOffset = reset ? 0 : offset + PAGE;
        const data = await listCustomers({
          search: search.trim() || undefined,
          limit: PAGE,
          offset: nextOffset,
        });
        setTotal(data.total);
        setOffset(nextOffset);
        setCustomers((prev) =>
          reset ? data.customers : [...prev, ...data.customers]
        );
      } catch (err) {
        setError(extractError(err, "Impossible de charger les clients."));
      } finally {
        setIsLoading(false);
        setIsPaging(false);
      }
    },
    [search, offset]
  );

  // Recherche serveur (debounce 350 ms).
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      fetchCustomers(true);
      return;
    }
    const t = setTimeout(() => fetchCustomers(true), 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  // Ouverture directe d'une fiche via ?open=<id> (depuis la recherche globale).
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("open");
    if (id) {
      setPanelId(id);
      window.history.replaceState({}, "", "/customers");
    }
  }, []);

  const handleImport = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // permet de réimporter le même fichier
    if (!file) return;
    try {
      const res = await importCustomersCsv(file);
      toast.success(
        `${res.created} client(s) importé(s)${res.skipped ? `, ${res.skipped} ignoré(s)` : ""}.`
      );
      fetchCustomers(true);
    } catch {
      toast.error("Import impossible. Vérifiez le format du CSV.");
    }
  };

  const hasMore = customers.length < total;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-6xl mx-auto p-4 md:p-6 space-y-5">
        {/* En-tête */}
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="font-mono text-[11px] tracking-[0.22em] uppercase text-jenny-coral mb-2">— qui vous écrit —</div>
            <h1 className="font-display text-[clamp(28px,4vw,36px)] leading-[1] tracking-[-0.02em] text-jenny-text">
              Vos <span className="italic text-jenny-coral">clients.</span>
            </h1>
            <p className="text-sm text-jenny-text-secondary mt-0.5">
              {total} client{total > 1 ? "s" : ""} · tous canaux confondus
            </p>
          </div>
          <div className="flex items-center gap-1">
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={handleImport}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              title="Importer des clients (CSV)"
              aria-label="Importer des clients depuis un CSV"
              className="p-2 rounded-lg text-jenny-text-secondary hover:text-jenny-coral hover:bg-jenny-coral/10 transition-colors"
            >
              <Upload className="w-4 h-4" />
            </button>
            <button
              onClick={() =>
                exportCustomersCsv().catch(() => toast.error("Export impossible."))
              }
              title="Exporter en CSV"
              aria-label="Exporter les clients en CSV"
              className="p-2 rounded-lg text-jenny-text-secondary hover:text-jenny-coral hover:bg-jenny-coral/10 transition-colors"
            >
              <Download className="w-4 h-4" />
            </button>
            <button
              onClick={() => fetchCustomers(true)}
              disabled={isLoading}
              title="Rafraîchir"
              aria-label="Rafraîchir la liste"
              className="p-2 rounded-lg text-jenny-text-secondary hover:text-jenny-coral hover:bg-jenny-coral/10 disabled:opacity-50 transition-colors"
            >
              <RefreshCw className={cn("w-4 h-4", isLoading && "animate-spin")} />
            </button>
          </div>
        </div>

        {/* Recherche */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-jenny-text-secondary" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Rechercher par nom, email ou téléphone…"
            className="w-full h-11 pl-10 pr-4 rounded-xl bg-jenny-surface border border-jenny-divider text-sm text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:ring-2 focus:ring-jenny-coral/30 focus:border-jenny-coral transition-all"
          />
        </div>

        {/* Contenu */}
        {error ? (
          <ErrorState message={error} onRetry={() => fetchCustomers(true)} />
        ) : isLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        ) : customers.length === 0 ? (
          <EmptyState
            icon={<Users className="w-7 h-7" />}
            title={search ? "Aucun client trouvé" : "Aucun client pour le moment"}
            description={
              search
                ? "Essayez un autre nom, email ou numéro."
                : "Les clients apparaîtront ici dès qu'un message arrivera."
            }
          />
        ) : (
          <>
            <motion.div
              variants={staggerContainer}
              initial="hidden"
              animate="show"
              className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3"
            >
              {customers.map((c) => (
                <motion.button
                  key={c.id}
                  variants={staggerItem}
                  onClick={() => setPanelId(c.id)}
                  className="group text-left bg-jenny-surface border border-jenny-divider rounded-2xl p-4 hover:border-jenny-coral/40 hover:shadow-md hover:shadow-jenny-coral/5 transition-all"
                >
                  <div className="flex items-start gap-3">
                    <Avatar name={c.full_name} email={c.email} />
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-jenny-text truncate group-hover:text-jenny-coral transition-colors">
                        {c.full_name || "Client"}
                      </p>
                      {c.email && (
                        <p className="flex items-center gap-1.5 text-xs text-jenny-text-secondary truncate mt-0.5">
                          <Mail className="w-3 h-3 shrink-0" />
                          <span className="truncate">{c.email}</span>
                        </p>
                      )}
                      {c.phone && (
                        <p className="flex items-center gap-1.5 text-xs text-jenny-text-secondary mt-0.5">
                          <Phone className="w-3 h-3 shrink-0" />
                          {c.phone}
                        </p>
                      )}
                    </div>
                  </div>

                  {c.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-3">
                      {c.tags.slice(0, 3).map((t) => (
                        <span
                          key={t}
                          className="bg-jenny-coral/10 text-jenny-coral text-[10px] font-medium rounded-full px-2 py-0.5"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="flex items-center justify-between mt-3 pt-3 border-t border-jenny-divider/60 text-xs text-jenny-text-secondary">
                    <span className="flex items-center gap-1.5">
                      <MessagesSquare className="w-3.5 h-3.5" />
                      {c.conversation_count} conversation{c.conversation_count > 1 ? "s" : ""}
                    </span>
                    {c.last_seen_at && <RelativeTime date={c.last_seen_at} />}
                  </div>
                </motion.button>
              ))}
            </motion.div>

            {hasMore && (
              <div className="flex justify-center pt-2">
                <button
                  onClick={() => fetchCustomers(false)}
                  disabled={isPaging}
                  className="h-10 px-5 rounded-xl bg-jenny-surface border border-jenny-divider text-sm font-medium text-jenny-text hover:border-jenny-coral/40 disabled:opacity-50 transition-colors"
                >
                  {isPaging ? "Chargement…" : "Charger plus"}
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* Fiche client 360° (tiroir réutilisé) */}
      <CustomerPanel
        customerId={panelId}
        onClose={() => setPanelId(null)}
        onOpenConversation={(id) => {
          setPanelId(null);
          router.push(`/conversations?open=${id}`);
        }}
      />
    </div>
  );
}

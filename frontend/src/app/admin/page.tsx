"use client";

import { useCallback, useEffect, useMemo, useState, type ComponentType } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowLeft,
  BarChart3,
  Building2,
  Check,
  Loader2,
  LogOut,
  MessageSquare,
  Power,
  Shield,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { useToast } from "@/components/ui/toast";
import {
  ApiError,
  getAdminOverview,
  listAdminBusinesses,
  listAdminUsers,
  setBusinessActive,
  setUserSuperuser,
  type AdminBusiness,
  type AdminOverview,
  type AdminUserItem,
} from "@/lib/api";

// ── Console super-admin plateforme (DA « Jenny Front », variante nuit profonde).
// Page autonome plein écran (hors groupe (dashboard)) : elle gère elle-même son
// layout et son gating. Réservée aux comptes `is_superuser`. Toutes les données
// proviennent des vrais endpoints /api/v1/admin/* ; les actions (activer/suspendre
// une entreprise, donner/retirer le rôle admin) sont réelles, avec confirmation
// et toast. La page n'appelle JAMAIS les APIs admin pour un non-admin (403).

const PAGE_BG =
  "radial-gradient(ellipse at 75% -5%, rgba(255,127,106,0.16) 0%, transparent 52%), radial-gradient(ellipse at 0% 90%, rgba(114,132,168,0.12) 0%, transparent 50%), var(--color-jenny-night)";

type TabId = "overview" | "businesses" | "users";

const TABS: { id: TabId; label: string; icon: ComponentType<{ className?: string }> }[] = [
  { id: "overview", label: "Vue d'ensemble", icon: BarChart3 },
  { id: "businesses", label: "Entreprises", icon: Building2 },
  { id: "users", label: "Comptes", icon: Users },
];

// Formatage FR des grands nombres (espaces fines insécables côté navigateur).
const NUMBER_FMT = new Intl.NumberFormat("fr-FR");

function formatNumber(n: number): string {
  return NUMBER_FMT.format(n);
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" });
}

// Récupère un message d'erreur lisible (détail FastAPI si présent).
function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    const data = err.data as { detail?: unknown } | undefined;
    const detail = data?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
  }
  return fallback;
}

const cardVariants = {
  hidden: { opacity: 0, y: 14 },
  show: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.34, delay: i * 0.05, ease: [0.16, 1, 0.3, 1] as const },
  }),
};

export default function AdminPage() {
  const { user, isAuthenticated, isLoading, logout } = useAuth();
  const router = useRouter();
  const toast = useToast();

  const isSuperuser = !!user?.is_superuser;

  const [tab, setTab] = useState<TabId>("overview");

  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [businesses, setBusinesses] = useState<AdminBusiness[]>([]);
  const [users, setUsers] = useState<AdminUserItem[]>([]);

  const [dataLoading, setDataLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // IDs en cours de mutation → désactive le bouton + spinner local.
  const [pendingBiz, setPendingBiz] = useState<string | null>(null);
  const [pendingUser, setPendingUser] = useState<string | null>(null);

  // ── Gating : redirection si non connecté (jamais d'appel admin pour autrui). ──
  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isAuthenticated, isLoading, router]);

  // ── Chargement initial de la console (uniquement pour un super-admin). ──
  const loadAll = useCallback(async () => {
    setDataLoading(true);
    setLoadError(null);
    try {
      const [ov, biz, usr] = await Promise.all([
        getAdminOverview(),
        listAdminBusinesses(),
        listAdminUsers(),
      ]);
      setOverview(ov);
      setBusinesses(biz);
      setUsers(usr);
    } catch (err) {
      setLoadError(errorMessage(err, "Impossible de charger la console d'administration."));
    } finally {
      setDataLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isAuthenticated && isSuperuser) {
      void loadAll();
    }
  }, [isAuthenticated, isSuperuser, loadAll]);

  // ── Action : activer / suspendre une entreprise. ──
  async function handleToggleBusiness(biz: AdminBusiness) {
    const next = !biz.is_active;
    const verb = next ? "réactiver" : "suspendre";
    if (!window.confirm(`Voulez-vous ${verb} « ${biz.name} » ?`)) return;
    setPendingBiz(biz.id);
    try {
      const updated = await setBusinessActive(biz.id, next);
      setBusinesses((list) => list.map((b) => (b.id === biz.id ? { ...b, ...updated } : b)));
      toast.success(next ? `« ${biz.name} » réactivée.` : `« ${biz.name} » suspendue.`);
    } catch (err) {
      toast.error(errorMessage(err, `Échec : impossible de ${verb} cette entreprise.`));
    } finally {
      setPendingBiz(null);
    }
  }

  // ── Action : accorder / retirer le rôle super-admin. ──
  // L'API interdit de retirer ses propres droits → on remonte le message dédié.
  async function handleToggleSuperuser(target: AdminUserItem) {
    const next = !target.is_superuser;
    const who = target.full_name || target.email;
    const verb = next ? "promouvoir administrateur" : "retirer les droits administrateur de";
    if (!window.confirm(`Voulez-vous ${verb} « ${who} » ?`)) return;
    setPendingUser(target.id);
    try {
      const updated = await setUserSuperuser(target.id, next);
      setUsers((list) => list.map((u) => (u.id === target.id ? { ...u, ...updated } : u)));
      toast.success(
        next ? `« ${who} » est désormais administrateur.` : `Droits administrateur retirés à « ${who} ».`
      );
    } catch (err) {
      toast.error(errorMessage(err, "Échec : impossible de modifier ce compte."));
    } finally {
      setPendingUser(null);
    }
  }

  const overviewCards = useMemo(
    () => [
      { key: "businesses", label: "Entreprises", icon: Building2, value: overview?.businesses },
      { key: "users", label: "Comptes", icon: Users, value: overview?.users },
      { key: "conversations", label: "Conversations", icon: MessageSquare, value: overview?.conversations },
      { key: "messages", label: "Messages", icon: MessageSquare, value: overview?.messages },
      { key: "customers", label: "Clients", icon: Users, value: overview?.customers },
    ],
    [overview]
  );

  // ── Écran de chargement de l'auth (avant résolution). ──
  if (isLoading || !isAuthenticated) {
    return <FullScreenLoader label="Vérification de la session…" />;
  }

  // ── Accès refusé : compte authentifié mais non super-admin. ──
  if (!isSuperuser) {
    return (
      <div
        className="min-h-screen w-full flex items-center justify-center px-6 text-[#F4F1ED]"
        style={{ background: PAGE_BG, fontFamily: "var(--font-sans)" }}
      >
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="max-w-[440px] w-full text-center rounded-[22px] p-9 md:p-11"
          style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
        >
          <span
            className="w-14 h-14 rounded-2xl mx-auto mb-6 flex items-center justify-center text-jenny-coral"
            style={{ background: "rgba(255,127,106,0.12)" }}
          >
            <Shield className="w-7 h-7" />
          </span>
          <div className="font-mono text-[11px] tracking-[0.28em] uppercase text-jenny-coral mb-3">
            — accès restreint —
          </div>
          <h1 className="font-display text-[34px] md:text-[40px] leading-[1.05] tracking-[-0.02em] mb-3.5">
            Accès réservé aux <span className="italic text-jenny-coral">administrateurs.</span>
          </h1>
          <p className="text-[14.5px] leading-[1.55] text-[#F4F1ED]/60 mb-8">
            Cette console est réservée aux administrateurs de la plateforme. Votre compte
            n&apos;a pas les droits nécessaires.
          </p>
          <button
            type="button"
            onClick={() => router.push("/chat")}
            className="h-11 px-5 rounded-xl text-[14px] font-semibold inline-flex items-center gap-2 bg-jenny-coral text-white hover:bg-jenny-coral-dark transition-colors"
            style={{ boxShadow: "0 4px 14px rgba(255,127,106,0.25)" }}
          >
            <ArrowLeft className="w-4 h-4" />
            Retour à l&apos;application
          </button>
        </motion.div>
      </div>
    );
  }

  // ── Console (super-admin). ──
  return (
    <div
      className="min-h-screen w-full flex flex-col text-[#F4F1ED]"
      style={{ background: PAGE_BG, fontFamily: "var(--font-sans)" }}
    >
      {/* ── Barre supérieure ── */}
      <header
        className="sticky top-0 z-20 flex items-center gap-4 px-5 md:px-10 py-4"
        style={{ backdropFilter: "blur(12px)", background: "rgba(14,11,20,0.72)", borderBottom: "1px solid rgba(255,255,255,0.07)" }}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="w-9 h-9 rounded-[10px] overflow-hidden bg-jenny-coral block shrink-0">
            <Image src="/jenny.png" alt="Jenny" width={36} height={36} className="object-cover w-full h-full" />
          </span>
          <div className="min-w-0">
            <div className="text-[15px] font-bold tracking-[-0.02em] leading-tight">
              Jenny <span className="text-[#F4F1ED]/40">·</span> Admin
            </div>
            <div className="font-mono text-[10.5px] tracking-[0.16em] uppercase text-jenny-coral/80 leading-tight">
              Console plateforme
            </div>
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2 md:gap-3">
          <span className="hidden sm:block font-mono text-[12px] text-[#F4F1ED]/55 truncate max-w-[220px]" title={user?.email}>
            {user?.email}
          </span>
          <button
            type="button"
            onClick={() => router.push("/chat")}
            className="h-9 px-3.5 rounded-lg text-[13px] font-semibold inline-flex items-center gap-1.5 text-[#F4F1ED]/85 transition-colors hover:bg-white/10"
            style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)" }}
          >
            <ArrowLeft className="w-4 h-4" />
            <span className="hidden md:inline">Quitter l&apos;admin</span>
          </button>
          <button
            type="button"
            onClick={() => {
              logout();
              router.replace("/login");
            }}
            className="h-9 px-3.5 rounded-lg text-[13px] font-semibold inline-flex items-center gap-1.5 text-[#F4F1ED]/70 hover:text-[#F4F1ED] transition-colors hover:bg-white/10"
          >
            <LogOut className="w-4 h-4" />
            <span className="hidden md:inline">Déconnexion</span>
          </button>
        </div>
      </header>

      {/* ── Corps ── */}
      <div className="flex-1 overflow-y-auto">
        <div className="px-5 md:px-10 py-8 md:py-10 max-w-[1180px] mx-auto w-full">
          {/* Titre */}
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
            <div className="font-mono text-[11px] tracking-[0.28em] uppercase text-jenny-coral mb-3">
              — supervision —
            </div>
            <h1 className="font-display text-[40px] md:text-[52px] leading-[1.02] tracking-[-0.025em] mb-7">
              Console <span className="italic text-jenny-coral">admin.</span>
            </h1>
          </motion.div>

          {/* Onglets */}
          <div
            className="inline-flex flex-wrap gap-1 p-1 rounded-xl mb-8"
            style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
          >
            {TABS.map((t) => {
              const Icon = t.icon;
              const active = tab === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setTab(t.id)}
                  aria-pressed={active}
                  className="relative h-9 px-3.5 rounded-lg text-[13px] font-semibold inline-flex items-center gap-2 transition-colors"
                  style={{
                    color: active ? "#FFFFFF" : "rgba(244,241,237,0.6)",
                  }}
                >
                  {active && (
                    <motion.span
                      layoutId="admin-tab-bg"
                      className="absolute inset-0 rounded-lg bg-jenny-coral"
                      style={{ boxShadow: "0 4px 14px rgba(255,127,106,0.25)" }}
                      transition={{ type: "spring", stiffness: 380, damping: 32 }}
                    />
                  )}
                  <Icon className="w-4 h-4 relative z-10" />
                  <span className="relative z-10">{t.label}</span>
                </button>
              );
            })}
          </div>

          {/* Erreur de chargement globale */}
          {loadError && !dataLoading && (
            <div
              className="rounded-2xl p-5 mb-6 flex flex-col sm:flex-row sm:items-center gap-3"
              style={{ background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)" }}
            >
              <X className="w-5 h-5 text-jenny-error shrink-0" />
              <span className="text-[14px] text-[#F4F1ED]/85 flex-1">{loadError}</span>
              <button
                type="button"
                onClick={() => void loadAll()}
                className="h-9 px-4 rounded-lg text-[13px] font-semibold bg-jenny-coral text-white hover:bg-jenny-coral-dark transition-colors shrink-0"
              >
                Réessayer
              </button>
            </div>
          )}

          {/* Contenu par onglet */}
          <AnimatePresence mode="wait">
            <motion.div
              key={tab}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.26, ease: [0.16, 1, 0.3, 1] }}
            >
              {tab === "overview" && (
                <OverviewSection loading={dataLoading} cards={overviewCards} />
              )}
              {tab === "businesses" && (
                <BusinessesSection
                  loading={dataLoading}
                  businesses={businesses}
                  pendingId={pendingBiz}
                  onToggle={handleToggleBusiness}
                />
              )}
              {tab === "users" && (
                <UsersSection
                  loading={dataLoading}
                  users={users}
                  currentUserId={user?.id}
                  pendingId={pendingUser}
                  onToggle={handleToggleSuperuser}
                />
              )}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

// ── Sections ─────────────────────────────────────────────────────────────────

function OverviewSection({
  loading,
  cards,
}: {
  loading: boolean;
  cards: { key: string; label: string; icon: ComponentType<{ className?: string }>; value: number | undefined }[];
}) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="h-[136px] rounded-2xl animate-pulse"
            style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.06)" }}
          />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
      {cards.map((c, i) => {
        const Icon = c.icon;
        return (
          <motion.div
            key={c.key}
            custom={i}
            variants={cardVariants}
            initial="hidden"
            animate="show"
            className="rounded-2xl p-5"
            style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
          >
            <span
              className="w-10 h-10 rounded-[11px] flex items-center justify-center mb-4 text-jenny-coral"
              style={{ background: "rgba(255,127,106,0.12)" }}
            >
              <Icon className="w-[18px] h-[18px]" />
            </span>
            <div className="font-display text-[40px] leading-none tracking-[-0.02em] mb-1.5">
              {formatNumber(c.value ?? 0)}
            </div>
            <div className="font-mono text-[10.5px] tracking-[0.16em] uppercase text-[#F4F1ED]/50">
              {c.label}
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}

function SectionShell({
  title,
  count,
  children,
}: {
  title: string;
  count: number | null;
  children: React.ReactNode;
}) {
  return (
    <div
      className="rounded-[20px] overflow-hidden"
      style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}
    >
      <div
        className="flex items-center gap-3 px-5 py-4"
        style={{ borderBottom: "1px solid rgba(255,255,255,0.07)" }}
      >
        <span className="text-[15px] font-semibold tracking-[-0.01em]">{title}</span>
        {count !== null && (
          <span className="font-mono text-[11px] tracking-[0.1em] text-[#F4F1ED]/45">
            {formatNumber(count)}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}

function ListSkeleton() {
  return (
    <div className="p-3 flex flex-col gap-2">
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="h-[68px] rounded-xl animate-pulse"
          style={{ background: "rgba(255,255,255,0.04)" }}
        />
      ))}
    </div>
  );
}

function EmptyRow({ label }: { label: string }) {
  return <div className="px-5 py-10 text-center text-[14px] text-[#F4F1ED]/45">{label}</div>;
}

function StatusBadge({ active }: { active: boolean }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-mono font-semibold tracking-[0.06em] shrink-0"
      style={
        active
          ? { background: "rgba(16,185,129,0.14)", color: "var(--color-jenny-success)" }
          : { background: "rgba(239,68,68,0.14)", color: "var(--color-jenny-error)" }
      }
    >
      {active ? <Check className="w-[11px] h-[11px]" /> : <X className="w-[11px] h-[11px]" />}
      {active ? "ACTIVE" : "SUSPENDUE"}
    </span>
  );
}

function MetaPill({ label, value }: { label: string; value: string }) {
  return (
    <span className="font-mono text-[11px] text-[#F4F1ED]/55 whitespace-nowrap">
      <span className="text-[#F4F1ED]/35">{label} </span>
      {value}
    </span>
  );
}

function BusinessesSection({
  loading,
  businesses,
  pendingId,
  onToggle,
}: {
  loading: boolean;
  businesses: AdminBusiness[];
  pendingId: string | null;
  onToggle: (biz: AdminBusiness) => void;
}) {
  return (
    <SectionShell title="Entreprises" count={loading ? null : businesses.length}>
      {loading ? (
        <ListSkeleton />
      ) : businesses.length === 0 ? (
        <EmptyRow label="Aucune entreprise pour le moment." />
      ) : (
        <ul className="divide-y" style={{ borderColor: "rgba(255,255,255,0.06)" }}>
          {businesses.map((b) => {
            const busy = pendingId === b.id;
            return (
              <li
                key={b.id}
                className="px-5 py-4 flex flex-col lg:flex-row lg:items-center gap-3 lg:gap-4 hover:bg-white/[0.02] transition-colors"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <span className="text-[14.5px] font-semibold text-[#F4F1ED] truncate">{b.name}</span>
                    <StatusBadge active={b.is_active} />
                  </div>
                  <div className="flex items-center gap-x-4 gap-y-1 flex-wrap mt-1.5">
                    <span className="font-mono text-[11.5px] text-jenny-coral/80">/{b.slug}</span>
                    {b.email && (
                      <span className="text-[12.5px] text-[#F4F1ED]/55 truncate">{b.email}</span>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-4 lg:gap-5 flex-wrap">
                  <MetaPill label="MEMBRES" value={formatNumber(b.members)} />
                  <MetaPill label="CONV." value={formatNumber(b.conversations)} />
                  <MetaPill label="CRÉÉE" value={formatDate(b.created_at)} />
                </div>

                <button
                  type="button"
                  onClick={() => onToggle(b)}
                  disabled={busy}
                  className="h-9 px-3.5 rounded-lg text-[12.5px] font-semibold inline-flex items-center gap-1.5 transition-colors shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
                  style={
                    b.is_active
                      ? { background: "rgba(239,68,68,0.12)", border: "1px solid rgba(239,68,68,0.3)", color: "var(--color-jenny-error)" }
                      : { background: "rgba(16,185,129,0.12)", border: "1px solid rgba(16,185,129,0.3)", color: "var(--color-jenny-success)" }
                  }
                >
                  {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Power className="w-4 h-4" />}
                  {b.is_active ? "Suspendre" : "Réactiver"}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </SectionShell>
  );
}

function UsersSection({
  loading,
  users,
  currentUserId,
  pendingId,
  onToggle,
}: {
  loading: boolean;
  users: AdminUserItem[];
  currentUserId: string | undefined;
  pendingId: string | null;
  onToggle: (user: AdminUserItem) => void;
}) {
  return (
    <SectionShell title="Comptes" count={loading ? null : users.length}>
      {loading ? (
        <ListSkeleton />
      ) : users.length === 0 ? (
        <EmptyRow label="Aucun compte pour le moment." />
      ) : (
        <ul className="divide-y" style={{ borderColor: "rgba(255,255,255,0.06)" }}>
          {users.map((u) => {
            const busy = pendingId === u.id;
            const isSelf = currentUserId === u.id;
            return (
              <li
                key={u.id}
                className="px-5 py-4 flex flex-col lg:flex-row lg:items-center gap-3 lg:gap-4 hover:bg-white/[0.02] transition-colors"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <span className="text-[14.5px] font-semibold text-[#F4F1ED] truncate">
                      {u.full_name || u.email}
                    </span>
                    {u.is_superuser && (
                      <span
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-mono font-semibold tracking-[0.06em] shrink-0 text-jenny-coral"
                        style={{ background: "rgba(255,127,106,0.14)" }}
                      >
                        <ShieldCheck className="w-[11px] h-[11px]" />
                        ADMIN
                      </span>
                    )}
                    {u.email_verified ? (
                      <span
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-mono font-semibold tracking-[0.06em] shrink-0"
                        style={{ background: "rgba(16,185,129,0.14)", color: "var(--color-jenny-success)" }}
                      >
                        <Check className="w-[11px] h-[11px]" />
                        VÉRIFIÉ
                      </span>
                    ) : (
                      <span
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-mono font-semibold tracking-[0.06em] shrink-0"
                        style={{ background: "rgba(245,158,11,0.14)", color: "var(--color-jenny-warning)" }}
                      >
                        NON VÉRIFIÉ
                      </span>
                    )}
                  </div>
                  {u.full_name && (
                    <div className="text-[12.5px] text-[#F4F1ED]/55 truncate mt-1.5">{u.email}</div>
                  )}
                </div>

                <div className="flex items-center gap-4 lg:gap-5 flex-wrap">
                  <MetaPill label="ENTREPRISES" value={formatNumber(u.businesses)} />
                  <MetaPill label="CRÉÉ" value={formatDate(u.created_at)} />
                </div>

                <button
                  type="button"
                  onClick={() => onToggle(u)}
                  disabled={busy || isSelf}
                  title={isSelf ? "Vous ne pouvez pas modifier vos propres droits." : undefined}
                  className="h-9 px-3.5 rounded-lg text-[12.5px] font-semibold inline-flex items-center gap-1.5 transition-colors shrink-0 disabled:opacity-40 disabled:cursor-not-allowed"
                  style={
                    u.is_superuser
                      ? { background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.12)", color: "rgba(244,241,237,0.85)" }
                      : { background: "rgba(255,127,106,0.12)", border: "1px solid rgba(255,127,106,0.3)", color: "var(--color-jenny-coral)" }
                  }
                >
                  {busy ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Shield className="w-4 h-4" />
                  )}
                  {u.is_superuser ? "Retirer admin" : "Promouvoir admin"}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </SectionShell>
  );
}

// ── Loader plein écran (variante nuit, cohérent avec la DA admin). ──
function FullScreenLoader({ label }: { label: string }) {
  return (
    <div
      className="min-h-screen w-full flex items-center justify-center"
      style={{ background: PAGE_BG, fontFamily: "var(--font-sans)" }}
    >
      <div className="flex flex-col items-center gap-5">
        <div className="relative w-14 h-14">
          <motion.span
            className="absolute inset-0 rounded-2xl border-2 border-jenny-coral/25 border-t-jenny-coral"
            animate={{ rotate: 360 }}
            transition={{ duration: 0.9, ease: "linear", repeat: Infinity }}
          />
          <motion.div
            className="absolute inset-[5px] rounded-xl bg-jenny-coral flex items-center justify-center"
            animate={{ scale: [1, 0.9, 1] }}
            transition={{ duration: 1.4, ease: "easeInOut", repeat: Infinity }}
          >
            <span className="text-white font-bold text-lg">J</span>
          </motion.div>
        </div>
        <p className="text-[#F4F1ED]/55 text-sm">{label}</p>
      </div>
    </div>
  );
}

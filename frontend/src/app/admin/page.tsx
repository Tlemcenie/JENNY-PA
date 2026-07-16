"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { BarChart3, Building2, Cpu, ScrollText, Users, X } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { useToast } from "@/components/ui/toast";
import { ConfirmProvider } from "@/components/ui/confirm-dialog";
import { slideInLeft, slideInRight } from "@/lib/motion";
import {
  getAdminOverview,
  listAdminBusinesses,
  listAdminUsers,
  setBusinessActive,
  setUserSuperuser,
  type AdminBusiness,
  type AdminOverview,
  type AdminUserItem,
} from "@/lib/api";
import {
  AccessDenied,
  AdminFullScreenLoader,
  AdminScreen,
  AdminTabBar,
  AdminTopbar,
  type AdminTab,
} from "@/components/admin/admin-shell";
import { errorMessage } from "@/components/admin/admin-shared";
import { OverviewTab } from "@/components/admin/overview-tab";
import { BusinessesTab } from "@/components/admin/businesses-tab";
import { UsersTab } from "@/components/admin/users-tab";
import { AuditTab } from "@/components/admin/audit-tab";
import { PlatformBrainCard } from "@/components/admin/platform-brain-card";

// console super-admin plateforme

type TabId = "overview" | "businesses" | "users" | "audit" | "brain";

const TABS: AdminTab<TabId>[] = [
  { id: "overview", label: "Vue d'ensemble", icon: BarChart3 },
  { id: "businesses", label: "Entreprises", icon: Building2 },
  { id: "users", label: "Comptes", icon: Users },
  { id: "audit", label: "Journal d'audit", icon: ScrollText },
  { id: "brain", label: "Cerveau plateforme", icon: Cpu },
];

const TAB_INDEX: Record<TabId, number> = {
  overview: 0,
  businesses: 1,
  users: 2,
  audit: 3,
  brain: 4,
};

export default function AdminPage() {
  const { user, isAuthenticated, isLoading, logout } = useAuth();
  const router = useRouter();
  const toast = useToast();
  const reduce = useReducedMotion();

  const isSuperuser = !!user?.is_superuser;

  const [tab, setTab] = useState<TabId>("overview");
  // sens du glissement
  const prevIndex = useRef(TAB_INDEX.overview);

  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [businesses, setBusinesses] = useState<AdminBusiness[]>([]);
  const [users, setUsers] = useState<AdminUserItem[]>([]);

  const [dataLoading, setDataLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // ids en mutation
  const [pendingBiz, setPendingBiz] = useState<string | null>(null);
  const [pendingUser, setPendingUser] = useState<string | null>(null);

  // redirection si non connecté
  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isAuthenticated, isLoading, router]);

  // chargement initial
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

  const selectTab = useCallback((next: TabId) => {
    setTab((cur) => {
      // mémorise l'onglet quitté
      prevIndex.current = TAB_INDEX[cur];
      return next;
    });
  }, []);

  // activer / suspendre une entreprise
  async function handleToggleBusiness(biz: AdminBusiness) {
    const next = !biz.is_active;
    setPendingBiz(biz.id);
    try {
      const updated = await setBusinessActive(biz.id, next);
      setBusinesses((list) => list.map((b) => (b.id === biz.id ? { ...b, ...updated } : b)));
      toast.success(next ? `« ${biz.name} » réactivée.` : `« ${biz.name} » suspendue.`);
    } catch (err) {
      toast.error(errorMessage(err, `Échec : impossible de modifier « ${biz.name} ».`));
    } finally {
      setPendingBiz(null);
    }
  }

  // donner / retirer le rôle admin
  async function handleToggleSuperuser(target: AdminUserItem) {
    const next = !target.is_superuser;
    const who = target.full_name || target.email;
    setPendingUser(target.id);
    try {
      const updated = await setUserSuperuser(target.id, next);
      setUsers((list) => list.map((u) => (u.id === target.id ? { ...u, ...updated } : u)));
      toast.success(
        next
          ? `« ${who} » est désormais administrateur.`
          : `Droits administrateur retirés à « ${who} ».`
      );
    } catch (err) {
      toast.error(errorMessage(err, "Échec : impossible de modifier ce compte."));
    } finally {
      setPendingUser(null);
    }
  }

  // écran de chargement auth
  if (isLoading || !isAuthenticated) {
    return <AdminFullScreenLoader label="Vérification de la session…" />;
  }

  // accès refusé
  if (!isSuperuser) {
    return <AccessDenied onBack={() => router.push("/chat")} />;
  }

  // sens de la transition
  const goingForward = TAB_INDEX[tab] >= prevIndex.current;
  const tabVariants = reduce ? undefined : goingForward ? slideInRight : slideInLeft;

  // console
  return (
    <ConfirmProvider>
      <AdminScreen>
        <AdminTopbar
          email={user?.email}
          onExit={() => router.push("/chat")}
          onLogout={() => {
            logout();
            router.replace("/login");
          }}
        />

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
            <AdminTabBar tabs={TABS} active={tab} onSelect={selectTab} />

            {/* erreur de chargement */}
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

            {/* contenu par onglet */}
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={tab}
                variants={tabVariants}
                initial="hidden"
                animate="show"
                exit="hidden"
              >
                {tab === "overview" && <OverviewTab loading={dataLoading} overview={overview} />}
                {tab === "businesses" && (
                  <BusinessesTab
                    loading={dataLoading}
                    businesses={businesses}
                    pendingId={pendingBiz}
                    onToggle={handleToggleBusiness}
                  />
                )}
                {tab === "users" && (
                  <UsersTab
                    loading={dataLoading}
                    users={users}
                    currentUserId={user?.id}
                    pendingId={pendingUser}
                    onToggle={handleToggleSuperuser}
                  />
                )}
                {tab === "audit" && <AuditTab />}
                {tab === "brain" && <PlatformBrainCard />}
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </AdminScreen>
    </ConfirmProvider>
  );
}

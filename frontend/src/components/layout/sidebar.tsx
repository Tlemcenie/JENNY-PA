"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { getConversationStats } from "@/lib/api";
import {
  LayoutDashboard,
  MessageCircle,
  MessagesSquare,
  Users,
  Contact,
  Radio,
  BookOpen,
  Brain,
  BarChart3,
  TrendingUp,
  Lightbulb,
  Megaphone,
  Gauge,
  Cpu,
  Scissors,
  CalendarDays,
  Shield,
  Settings,
  LogOut,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  FlaskConical,
  Sparkles,
  Menu,
  X,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth-context";
import { JennyAvatar } from "@/components/ui/jenny-avatar";
import { ThemeSwitch } from "@/components/ui/theme-switch";
import {
  useRealtimeRefresh,
  useRealtimeStatus,
} from "@/components/providers/realtime-provider";

type NavItem = { href: string; icon: LucideIcon; labelKey: string; accent?: boolean };

// menu principal
const mainItems: NavItem[] = [
  { href: "/dashboard", icon: LayoutDashboard, labelKey: "nav.dashboard" },
  { href: "/chat", icon: MessageCircle, labelKey: "nav.chat", accent: true },
  { href: "/assistant", icon: Sparkles, labelKey: "nav.assistant" },
  { href: "/conversations", icon: MessagesSquare, labelKey: "nav.conversations" },
  { href: "/calendar", icon: CalendarDays, labelKey: "nav.calendar" },
  { href: "/team", icon: Users, labelKey: "nav.team" },
  { href: "/campaigns", icon: Megaphone, labelKey: "nav.campaigns" },
  { href: "/prestations", icon: Scissors, labelKey: "nav.prestations" },
  { href: "/brain", icon: Brain, labelKey: "nav.brain" },
  { href: "/knowledge", icon: BookOpen, labelKey: "nav.knowledge" },
  { href: "/learning", icon: Lightbulb, labelKey: "nav.learning" },
  { href: "/analytics", icon: BarChart3, labelKey: "nav.analytics" },
  { href: "/stats", icon: TrendingUp, labelKey: "nav.stats" },
  { href: "/channels", icon: Radio, labelKey: "nav.channels" },
];

// vitrine technique, repliée
const labItems: NavItem[] = [
  { href: "/efficacy", icon: Gauge, labelKey: "nav.efficacy" },
  { href: "/lab", icon: Cpu, labelKey: "nav.lab" },
];

// section compte
const accountItems: NavItem[] = [
  { href: "/customers", icon: Contact, labelKey: "nav.customers" },
  { href: "/profile", icon: Settings, labelKey: "nav.settings" },
];

const LAB_KEY = "jenny-nav-lab-open";

function isActivePath(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(href + "/");
}

function NavLink({
  item,
  pathname,
  expanded,
  onClose,
  badge,
}: {
  item: NavItem;
  pathname: string;
  expanded: boolean;
  onClose: () => void;
  badge?: number;
}) {
  const { t } = useTranslation();
  const isActive = isActivePath(pathname, item.href);
  const label = t(item.labelKey);
  return (
    <Link
      href={item.href}
      onClick={onClose}
      aria-current={isActive ? "page" : undefined}
      title={expanded ? undefined : label}
      className={cn(
        "flex items-center gap-3 px-3 py-2.5 rounded-2xl transition-all duration-200 ease-out group relative",
        isActive
          ? "text-white bg-gradient-to-r from-white/[0.13] to-white/[0.04] shadow-[0_6px_18px_-8px_rgba(0,0,0,0.55),inset_0_1px_0_rgba(255,255,255,0.07)]"
          : "text-white/45 hover:text-white/80 hover:bg-white/[0.055] hover:translate-x-[2px]"
      )}
    >
      {isActive && (
        <motion.div
          layoutId="nav-indicator"
          className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 bg-jenny-coral rounded-r-full"
          transition={{ type: "spring", stiffness: 350, damping: 30 }}
        />
      )}
      <item.icon
        className={cn("w-[18px] h-[18px] flex-shrink-0", item.accent && isActive && "text-jenny-coral")}
      />
      {expanded && <span className="text-[0.8125rem] font-medium">{label}</span>}
      {badge !== undefined && badge > 0 && (
        <span
          className={cn(
            "bg-jenny-coral text-white text-[10px] font-semibold rounded-full min-w-[18px] h-[18px] px-1 flex items-center justify-center",
            expanded ? "ml-auto" : "absolute top-1 right-1"
          )}
          title={`${badge} conversation${badge > 1 ? "s" : ""} sans réponse`}
        >
          {badge > 99 ? "99+" : badge}
        </span>
      )}
      {item.accent && expanded && isActive && (
        <Sparkles className="w-3.5 h-3.5 text-jenny-coral/70 ml-auto" />
      )}
    </Link>
  );
}

function SidebarInner({ collapsed, mobileOpen, onClose }: { collapsed: boolean; mobileOpen: boolean; onClose: () => void }) {
  const pathname = usePathname();
  const { logout, user } = useAuth();
  const { t } = useTranslation();
  const expanded = !collapsed || mobileOpen;
  const live = useRealtimeStatus();
  const [awaiting, setAwaiting] = useState<number | null>(null);
  const [statsFailed, setStatsFailed] = useState(false);
  const [labOpen, setLabOpen] = useState(false);
  const labActive = labItems.some((i) => isActivePath(pathname, i.href));

  // compteur à traiter
  const refresh = useCallback(() => {
    getConversationStats()
      .then((s) => {
        setAwaiting(s.awaiting);
        setStatsFailed(false);
      })
      .catch(() => setStatsFailed(true));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useRealtimeRefresh(refresh);

  // groupe labo mémorisé
  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (localStorage.getItem(LAB_KEY) === "1") setLabOpen(true);
    } catch {
      // stockage bloqué
    }
  }, []);

  const toggleLab = () => {
    setLabOpen((o) => {
      const next = !o;
      try {
        localStorage.setItem(LAB_KEY, next ? "1" : "0");
      } catch {
        // tant pis
      }
      return next;
    });
  };

  const showLab = labOpen || labActive;

  return (
    <>
      {/* Logo — clic = retour à l'accueil du tableau de bord */}
      <div className="h-[60px] flex items-center px-4 border-b border-white/[0.06]">
        <Link
          href="/dashboard"
          onClick={onClose}
          aria-label="Accueil Jenny"
          className="flex items-center gap-3 min-w-0 rounded-xl -ml-1 pl-1 pr-2 py-1 transition-colors hover:bg-white/[0.06] group/logo"
        >
          <JennyAvatar
            size={36}
            tone="dark"
            className="shadow-md shadow-jenny-coral/30 transition-transform duration-200 group-hover/logo:scale-105"
          />
          {expanded && (
            <span className="text-white font-semibold text-[1.0625rem] tracking-tight">
              Jenny
            </span>
          )}
        </Link>
        {expanded && !mobileOpen && (
          <span className="ml-auto font-mono text-[9px] tracking-[0.12em] uppercase text-white/30 px-1.5 py-[3px] border border-white/10 rounded">
            Bêta
          </span>
        )}
        {mobileOpen && (
          <button onClick={onClose} aria-label="Fermer le menu" className="ml-auto text-white/40 hover:text-white/70 p-1">
            <X className="w-5 h-5" />
          </button>
        )}
      </div>

      {/* Nav */}
      <nav aria-label="Navigation principale" className="flex-1 py-3 px-2.5 space-y-0.5 overflow-y-auto">
        {mainItems.map((item) => (
          <NavLink
            key={item.href}
            item={item}
            pathname={pathname}
            expanded={expanded}
            onClose={onClose}
            badge={item.href === "/conversations" ? awaiting ?? 0 : undefined}
          />
        ))}

        {/* groupe labo */}
        <button
          type="button"
          onClick={toggleLab}
          aria-expanded={showLab}
          title={expanded ? undefined : t("nav.labGroup")}
          className={cn(
            "w-full flex items-center gap-3 px-3 pt-4 pb-1.5 rounded-xl text-white/30 hover:text-white/60 transition-colors",
            !expanded && "justify-center px-0"
          )}
        >
          <FlaskConical className={cn("w-[15px] h-[15px] flex-shrink-0", expanded && "hidden")} />
          {expanded && (
            <>
              <span className="font-mono text-[10px] tracking-[0.16em] uppercase font-semibold">
                {t("nav.labGroup")}
              </span>
              <ChevronDown
                className={cn("w-3.5 h-3.5 ml-auto transition-transform", showLab ? "rotate-0" : "-rotate-90")}
              />
            </>
          )}
        </button>
        {showLab &&
          labItems.map((item) => (
            <NavLink key={item.href} item={item} pathname={pathname} expanded={expanded} onClose={onClose} />
          ))}

        {expanded && (
          <div className="px-3.5 pt-4 pb-1.5 font-mono text-[10px] tracking-[0.16em] uppercase text-white/25 font-semibold">
            {t("nav.account")}
          </div>
        )}
        {accountItems.map((item) => (
          <NavLink key={item.href} item={item} pathname={pathname} expanded={expanded} onClose={onClose} />
        ))}
      </nav>

      {/* Footer */}
      <div className="p-2.5 border-t border-white/[0.06]">
        {/* état réel du flux */}
        {expanded && (
          <div
            className="mx-1 mb-2 p-3.5 rounded-xl border border-jenny-coral/20"
            style={{
              background:
                "linear-gradient(135deg, rgba(255,127,106,0.12), rgba(255,127,106,0.04))",
            }}
          >
            <div className="flex items-center justify-between gap-2 mb-2">
              <span className="font-mono text-[10px] tracking-[0.14em] uppercase text-jenny-coral font-semibold">
                {t("nav.liveTitle")}
              </span>
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[10.5px] font-semibold tracking-wide",
                  live
                    ? "bg-jenny-success/15 border-jenny-success/25 text-jenny-success"
                    : "bg-jenny-warning/15 border-jenny-warning/25 text-jenny-warning"
                )}
              >
                <span className="relative flex w-1.5 h-1.5">
                  {live && (
                    <span className="absolute inline-flex h-full w-full rounded-full bg-current opacity-60 animate-ping" />
                  )}
                  <span className="relative inline-flex w-1.5 h-1.5 rounded-full bg-current" />
                </span>
                {live
                  ? t("nav.liveOn")
                  : t("nav.liveOff")}
              </span>
            </div>
            <p className="text-white/70 text-[12px] leading-snug">
              {awaiting === null
                ? statsFailed
                  ? t("nav.liveError")
                  : t("nav.liveUnknown")
                : awaiting > 0
                  ? t("nav.liveAwaiting", { count: awaiting })
                  : t("nav.liveClear")}
            </p>
          </div>
        )}
        {expanded && user && (
          <div className="px-3 py-2.5 mb-1">
            <p className="text-white/75 text-[0.8125rem] font-medium truncate">{user.full_name}</p>
            <p className="text-white/30 text-[0.75rem] truncate">{user.email}</p>
          </div>
        )}
        {/* Mode sombre — vrai toggle premium (synchro avec la topbar) */}
        {expanded && <ThemeSwitch className="hover:bg-white/[0.04]" />}
        {user?.is_superuser && (
          <Link
            href="/admin"
            onClick={onClose}
            className="flex items-center gap-3 px-3 py-2.5 rounded-2xl text-jenny-coral/80 hover:text-jenny-coral hover:bg-jenny-coral/10 transition-all duration-200 w-full"
          >
            <Shield className="w-[18px] h-[18px] flex-shrink-0" />
            {expanded && <span className="text-[0.8125rem] font-medium">{t("nav.admin")}</span>}
          </Link>
        )}
        <button
          onClick={() => { logout(); onClose(); }}
          className="flex items-center gap-3 px-3 py-2.5 rounded-2xl text-white/35 hover:text-white/60 hover:bg-white/[0.04] transition-all duration-200 w-full"
        >
          <LogOut className="w-[18px] h-[18px] flex-shrink-0" />
          {expanded && <span className="text-[0.8125rem]">{t("nav.logout")}</span>}
        </button>
      </div>
    </>
  );
}

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <>
      {/* Mobile trigger */}
      <button
        onClick={() => setMobileOpen(true)}
        aria-label="Ouvrir le menu"
        className="fixed top-3.5 left-3.5 z-50 md:hidden w-10 h-10 rounded-xl bg-jenny-sidebar flex items-center justify-center text-white/80 shadow-lg"
      >
        <Menu className="w-5 h-5" />
      </button>

      {/* Mobile overlay */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setMobileOpen(false)}
            className="fixed inset-0 bg-black/40 backdrop-blur-[2px] z-40 md:hidden"
          />
        )}
      </AnimatePresence>

      {/* Mobile drawer */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.aside
            initial={{ x: -280 }}
            animate={{ x: 0 }}
            exit={{ x: -280 }}
            transition={{ type: "spring", stiffness: 350, damping: 35 }}
            className="fixed inset-y-0 left-0 w-[260px] bg-jenny-sidebar flex flex-col z-50 md:hidden shadow-2xl"
          >
            <SidebarInner collapsed={false} mobileOpen={true} onClose={() => setMobileOpen(false)} />
          </motion.aside>
        )}
      </AnimatePresence>

      {/* Desktop sidebar */}
      <motion.aside
        animate={{ width: collapsed ? 64 : 240 }}
        transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
        className="hidden md:flex h-full bg-jenny-sidebar flex-col relative z-20 border-r border-white/[0.04]"
      >
        <SidebarInner collapsed={collapsed} mobileOpen={false} onClose={() => {}} />

        {/* Collapse toggle */}
        <button
          onClick={() => setCollapsed(!collapsed)}
          aria-label={collapsed ? "Déplier le menu" : "Replier le menu"}
          className="absolute -right-3 top-[72px] w-6 h-6 bg-jenny-surface border border-jenny-divider rounded-full flex items-center justify-center text-jenny-text-secondary/70 hover:text-jenny-text hover:border-jenny-coral/30 transition-all shadow-sm"
        >
          {collapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronLeft className="w-3 h-3" />}
        </button>
      </motion.aside>
    </>
  );
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { getConversationStats, subscribeToConversationEvents } from "@/lib/api";
import {
  LayoutDashboard,
  MessageCircle,
  MessagesSquare,
  Mail,
  Users,
  Radio,
  BookOpen,
  Brain,
  BarChart3,
  TrendingUp,
  Lightbulb,
  Gauge,
  Cpu,
  Scissors,
  CalendarDays,
  Shield,
  Settings,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  Menu,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth-context";
import { JennyAvatar } from "@/components/ui/jenny-avatar";
import { ThemeSwitch } from "@/components/ui/theme-switch";

// Navigation principale + section « Compte », dans l'ordre de la DA Jenny Front.
const navItems = [
  { href: "/dashboard", icon: LayoutDashboard, labelKey: "nav.dashboard", accent: false, section: "main" },
  { href: "/chat", icon: MessageCircle, labelKey: "nav.chat", accent: true, section: "main" },
  { href: "/assistant", icon: Sparkles, labelKey: "nav.assistant", accent: false, section: "main" },
  { href: "/conversations", icon: MessagesSquare, labelKey: "nav.conversations", accent: false, section: "main" },
  { href: "/calendar", icon: CalendarDays, labelKey: "nav.calendar", accent: false, section: "main" },
  { href: "/prestations", icon: Scissors, labelKey: "nav.prestations", accent: false, section: "main" },
  { href: "/brain", icon: Brain, labelKey: "nav.brain", accent: false, section: "main" },
  { href: "/knowledge", icon: BookOpen, labelKey: "nav.knowledge", accent: false, section: "main" },
  { href: "/learning", icon: Lightbulb, labelKey: "nav.learning", accent: false, section: "main" },
  { href: "/analytics", icon: BarChart3, labelKey: "nav.analytics", accent: false, section: "main" },
  { href: "/efficacy", icon: Gauge, labelKey: "nav.efficacy", accent: false, section: "main" },
  { href: "/lab", icon: Cpu, labelKey: "nav.lab", accent: false, section: "main" },
  { href: "/stats", icon: TrendingUp, labelKey: "nav.stats", accent: false, section: "main" },
  { href: "/channels", icon: Radio, labelKey: "nav.channels", accent: false, section: "main" },
  { href: "/customers", icon: Users, labelKey: "nav.customers", accent: false, section: "account" },
  { href: "/messages", icon: Mail, labelKey: "nav.messages", accent: false, section: "account" },
  { href: "/profile", icon: Settings, labelKey: "nav.settings", accent: false, section: "account" },
];

function SidebarInner({ collapsed, mobileOpen, onClose }: { collapsed: boolean; mobileOpen: boolean; onClose: () => void }) {
  const pathname = usePathname();
  const { logout, user } = useAuth();
  const { t } = useTranslation();
  const expanded = !collapsed || mobileOpen;
  const [awaiting, setAwaiting] = useState(0);

  // Compteur « à traiter » live (mis à jour via SSE).
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const refresh = () => getConversationStats().then((s) => setAwaiting(s.awaiting)).catch(() => {});
    refresh();
    const unsub = subscribeToConversationEvents(() => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(refresh, 600);
    });
    return () => {
      unsub();
      if (timer) clearTimeout(timer);
    };
  }, []);

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
          <button onClick={onClose} className="ml-auto text-white/40 hover:text-white/70 p-1">
            <X className="w-5 h-5" />
          </button>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 py-3 px-2.5 space-y-0.5 overflow-y-auto">
        {navItems.map((item, i) => {
          const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
          const showSection =
            expanded && item.section === "account" && navItems[i - 1]?.section !== "account";
          return (
            <div key={item.href} className="contents">
              {showSection && (
                <div className="px-3.5 pt-4 pb-1.5 font-mono text-[10px] tracking-[0.16em] uppercase text-white/25 font-semibold">
                  {t("nav.account")}
                </div>
              )}
            <Link
              href={item.href}
              onClick={onClose}
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
                className={cn(
                  "w-[18px] h-[18px] flex-shrink-0",
                  item.accent && isActive && "text-jenny-coral"
                )}
              />
              {expanded && (
                <span className="text-[0.8125rem] font-medium">{t(item.labelKey)}</span>
              )}
              {item.href === "/conversations" && awaiting > 0 && (
                <span
                  className={cn(
                    "bg-jenny-coral text-white text-[10px] font-semibold rounded-full min-w-[18px] h-[18px] px-1 flex items-center justify-center",
                    expanded ? "ml-auto" : "absolute top-1 right-1"
                  )}
                  title={`${awaiting} conversation${awaiting > 1 ? "s" : ""} à traiter`}
                >
                  {awaiting > 99 ? "99+" : awaiting}
                </span>
              )}
              {item.accent && expanded && isActive && (
                <Sparkles className="w-3.5 h-3.5 text-jenny-coral/70 ml-auto" />
              )}
            </Link>
            </div>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="p-2.5 border-t border-white/[0.06]">
        {/* Carte auto-pilote (DA) */}
        {expanded && (
          <div
            className="mx-1 mb-2 p-3.5 rounded-xl border border-jenny-coral/20"
            style={{
              background:
                "linear-gradient(135deg, rgba(255,127,106,0.12), rgba(255,127,106,0.04))",
            }}
          >
            <div className="font-mono text-[10px] tracking-[0.14em] uppercase text-jenny-coral font-semibold mb-2">
              {t("nav.autopilot")}
            </div>
            <p className="text-white/70 text-[12px] leading-snug mb-2.5">{t("nav.autopilotDesc")}</p>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-jenny-coral/15 border border-jenny-coral/25">
              <span className="relative flex w-1.5 h-1.5">
                <span className="absolute inline-flex h-full w-full rounded-full bg-jenny-coral opacity-60 animate-ping" />
                <span className="relative inline-flex w-1.5 h-1.5 rounded-full bg-jenny-coral" />
              </span>
              <span className="text-jenny-coral text-[10.5px] font-semibold tracking-wide">
                {t("nav.autopilotOn")}
              </span>
            </span>
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
          className="absolute -right-3 top-[72px] w-6 h-6 bg-white border border-jenny-divider rounded-full flex items-center justify-center text-jenny-text-secondary/70 hover:text-jenny-text hover:border-jenny-coral/30 transition-all shadow-sm"
        >
          {collapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronLeft className="w-3 h-3" />}
        </button>
      </motion.aside>
    </>
  );
}

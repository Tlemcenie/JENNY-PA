"use client";

import { usePathname } from "next/navigation";
import { Activity, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { checkHealth } from "@/lib/api";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { SoundToggle } from "@/components/ui/sound-toggle";
import { DensityToggle } from "@/components/ui/density-toggle";
import { LanguageSwitcher } from "@/components/ui/language-switcher";
import { NotificationBell } from "@/components/layout/notification-bell";
import { UserMenu } from "@/components/layout/user-menu";
import { LlmSwitcher } from "@/components/layout/llm-switcher";

const pageTitleKeys: Record<string, string> = {
  "/dashboard": "nav.dashboard",
  "/chat": "nav.chat",
  "/conversations": "nav.conversations",
  "/customers": "nav.customers",
  "/channels": "nav.channels",
  "/knowledge": "nav.knowledge",
  "/profile": "nav.settings",
};

export function Topbar() {
  const pathname = usePathname();
  const { t } = useTranslation();
  const [apiStatus, setApiStatus] = useState<"ok" | "error" | "loading">("loading");

  const titleKey = pageTitleKeys[pathname];
  const title = titleKey ? t(titleKey) : "Jenny";

  useEffect(() => {
    checkHealth()
      .then(() => setApiStatus("ok"))
      .catch(() => setApiStatus("error"));

    // Re-check every 30s
    const interval = setInterval(() => {
      checkHealth()
        .then(() => setApiStatus("ok"))
        .catch(() => setApiStatus("error"));
    }, 30000);

    return () => clearInterval(interval);
  }, []);

  return (
    <header className="h-14 bg-jenny-surface border-b border-jenny-divider flex items-center justify-between px-4 md:px-6">
      {/* Spacer for mobile hamburger */}
      <div className="w-10 md:hidden" />
      <h1 className="text-base md:text-lg font-semibold text-jenny-text">{title}</h1>
      <div className="flex items-center gap-2">
        <button
          onClick={() => window.dispatchEvent(new Event("jenny:command-open"))}
          title="Rechercher (⌘K)"
          aria-label="Recherche globale"
          className="flex items-center gap-2 h-8 pl-2.5 pr-2 rounded-lg text-jenny-text-secondary border border-jenny-divider hover:border-jenny-coral/40 hover:text-jenny-coral transition-colors"
        >
          <Search className="w-3.5 h-3.5" />
          <kbd className="hidden sm:inline text-[10px] bg-jenny-divider/50 rounded px-1 py-0.5">⌘K</kbd>
        </button>
        <LlmSwitcher />
        <NotificationBell />
        <SoundToggle />
        <DensityToggle />
        <LanguageSwitcher />
        <ThemeToggle />
        <div className="flex items-center gap-2 text-xs">
          <Activity className="w-3.5 h-3.5 text-jenny-text-secondary" />
          <span className="text-jenny-text-secondary hidden sm:inline">API</span>
          <span
            className={`w-2 h-2 rounded-full transition-colors ${
              apiStatus === "ok"
                ? "bg-jenny-success"
                : apiStatus === "error"
                ? "bg-jenny-error"
                : "bg-jenny-warning animate-pulse"
            }`}
          />
          {apiStatus === "error" && (
            <span className="text-jenny-error text-[10px] hidden sm:inline">Hors ligne</span>
          )}
        </div>
        <UserMenu />
      </div>
    </header>
  );
}

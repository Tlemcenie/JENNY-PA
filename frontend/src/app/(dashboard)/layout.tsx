"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { TimeProvider } from "@/lib/time-context";
import { UiPrefsProvider } from "@/lib/ui-prefs";
import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { RealtimeNotifier } from "@/components/layout/realtime-notifier";
import { CommandPalette } from "@/components/layout/command-palette";
import { ShortcutsHelp } from "@/components/layout/shortcuts-help";
import { LiveRegion } from "@/components/layout/live-region";
import { ConfirmProvider } from "@/components/ui/confirm-dialog";
import { BrandedLoader } from "@/components/ui/branded-loader";
import { I18nProvider } from "@/components/i18n-provider";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isAuthenticated, isLoading, router]);

  if (isLoading) {
    return <BrandedLoader />;
  }

  if (!isAuthenticated) return null;

  return (
    <I18nProvider>
      <UiPrefsProvider>
        <TimeProvider>
          <ConfirmProvider>
            <div className="h-full flex">
              <RealtimeNotifier />
              <CommandPalette />
              <ShortcutsHelp />
              <LiveRegion />
              <Sidebar />
              <div className="flex-1 flex flex-col min-w-0">
                <Topbar />
                <main className="flex-1 overflow-auto">{children}</main>
              </div>
            </div>
          </ConfirmProvider>
        </TimeProvider>
      </UiPrefsProvider>
    </I18nProvider>
  );
}

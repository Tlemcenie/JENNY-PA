import type { Metadata } from "next";
import { DashboardShell } from "@/components/layout/dashboard-shell";

// espace connecté : jamais indexé
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return <DashboardShell>{children}</DashboardShell>;
}

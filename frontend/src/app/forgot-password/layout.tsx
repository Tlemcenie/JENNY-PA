import type { Metadata } from "next";

// page outil, pas d'index
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function ForgotPasswordLayout({ children }: { children: React.ReactNode }) {
  return children;
}

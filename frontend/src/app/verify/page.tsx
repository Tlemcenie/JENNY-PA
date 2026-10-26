import type { Metadata } from "next";
import { VerifyForm } from "./verify-form";

// lien perso, pas d'index
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default async function VerifyPage({
  searchParams,
}: {
  searchParams: Promise<{ email?: string | string[] }>;
}) {
  const params = await searchParams;
  const email = typeof params.email === "string" ? params.email : "";
  return <VerifyForm initialEmail={email} />;
}

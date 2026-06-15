"use client";

import { useEffect } from "react";
import { I18nextProvider } from "react-i18next";
import i18n, { getStoredLang } from "@/lib/i18n";

/**
 * Fournit le contexte i18n et applique la langue persistée après montage
 * (le SSR rend en FR par défaut ; on bascule côté client sans flash visible).
 */
export function I18nProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    const lang = getStoredLang();
    if (i18n.language !== lang) {
      void i18n.changeLanguage(lang);
    }
  }, []);

  return <I18nextProvider i18n={i18n}>{children}</I18nextProvider>;
}

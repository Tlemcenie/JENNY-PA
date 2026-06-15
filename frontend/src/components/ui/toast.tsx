"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Toaster, toast as sonnerToast } from "sonner";

type ToastType = "success" | "error" | "info";

interface ToastContextValue {
  show: (message: string, type?: ToastType) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

// API conservée (toast.success/error/info) mais adossée à sonner pour un rendu
// pro (empilement, swipe, couleurs riches, accessibilité).
const api: ToastContextValue = {
  show: (m, type = "info") => {
    if (type === "success") sonnerToast.success(m);
    else if (type === "error") sonnerToast.error(m);
    else sonnerToast(m);
  },
  success: (m) => sonnerToast.success(m),
  error: (m) => sonnerToast.error(m),
  info: (m) => sonnerToast(m),
};

export function useToast(): ToastContextValue {
  return api;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    const read = () =>
      setTheme(document.documentElement.classList.contains("dark") ? "dark" : "light");
    read();
    const obs = new MutationObserver(read);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);

  return (
    <>
      {children}
      <Toaster
        theme={theme}
        position="bottom-right"
        richColors
        closeButton
        toastOptions={{
          style: { borderRadius: "0.75rem", fontSize: "0.875rem" },
        }}
      />
    </>
  );
}

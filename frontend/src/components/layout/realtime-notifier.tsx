"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import type { RealtimeEvent } from "@/lib/api";
import { channelLabel } from "@/lib/utils";
import { playNotificationSound } from "@/lib/sound";
import { useRealtimeEvent } from "@/components/providers/realtime-provider";

/** vrai message client ? */
function isCustomerMessage(event: RealtimeEvent): boolean {
  // simple refresh = pas d'alerte
  return event.kind === "inbound" && event.event !== "notification.new";
}

/** notificateur temps réel global. */
export function RealtimeNotifier() {
  const pathname = usePathname();
  const pathnameRef = useRef(pathname);
  const countRef = useRef(0);

  const applyTitle = () => {
    const base = document.title.replace(/^\(\d+\)\s*/, "");
    document.title = countRef.current > 0 ? `(${countRef.current}) ${base}` : base;
  };

  // demande la permission
  useEffect(() => {
    if (typeof Notification !== "undefined" && Notification.permission === "default") {
      Notification.requestPermission().catch(() => {});
    }
  }, []);

  // maj badge à chaque navigation
  useEffect(() => {
    pathnameRef.current = pathname;
    if (pathname === "/conversations") countRef.current = 0;
    applyTitle();
  }, [pathname]);

  // vide le badge au retour
  useEffect(() => {
    const onVisible = () => {
      if (!document.hidden && pathnameRef.current === "/conversations") {
        countRef.current = 0;
        applyTitle();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);

  // flux partagé du layout
  useRealtimeEvent((event: RealtimeEvent) => {
    // vrais clients seulement
    if (!isCustomerMessage(event)) return;
    // déjà sous les yeux
    if (!document.hidden && pathnameRef.current === "/conversations") return;
    countRef.current += 1;
    applyTitle();
    playNotificationSound(); // bip discret
    // annonce lecteurs d'écran
    const canal = event.channel ? ` (${channelLabel(event.channel)})` : "";
    window.dispatchEvent(
      new CustomEvent("jenny:announce", { detail: `Nouveau message reçu${canal}` })
    );

    if (typeof Notification !== "undefined" && Notification.permission === "granted") {
      try {
        new Notification("Nouveau message", {
          body: `Un client vous a écrit${canal}.`,
          tag: "jenny-inbound", // regroupe les notifs
        });
      } catch {
        // on ignore
      }
    }
  });

  return null;
}

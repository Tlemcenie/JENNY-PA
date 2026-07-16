"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { subscribeToConversationEvents, type RealtimeEvent } from "@/lib/api";
import { channelLabel } from "@/lib/utils";
import { playNotificationSound } from "@/lib/sound";

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

  // abonnement sse unique
  useEffect(() => {
    const watching = () =>
      pathnameRef.current === "/conversations" && !document.hidden;

    const handle = (event: RealtimeEvent) => {
      if (event.kind !== "inbound") return; // seuls les entrants alertent
      if (watching()) return; // l'utilisateur les voit déjà
      countRef.current += 1;
      applyTitle();
      playNotificationSound(); // bip discret
      // annonce lecteurs d'écran
      const canalA = event.channel ? ` (${channelLabel(event.channel)})` : "";
      window.dispatchEvent(
        new CustomEvent("jenny:announce", { detail: `Nouveau message reçu${canalA}` })
      );

      if (typeof Notification !== "undefined" && Notification.permission === "granted") {
        const canal = event.channel ? ` (${channelLabel(event.channel)})` : "";
        try {
          new Notification("Nouveau message", {
            body: `Un client vous a écrit${canal}.`,
            tag: "jenny-inbound", // regroupe les notifs
          });
        } catch {
          // on ignore
        }
      }
    };

    return subscribeToConversationEvents(handle);
  }, []);

  return null;
}

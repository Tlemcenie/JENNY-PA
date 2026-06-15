"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { subscribeToConversationEvents, type RealtimeEvent } from "@/lib/api";
import { channelLabel } from "@/lib/utils";
import { playNotificationSound } from "@/lib/sound";

/**
 * Notificateur temps réel global (monté dans le layout dashboard).
 *
 * À chaque nouveau message entrant (événement SSE `inbound`), si l'utilisateur
 * n'est PAS déjà en train de regarder les conversations :
 *  - incrémente un compteur affiché dans le titre de l'onglet → `(3) Jenny …` ;
 *  - déclenche une notification navigateur (best-effort, si permission accordée).
 *
 * Le compteur se remet à zéro dès qu'on (re)voit la page Conversations.
 *
 * Purement comportemental : la seule sortie est `document.title` (effet DOM) et
 * les notifications. On s'appuie donc sur des refs (pas d'état React à rendre).
 */
export function RealtimeNotifier() {
  const pathname = usePathname();
  const pathnameRef = useRef(pathname);
  const countRef = useRef(0);

  const applyTitle = () => {
    const base = document.title.replace(/^\(\d+\)\s*/, "");
    document.title = countRef.current > 0 ? `(${countRef.current}) ${base}` : base;
  };

  // Demande de permission (best-effort, sans bloquer si refusée/indisponible).
  useEffect(() => {
    if (typeof Notification !== "undefined" && Notification.permission === "default") {
      Notification.requestPermission().catch(() => {});
    }
  }, []);

  // À chaque navigation : on mémorise le pathname, on vide le compteur si on
  // arrive sur les conversations, et on (re)pose le badge dans le titre — Next
  // réécrit le titre au changement de route, il faut donc le réappliquer.
  useEffect(() => {
    pathnameRef.current = pathname;
    if (pathname === "/conversations") countRef.current = 0;
    applyTitle();
  }, [pathname]);

  // Retour sur l'onglet en regardant déjà les conversations → on vide le badge.
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

  // Abonnement SSE unique : alerte sur les messages entrants non vus.
  useEffect(() => {
    const watching = () =>
      pathnameRef.current === "/conversations" && !document.hidden;

    const handle = (event: RealtimeEvent) => {
      if (event.kind !== "inbound") return; // seuls les entrants alertent
      if (watching()) return; // l'utilisateur les voit déjà
      countRef.current += 1;
      applyTitle();
      playNotificationSound(); // bip discret (si activé dans les préférences)
      // Annonce pour les lecteurs d'écran (accessibilité).
      const canalA = event.channel ? ` (${channelLabel(event.channel)})` : "";
      window.dispatchEvent(
        new CustomEvent("jenny:announce", { detail: `Nouveau message reçu${canalA}` })
      );

      if (typeof Notification !== "undefined" && Notification.permission === "granted") {
        const canal = event.channel ? ` (${channelLabel(event.channel)})` : "";
        try {
          new Notification("Nouveau message", {
            body: `Un client vous a écrit${canal}.`,
            tag: "jenny-inbound", // regroupe les notifications successives
          });
        } catch {
          // certains navigateurs exigent un Service Worker → on ignore
        }
      }
    };

    return subscribeToConversationEvents(handle);
  }, []);

  return null;
}

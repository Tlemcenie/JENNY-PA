"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { subscribeToConversationEvents, type RealtimeEvent } from "@/lib/api";

type Handler = (event: RealtimeEvent) => void;

interface RealtimeContextValue {
  connected: boolean;
  subscribe: (handler: Handler) => () => void;
}

const RealtimeContext = createContext<RealtimeContextValue | null>(null);

/** un seul flux sse pour le dashboard */
export function RealtimeProvider({ children }: { children: ReactNode }) {
  const handlers = useRef(new Set<Handler>());
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    return subscribeToConversationEvents((event) => {
      for (const h of [...handlers.current]) {
        try {
          h(event);
        } catch {
          // on passe au suivant
        }
      }
    }, setConnected);
  }, []);

  const subscribe = useCallback((handler: Handler) => {
    handlers.current.add(handler);
    return () => {
      handlers.current.delete(handler);
    };
  }, []);

  const value = useMemo(() => ({ connected, subscribe }), [connected, subscribe]);

  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>;
}

/** écoute les événements temps réel */
export function useRealtimeEvent(handler: Handler): void {
  const subscribe = useContext(RealtimeContext)?.subscribe;
  const handlerRef = useRef(handler);

  useEffect(() => {
    handlerRef.current = handler;
  });

  useEffect(() => {
    const relay: Handler = (event) => handlerRef.current(event);
    if (subscribe) return subscribe(relay);
    // repli hors provider
    return subscribeToConversationEvents(relay);
  }, [subscribe]);
}

/** relance une action, regroupée */
export function useRealtimeRefresh(
  refresh: () => void,
  delay = 600,
  filter?: (event: RealtimeEvent) => boolean
): void {
  const refreshRef = useRef(refresh);
  const filterRef = useRef(filter);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    refreshRef.current = refresh;
    filterRef.current = filter;
  });

  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  useRealtimeEvent((event) => {
    if (filterRef.current && !filterRef.current(event)) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => refreshRef.current(), delay);
  });
}

/** état de connexion du flux */
export function useRealtimeStatus(): boolean {
  return useContext(RealtimeContext)?.connected ?? false;
}

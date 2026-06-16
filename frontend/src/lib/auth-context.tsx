"use client";

import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from "react";
import * as api from "./api";
import { ApiError } from "./api";
import type { RegisterResult, User } from "./api";

interface AuthState {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
}

interface AuthContextType extends AuthState {
  login: (email: string, password: string) => Promise<User>;
  register: (fullName: string, email: string, password: string) => Promise<RegisterResult>;
  verifyEmail: (email: string, code: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    isLoading: true,
    isAuthenticated: false,
  });

  // Vérifie la session au montage. Robuste aux pépins transitoires : on ne
  // déconnecte JAMAIS sur une erreur réseau / 5xx / API qui redémarre — sinon
  // l'utilisateur est renvoyé au login au moindre hoquet (« ça refresh tout le
  // temps / ça me change d'onglet »). On ne vide la session que sur un vrai 401/403.
  useEffect(() => {
    let cancelled = false;
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

    const checkAuth = async () => {
      if (!api.isAuthenticated()) {
        setState({ user: null, isLoading: false, isAuthenticated: false });
        return;
      }
      // Jusqu'à 3 tentatives avec petit back-off : couvre un redémarrage d'API ou
      // une coupure réseau brève sans jamais déconnecter l'utilisateur.
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          const user = await api.getMe();
          if (!cancelled) setState({ user, isLoading: false, isAuthenticated: true });
          return;
        } catch (err) {
          const status = err instanceof ApiError ? err.status : 0;
          if (status === 401 || status === 403) {
            // Vraie expiration de session → on déconnecte proprement.
            api.clearToken();
            if (!cancelled) setState({ user: null, isLoading: false, isAuthenticated: false });
            return;
          }
          if (attempt < 2) await sleep(800 * (attempt + 1));
        }
      }
      // Toujours pas de réponse après les tentatives : on RESTE connecté (token
      // valide), `getMe` sera retenté plus tard. Pas de rebond vers /login.
      if (!cancelled) setState((s) => ({ ...s, isLoading: false, isAuthenticated: true }));
    };

    checkAuth();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const { user } = await api.login(email, password);
    setState({ user, isLoading: false, isAuthenticated: true });
    return user;
  }, []);

  const register = useCallback(async (fullName: string, email: string, password: string) => {
    // L'inscription n'authentifie pas : elle déclenche l'envoi du code.
    // La connexion se fait après vérification de l'email (verifyEmail).
    return api.register(fullName, email, password);
  }, []);

  const verifyEmail = useCallback(async (email: string, code: string) => {
    const { user } = await api.verifyEmail(email, code);
    setState({ user, isLoading: false, isAuthenticated: true });
  }, []);

  const logout = useCallback(() => {
    api.logout();
    setState({ user: null, isLoading: false, isAuthenticated: false });
  }, []);

  const refreshUser = useCallback(async () => {
    const user = await api.getMe();
    setState((s) => ({ ...s, user, isAuthenticated: true, isLoading: false }));
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, register, verifyEmail, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

"use client";

import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from "react";
import * as api from "./api";
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

  // Check for existing session on mount
  useEffect(() => {
    const checkAuth = async () => {
      if (!api.isAuthenticated()) {
        setState({ user: null, isLoading: false, isAuthenticated: false });
        return;
      }
      try {
        const user = await api.getMe();
        setState({ user, isLoading: false, isAuthenticated: true });
      } catch {
        api.clearToken();
        setState({ user: null, isLoading: false, isAuthenticated: false });
      }
    };
    checkAuth();
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

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import api, { API_ROUTES, JwtPair, setTokens, clearTokens, getAccessToken, getRefreshToken } from "../api/client";

type AuthContextType = {
  isAuthed: boolean;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [isAuthed, setIsAuthed] = useState(false);

  useEffect(() => {
    const has = !!getAccessToken() && !!getRefreshToken();
    setIsAuthed(has);
    setLoading(false);
  }, []);

  const login = async (email: string, password: string) => {
    const { data } = await api.post<JwtPair>(API_ROUTES.login, { email, password });
    setTokens(data);
    setIsAuthed(true);
  };

  const logout = () => {
    clearTokens();
    setIsAuthed(false);
    window.location.href = "/login";
  };

  const value = useMemo(() => ({ isAuthed, loading, login, logout }), [isAuthed, loading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

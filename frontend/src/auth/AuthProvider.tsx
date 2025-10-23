import React, { createContext, useContext, useEffect, useState } from "react";

type AuthContextType = {
  isAuthenticated: boolean;
  login: (u: string, p: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextType | null>(null);

const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";

export const AuthProvider: React.FC<React.PropsWithChildren> = ({ children }) => {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);

  useEffect(() => {
    if (AUTH_DISABLED) {
      // Dev mode: pretend we’re logged in
      setIsAuthenticated(true);
      return;
    }
    // JWT mode: check localStorage
    setIsAuthenticated(!!localStorage.getItem("access"));
  }, []);

  const login = async (username: string, password: string) => {
    if (AUTH_DISABLED) {
      setIsAuthenticated(true);
      return;
    }
    // normal JWT flow (uncomment when backend ready)
    // const { data } = await api.post("/api/token/", { username, password });
    // localStorage.setItem("access", data.access);
    // localStorage.setItem("refresh", data.refresh);
    setIsAuthenticated(true);
  };

  const logout = () => {
    if (!AUTH_DISABLED) {
      localStorage.removeItem("access");
      localStorage.removeItem("refresh");
    }
    setIsAuthenticated(false);
  };

  return (
    <AuthContext.Provider value={{ isAuthenticated, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
};

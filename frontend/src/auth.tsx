import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, setCsrfToken, type Schema } from "./api/client";
import { Loading } from "./components/common";

type User = Schema["UserView"];
type Auth = {
  user: User | null;
  accept: (value: Schema["AuthView"]) => void;
  logout: () => Promise<void>;
};
const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const client = useQueryClient();
  function accept(value: Schema["AuthView"]) {
    setCsrfToken(value.csrf_token);
    setUser(value.user);
    client.clear();
  }
  function expire() {
    setCsrfToken("");
    setUser(null);
    client.clear();
  }
  useEffect(() => {
    api<Schema["AuthView"]>("/auth/me")
      .then(accept)
      .catch(() => {})
      .finally(() => setLoading(false));
    window.addEventListener("session-expired", expire);
    return () => window.removeEventListener("session-expired", expire);
    // 初始化只恢复一次会话。
  }, []);
  async function logout() {
    await api<void>("/auth/logout", { method: "POST" });
    expire();
  }
  if (loading) return <Loading />;
  return (
    <AuthContext.Provider value={{ user, accept, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("AuthProvider missing");
  return context;
}

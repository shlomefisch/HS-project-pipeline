import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import type { Meta, User } from "./types";

// ------------------------------------------------------------- router
export function useRoute(): string[] {
  const read = () => (location.hash.replace(/^#\/?/, "") || "today").split("/");
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const on = () => setRoute(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function go(path: string) {
  location.hash = `#/${path}`;
}

// ---------------------------------------------------------- app state
interface AppState {
  me: User;
  meta: Meta;
  users: User[];
  userName: (id: number | null | undefined) => string;
  refreshUsers: () => void;
  toast: (msg: string, kind?: "ok" | "error") => void;
}

const Ctx = createContext<AppState | null>(null);

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("App state missing");
  return v;
}

export function AppProvider({ me, meta, children, toast }: { me: User; meta: Meta; children: ReactNode; toast: AppState["toast"] }) {
  const [users, setUsers] = useState<User[]>([]);
  const refreshUsers = useCallback(() => {
    api.get<User[]>("/users").then(setUsers).catch(() => {});
  }, []);
  useEffect(refreshUsers, [refreshUsers]);
  const userName = (id: number | null | undefined) => {
    if (id == null) return "—";
    if (id === me.id) return "You";
    return users.find((u) => u.id === id)?.name ?? `User ${id}`;
  };
  return <Ctx.Provider value={{ me, meta, users, userName, refreshUsers, toast }}>{children}</Ctx.Provider>;
}

// --------------------------------------------------------- data hook
export function useLoad<T>(load: () => Promise<T>, deps: unknown[]): { data: T | null; error: string | null; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    setError(null);
    load()
      .then((d) => live && setData(d))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return { data, error, reload: () => setN((x) => x + 1) };
}

// -------------------------------------------------------------- dates
export function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function plusDays(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return isoDate(d);
}

export function niceDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  const today = isoDate(new Date());
  const key = isoDate(d);
  if (key === today) return "Today";
  if (key === plusDays(1)) return "Tomorrow";
  if (key === plusDays(-1)) return "Yesterday";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric" });
}

export function niceTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

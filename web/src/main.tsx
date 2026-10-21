import { useRef, StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api";
import { AppProvider, go, useApp, useRoute } from "./state";
import { Icon, Logo } from "./icons";
import { Loading } from "./ui";
import type { Meta, User } from "./types";
import { Login, MustChangePassword, Pending } from "./pages/Login";
import { Today } from "./pages/Today";
import { Jobs, NewJob } from "./pages/Jobs";
import { JobPage } from "./pages/Job";
import { Scan } from "./pages/Scan";
import { People, PersonPage } from "./pages/People";
import { Admin } from "./pages/Admin";
import { forgetThisPhone } from "./notify";
import { OfflineBar } from "./OfflineBar";
import { claimFor, forgetAll } from "./offline";
import { AwayOrGone } from "./pages/AwayOrGone";
import { Templates } from "./pages/Templates";

function Root() {
  const [me, setMe] = useState<User | null | undefined>(undefined);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [toastMsg, setToastMsg] = useState<{ text: string; kind: string } | null>(null);

  // The session is already dead (a 401): just clear it. Calling the server again would only 401 again.
  const dropSession = useCallback(() => {
    setToken(null);
    setMe(null);
  }, []);

  // A deliberate sign-out also clears what this phone remembers, so the next person sees none of it.

  // The Sign out button: forget this phone for notifications while the session still works, then clear it.
  const signOut = useCallback(() => {
    forgetThisPhone().finally(() => {
      forgetAll();
      dropSession();
    });
  }, [dropSession]);

  useEffect(() => {
    setUnauthorizedHandler(dropSession);
    if (!getToken()) {
      setMe(null);
      return;
    }
    api.get<User>("/auth/me").then(setMe).catch(() => setMe(null));
  }, [dropSession]);

  useEffect(() => {
    if (!me) return;
    claimFor(me.id);
    if (me.role === "pending" && !me.is_admin) return;
    let stop = false;
    let timer = 0;
    const load = () =>
      api.get<Meta>("/meta").then((m) => { if (!stop) setMeta(m); }).catch(() => { if (!stop) timer = window.setTimeout(load, 4000); });
    load();
    return () => { stop = true; window.clearTimeout(timer); };
  }, [me]);

  const toastTimer = useRef(0);
  const toast = useCallback((text: string, kind: "ok" | "error" = "ok") => {
    setToastMsg({ text, kind });
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToastMsg(null), 2600);
  }, []);

  if (me === undefined) return <Loading />;
  if (me === null) return <Login onSignedIn={setMe} />;
  if (me.must_change_password) return <MustChangePassword me={me} onDone={setMe} onSignOut={signOut} />;
  if (me.role === "pending" && !me.is_admin) return <Pending user={me} onSignOut={signOut} />;
  if (!meta) return <Loading />;

  return (
    <AppProvider me={me} meta={meta} toast={toast}>
      <Shell onSignOut={signOut} onMe={setMe} />
      {toastMsg && (
        <div className={`toast toast-${toastMsg.kind}`} role="status">
          {toastMsg.text}
        </div>
      )}
    </AppProvider>
  );
}

function Shell({ onSignOut, onMe }: { onSignOut: () => void; onMe: (u: User) => void }) {
  const { me } = useApp();
  const route = useRoute();
  const [section, a, b] = route;

  let page;
  const desktop = useDesktop();
  if (section === "jobs" && a === "new") page = <NewJob />;
  else if (section === "jobs" && desktop) {
    // On a PC, the list stays on the left and the job opens beside it.
    page = (
      <div className="split">
        <Jobs compact selectedId={a ? Number(a) : null} />
        <div className="split-main">
          {a ? <JobPage id={Number(a)} key={a} /> : <div className="split-empty"><Logo width={150} /><p>Pick a job on the left, or press <kbd>N</kbd> to start a new one.</p></div>}
        </div>
      </div>
    );
  } else if (section === "jobs" && a) page = <JobPage id={Number(a)} key={a} />;
  else if (section === "jobs") page = <Jobs />;
  else if (section === "scan") page = <Scan jobId={a ? Number(a) : null} key={a ?? "scan"} />;
  else if (section === "people" && a) page = <PersonPage id={Number(a)} key={a} />;
  else if (section === "people") page = <People />;
  else if (section === "team" && me.is_admin && a === "templates") page = <Templates />;
  else if (section === "team" && me.is_admin && a) page = <AwayOrGone id={Number(a)} key={a} />;
  else if (section === "team" && me.is_admin) page = <Admin />;
  else page = <Today onSignOut={onSignOut} onMe={onMe} />;
  void b;

  // Keyboard, for the PC: "/" finds a job, "N" starts one, "G then T/J/P" jumps.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (e.ctrlKey || e.metaKey || e.altKey || el.closest("input, textarea, select, [contenteditable]") || document.querySelector(".sheet")) return;
      if (e.key === "/") {
        e.preventDefault();
        if (section !== "jobs") go("jobs");
        window.setTimeout(() => (document.getElementById("job-search") as HTMLInputElement | null)?.focus(), 50);
      } else if (e.key === "n" || e.key === "N") {
        e.preventDefault();
        go("jobs/new");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [section]);

  const isOn = (key: string) => section === key || (key === "today" && !["jobs", "scan", "people", "team"].includes(section));
  const nav: [string, string, Parameters<typeof Icon>[0]["name"]][] = [
    ["today", "Today", "today"],
    ["jobs", "Jobs", "jobs"],
    ["scan", "Scan", "scan"],
    ["people", "People", "people"],
    ...(me.is_admin ? ([["team", "Team", "team"]] as [string, string, "team"][]) : []),
  ];

  return (
    <div className="shell">
      <aside className="sidebar" aria-label="Main">
        <a href="#/today" className="sidebar-brand" aria-label="Highstyle — Today">
          <Logo width={132} />
          <span className="sidebar-app">Pipeline</span>
        </a>
        <button className="btn btn-sand sidebar-new" onClick={() => go("jobs/new")}>
          <Icon name="plus" /> New job <kbd>N</kbd>
        </button>
        <nav className="sidebar-nav">
          {nav.map(([key, label, icon]) => (
            <a key={key} href={`#/${key}`} className={isOn(key) ? "on" : ""} aria-current={isOn(key) ? "page" : undefined}>
              <Icon name={icon} /> {label}
            </a>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="avatar" aria-hidden="true">{initials(me.name || me.email)}</span>
          <span className="sidebar-me">
            <strong>{me.name || me.email}</strong>
            <span>{ROLE_NAME[me.role] ?? me.role}</span>
          </span>
          <button className="icon-btn" onClick={onSignOut} aria-label="Sign out" title="Sign out">
            <Icon name="logout" />
          </button>
        </div>
      </aside>
      <div className="main-col">
        <OfflineBar />
        {page}
      </div>
      <nav className="tabbar" aria-label="Main">
        {nav.map(([key, label, icon]) => (
          <a key={key} href={`#/${key}`} className={isOn(key) ? "on" : ""} aria-current={isOn(key) ? "page" : undefined}>
            <Icon name={icon} size={22} />
            <span>{label}</span>
          </a>
        ))}
      </nav>
    </div>
  );
}

const ROLE_NAME: Record<string, string> = { rep: "Rep", back_office: "Back office", management: "Management", viewer: "View only", pending: "Waiting for setup" };

function initials(name: string): string {
  const parts = name.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

function useDesktop(): boolean {
  const query = "(min-width: 1024px)";
  const [on, setOn] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const m = window.matchMedia(query);
    const f = () => setOn(m.matches);
    m.addEventListener("change", f);
    return () => m.removeEventListener("change", f);
  }, []);
  return on;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);

if ("serviceWorker" in navigator && location.hostname !== "localhost") {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}

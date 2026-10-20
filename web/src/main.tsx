import { StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api";
import { AppProvider, useApp, useRoute } from "./state";
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
import { AwayOrGone } from "./pages/AwayOrGone";

function Root() {
  const [me, setMe] = useState<User | null | undefined>(undefined);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [toastMsg, setToastMsg] = useState<{ text: string; kind: string } | null>(null);

  // The session is already dead (a 401): just clear it. Calling the server again would only 401 again.
  const dropSession = useCallback(() => {
    setToken(null);
    setMe(null);
  }, []);

  // The Sign out button: forget this phone for notifications while the session still works, then clear it.
  const signOut = useCallback(() => {
    forgetThisPhone().finally(dropSession);
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
    if (me && me.role !== "pending") api.get<Meta>("/meta").then(setMeta).catch(() => {});
  }, [me]);

  const toast = useCallback((text: string, kind: "ok" | "error" = "ok") => {
    setToastMsg({ text, kind });
    window.setTimeout(() => setToastMsg(null), 2600);
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
  if (section === "jobs" && a === "new") page = <NewJob />;
  else if (section === "jobs" && a) page = <JobPage id={Number(a)} key={a} />;
  else if (section === "jobs") page = <Jobs />;
  else if (section === "scan") page = <Scan jobId={a ? Number(a) : null} key={a ?? "scan"} />;
  else if (section === "people" && a) page = <PersonPage id={Number(a)} key={a} />;
  else if (section === "people") page = <People />;
  else if (section === "team" && me.is_admin && a) page = <AwayOrGone id={Number(a)} key={a} />;
  else if (section === "team" && me.is_admin) page = <Admin />;
  else page = <Today onSignOut={onSignOut} onMe={onMe} />;
  void b;

  const tab = (key: string, label: string) => (
    <a href={`#/${key}`} className={section === key || (key === "today" && !["jobs", "scan", "people", "team"].includes(section)) ? "on" : ""} aria-current={section === key ? "page" : undefined}>
      {label}
    </a>
  );

  return (
    <div className="shell">
      {page}
      <nav className="tabbar" aria-label="Main">
        {tab("today", "Today")}
        {tab("jobs", "Jobs")}
        {tab("scan", "Scan")}
        {tab("people", "People")}
        {me.is_admin && tab("team", "Team")}
      </nav>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);

if ("serviceWorker" in navigator && location.hostname !== "localhost") {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}

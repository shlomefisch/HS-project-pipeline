import { useEffect, useState } from "react";
import { flushOutbox } from "./api";
import { dismissFailed, failed, isOffline, onOutboxChange, waiting } from "./offline";

/** Shows what's waiting on this phone, and sends it when signal comes back. */
export function OfflineBar() {
  const [, bump] = useState(0);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const off = onOutboxChange(() => bump((n) => n + 1));
    const tryNow = () => void flushOutbox();
    window.addEventListener("online", tryNow);
    const onShow = () => document.visibilityState === "visible" && tryNow();
    document.addEventListener("visibilitychange", onShow);
    const t = window.setInterval(() => waiting().length && tryNow(), 20000);
    tryNow();
    return () => {
      off();
      window.removeEventListener("online", tryNow);
      document.removeEventListener("visibilitychange", onShow);
      window.clearInterval(t);
    };
  }, []);

  const w = waiting();
  const f = failed();
  if (!isOffline() && !w.length && !f.length) return null;
  return (
    <div className={`offline-bar ${f.length ? "has-failed" : ""}`} role="status">
      <button className="offline-head" onClick={() => setOpen(!open)}>
        {isOffline() ? "No signal" : "Back online"}
        {w.length > 0 && ` — ${w.length} save${w.length === 1 ? "" : "s"} waiting to send`}
        {f.length > 0 && ` — ${f.length} couldn't be sent`}
        {!w.length && !f.length && " — showing what this phone last saw"}
      </button>
      {open && (
        <div className="offline-list">
          {w.map((x) => (
            <p key={x.id} className="small">⏳ {x.label} <span className="muted">· saved {new Date(x.at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span></p>
          ))}
          {f.map((x) => (
            <p key={x.id} className="small offline-failed">
              ✕ {x.label}: {x.error}{" "}
              <button className="btn btn-quiet btn-small" onClick={() => dismissFailed(x.id)}>OK</button>
            </p>
          ))}
          {w.length > 0 && !isOffline() && <button className="btn btn-small" onClick={() => void flushOutbox()}>Send now</button>}
        </div>
      )}
    </div>
  );
}

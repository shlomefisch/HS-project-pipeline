import { useEffect, useState } from "react";
import { api } from "./api";

type State = "checking" | "unsupported" | "blocked" | "off" | "on";

function keyBytes(b64url: string): ArrayBuffer {
  const pad = "=".repeat((4 - (b64url.length % 4)) % 4);
  const raw = atob((b64url + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const buf = new ArrayBuffer(raw.length);
  const view = new Uint8Array(buf);
  for (let i = 0; i < raw.length; i++) view[i] = raw.charCodeAt(i);
  return buf;
}

async function registration(): Promise<ServiceWorkerRegistration | null> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return null;
  return (await navigator.serviceWorker.getRegistration()) ?? null;
}

/** On this phone: are notifications on? And the button to change it. */
export function useNotifications() {
  const [state, setState] = useState<State>("checking");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const reg = await registration();
      if (!reg || typeof Notification === "undefined") return setState("unsupported");
      if (Notification.permission === "denied") return setState("blocked");
      setState((await reg.pushManager.getSubscription()) ? "on" : "off");
    })().catch(() => setState("unsupported"));
  }, []);

  const turnOn = async () => {
    setError(null);
    try {
      const reg = await registration();
      if (!reg) return setState("unsupported");
      const perm = await Notification.requestPermission();
      if (perm !== "granted") return setState(perm === "denied" ? "blocked" : "off");
      const { key } = await api.get<{ key: string }>("/push/key");
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) });
      await api.post("/push/subscribe", sub.toJSON());
      setState("on");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't turn notifications on.");
    }
  };

  const turnOff = async () => {
    setError(null);
    const reg = await registration();
    const sub = await reg?.pushManager.getSubscription();
    if (sub) {
      await api.post("/push/unsubscribe", { endpoint: sub.endpoint }).catch(() => {});
      await sub.unsubscribe().catch(() => {});
    }
    setState("off");
  };

  const test = () => api.post("/push/test").catch((e: Error) => setError(e.message));
  return { state, error, turnOn, turnOff, test };
}

/** Called on sign-out, so the next person on a shared phone doesn't get the last person's buzzes. */
export async function forgetThisPhone(): Promise<void> {
  try {
    const reg = await registration();
    const sub = await reg?.pushManager.getSubscription();
    if (sub) {
      await api.post("/push/unsubscribe", { endpoint: sub.endpoint }).catch(() => {});
      await sub.unsubscribe();
    }
  } catch {
    /* best effort */
  }
}

export function NotificationsBox() {
  const n = useNotifications();
  if (n.state === "checking") return null;
  return (
    <section className="notify-box">
      {n.state === "unsupported" && <p className="muted small">This browser can't show notifications. On Android, open the app from its home-screen icon in Chrome.</p>}
      {n.state === "blocked" && <p className="muted small">Notifications are blocked for this app. Turn them on in the phone's settings: Settings → Apps → Chrome → Notifications.</p>}
      {n.state === "off" && (
        <>
          <p className="small"><strong>Get a buzz</strong> when someone gives you a step, or something goes wrong on your job.</p>
          <button className="btn btn-primary btn-small" onClick={n.turnOn}>Turn on notifications</button>
        </>
      )}
      {n.state === "on" && (
        <div className="notify-on">
          <span className="small">Notifications are on for this phone.</span>
          <button className="btn btn-quiet btn-small" onClick={n.test}>Send a test</button>
          <button className="btn btn-quiet btn-small" onClick={n.turnOff}>Turn off</button>
        </div>
      )}
      {n.error && <p className="error-line">{n.error}</p>}
    </section>
  );
}

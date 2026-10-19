import { useEffect, useRef, useState } from "react";
import { api, setToken } from "../api";
import { ErrorLine, Field, useAction } from "../ui";
import type { User } from "../types";

interface Config {
  google_client_id: string;
  allowed_domain: string;
  dev_login: boolean;
}

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (o: { client_id: string; callback: (r: { credential: string }) => void; hd?: string }) => void;
          renderButton: (el: HTMLElement, o: Record<string, unknown>) => void;
        };
      };
    };
  }
}

export function Login({ onSignedIn }: { onSignedIn: (u: User) => void }) {
  const [config, setConfig] = useState<Config | null>(null);
  const [email, setEmail] = useState("");
  const buttonRef = useRef<HTMLDivElement>(null);
  const { busy, error, setError, run } = useAction();
  const signIn = useRef(onSignedIn);
  signIn.current = onSignedIn;
  const runRef = useRef(run);
  runRef.current = run;

  useEffect(() => {
    api.get<Config>("/config").then(setConfig).catch((e: Error) => setError(e.message));
  }, [setError]);

  useEffect(() => {
    if (!config?.google_client_id || !buttonRef.current) return;
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = () => {
      window.google?.accounts.id.initialize({
        client_id: config.google_client_id,
        hd: config.allowed_domain,
        callback: (r) =>
          runRef.current(async () => {
            const res = await api.post<{ token: string; user: User }>("/auth/google", { credential: r.credential });
            setToken(res.token);
            signIn.current(res.user);
          }),
      });
      if (buttonRef.current) window.google?.accounts.id.renderButton(buttonRef.current, { theme: "outline", size: "large", width: 280 });
    };
    script.onerror = () => setError("Google sign-in couldn't load. If this phone is filtered, the Google sign-in address may need whitelisting.");
    document.head.appendChild(script);
    return () => script.remove();
  }, [config, setError]);

  return (
    <main className="login">
      <div className="login-mark" aria-hidden="true">
        <span />
        <span />
        <span />
        <span className="glaze" />
      </div>
      <h1>Pipeline</h1>
      <p className="lead">Every job, its next step, and who is doing it.</p>

      {config?.google_client_id && <div ref={buttonRef} className="google-btn" />}
      {config && !config.google_client_id && !config.dev_login && (
        <p className="muted">Sign-in isn't set up yet. An admin needs to set GOOGLE_CLIENT_ID.</p>
      )}

      {config?.dev_login && (
        <form
          className="dev-login"
          onSubmit={(e) => {
            e.preventDefault();
            run(async () => {
              const res = await api.post<{ token: string; user: User }>("/auth/dev", { email });
              setToken(res.token);
              onSignedIn(res.user);
            });
          }}
        >
          <Field label="Test sign-in" hint={`Testing only — any @${config.allowed_domain} address.`}>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder={`jay@${config.allowed_domain}`} />
          </Field>
          <button className="btn btn-primary" disabled={busy || !email}>
            Sign in
          </button>
        </form>
      )}
      <ErrorLine error={error} />
    </main>
  );
}

export function Pending({ user, onSignOut }: { user: User; onSignOut: () => void }) {
  return (
    <main className="login">
      <h1>Almost there</h1>
      <p className="lead">
        You're signed in as {user.email}. An admin still needs to set your role, showroom and department before you can see jobs.
      </p>
      <button className="btn btn-quiet" onClick={onSignOut}>
        Sign out
      </button>
    </main>
  );
}

import { useEffect, useRef, useState } from "react";
import { api, setToken } from "../api";
import { ErrorLine, Field, Sheet, useAction } from "../ui";
import { Logo } from "../icons";
import type { User } from "../types";

interface Config {
  google_client_id: string;
  allowed_domain: string;
  dev_login: boolean;
  password_login?: boolean;
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

type SignedIn = { token: string; user: User };

function Mark() {
  return <Logo width={180} className="login-logo" />;
}

export function Login({ onSignedIn }: { onSignedIn: (u: User) => void }) {
  const [config, setConfig] = useState<Config | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [devEmail, setDevEmail] = useState("");
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
            const res = await api.post<SignedIn>("/auth/google", { credential: r.credential });
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

  const finish = (res: SignedIn) => {
    setToken(res.token);
    onSignedIn(res.user);
  };

  return (
    <main className="login">
      <Mark />
      <h1>Pipeline</h1>
      <p className="lead">Every job, its next step, and who's on it.</p>

      <form
        className="pw-login"
        onSubmit={(e) => {
          e.preventDefault();
          run(async () => finish(await api.post<SignedIn>("/auth/login", { email, password })));
        }}
      >
        <Field label="Email">
          <input type="email" autoComplete="username" inputMode="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password" hint="Forgot it? Ask an admin to set a new one.">
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <ErrorLine error={error} />
        <button className="btn btn-primary btn-wide" disabled={busy || !email || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>

      {config?.google_client_id && <div ref={buttonRef} className="google-btn" />}

      {config?.dev_login && (
        <form
          className="dev-login"
          onSubmit={(e) => {
            e.preventDefault();
            run(async () => finish(await api.post<SignedIn>("/auth/dev", { email: devEmail })));
          }}
        >
          <Field label="Test sign-in (no password)" hint="On while DEV_LOGIN=1. Turn it off once your password works.">
            <input type="email" value={devEmail} onChange={(e) => setDevEmail(e.target.value)} placeholder={`jay@${config.allowed_domain}`} />
          </Field>
          <button className="btn btn-quiet" disabled={busy || !devEmail}>
            Test sign-in
          </button>
        </form>
      )}
    </main>
  );
}

/** Pick a new password. Forced after an admin sets a temporary one; optional from the Today screen. */
export function PasswordForm({ me, onDone, forced }: { me: User; onDone: (u: User) => void; forced?: boolean }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const { busy, error, setError, run } = useAction();
  const needsCurrent = me.has_password !== false;
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (next !== again) return setError("The two new passwords don't match.");
        run(async () => {
          const res = await api.post<SignedIn>("/auth/password", { current_password: current, new_password: next });
          setToken(res.token);
          onDone(res.user);
        });
      }}
    >
      {needsCurrent && (
        <Field label={forced ? "Temporary password" : "Current password"}>
          <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </Field>
      )}
      <Field label="New password" hint="At least 8 characters.">
        <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
      </Field>
      <Field label="New password again">
        <input type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} />
      </Field>
      <ErrorLine error={error} />
      <button className="btn btn-primary btn-wide" disabled={busy || next.length < 8 || !again || (needsCurrent && !current)}>
        {busy ? "Saving…" : "Save password"}
      </button>
    </form>
  );
}

export function MustChangePassword({ me, onDone, onSignOut }: { me: User; onDone: (u: User) => void; onSignOut: () => void }) {
  return (
    <main className="login">
      <Mark />
      <h1>Pick your password</h1>
      <p className="lead">You signed in with a temporary password. Choose your own to continue.</p>
      <PasswordForm me={me} onDone={onDone} forced />
      <button className="btn btn-quiet" onClick={onSignOut}>
        Sign out
      </button>
    </main>
  );
}

export function ChangePasswordSheet({ me, onClose, onDone }: { me: User; onClose: () => void; onDone: (u: User) => void }) {
  return (
    <Sheet title={me.has_password === false ? "Set your password" : "Change password"} onClose={onClose}>
      <PasswordForm me={me} onDone={onDone} />
    </Sheet>
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

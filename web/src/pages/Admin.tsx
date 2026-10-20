import { useEffect, useState } from "react";
import { api } from "../api";
import { go, niceDate, niceTime, useApp, useLoad } from "../state";
import { ErrorLine, Field, Loading, Sheet, useAction } from "../ui";
import type { AppSettings, ItemSyncStatus, SyncRun, User } from "../types";

const ROLE_LABEL: Record<string, string> = {
  pending: "Waiting for setup",
  rep: "Rep",
  back_office: "Back office",
  management: "Management",
  viewer: "View only",
};

export function Admin() {
  const { refreshUsers } = useApp();
  const { data, error, reload } = useLoad(() => api.get<User[]>("/users", { include_inactive: 1 }), []);
  const [editing, setEditing] = useState<User | null>(null);
  const [adding, setAdding] = useState(false);
  if (!data) return <main className="page"><Loading error={error} /></main>;
  const pending = data.filter((u) => u.role === "pending" && u.active);
  const rest = data.filter((u) => !(u.role === "pending" && u.active));
  const row = (u: User) => (
    <li key={u.id}>
      <button className="row-btn" onClick={() => setEditing(u)}>
        <strong className={u.active ? "" : "struck"}>{u.name || u.email}</strong>
        <span className="muted">{[ROLE_LABEL[u.role], u.home_showroom, u.default_class, u.is_admin ? "admin" : null, u.active ? null : "deactivated", u.has_password === false ? "no password yet" : u.must_change_password ? "temporary password" : null].filter(Boolean).join(" — ")}</span>
      </button>
    </li>
  );
  return (
    <main className="page">
      <header className="page-head">
        <h1>Team</h1>
        <button className="btn btn-primary btn-small" onClick={() => setAdding(true)}>Add a person</button>
      </header>
      {pending.length > 0 && (
        <section className="section">
          <h2>Waiting for setup</h2>
          <p className="muted">They signed in with Google. Set a role so they can start.</p>
          <ul className="list">{pending.map(row)}</ul>
        </section>
      )}
      <section className="section">
        <h2>Everyone</h2>
        <ul className="list">{rest.map(row)}</ul>
      </section>
      <Defaults people={data.filter((u) => u.active && u.role !== "pending")} />
      <ItemSync />
      {adding && <AddUser onClose={() => setAdding(false)} onDone={() => { setAdding(false); reload(); refreshUsers(); }} />}
      {editing && <EditUser user={editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); reload(); refreshUsers(); }} />}
    </main>
  );
}

function EditUser({ user, onClose, onDone }: { user: User; onClose: () => void; onDone: () => void }) {
  const { meta, me } = useApp();
  const [form, setForm] = useState({
    name: user.name,
    role: (user.role === "pending" ? "rep" : user.role) as User["role"],
    home_showroom: user.home_showroom ?? meta.showrooms[0],
    default_class: user.default_class ?? meta.classes[0],
    is_admin: user.is_admin,
    active: user.active,
  });
  const { busy, error, run } = useAction();
  return (
    <Sheet title={user.email} onClose={onClose}>
      <Field label="Name"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
      <Field label="Role">
        <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as User["role"] })}>
          {Object.entries(ROLE_LABEL).filter(([k]) => k !== "pending").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </Field>
      <Field label="Home showroom" hint="Visits default to this showroom.">
        <select value={form.home_showroom} onChange={(e) => setForm({ ...form, home_showroom: e.target.value })}>
          {meta.showrooms.map((s) => <option key={s}>{s}</option>)}
        </select>
      </Field>
      <Field label="Department" hint="New jobs default to this.">
        <select value={form.default_class} onChange={(e) => setForm({ ...form, default_class: e.target.value })}>
          {meta.classes.map((c) => <option key={c}>{c}</option>)}
        </select>
      </Field>
      <label className="check"><input type="checkbox" checked={form.is_admin} onChange={(e) => setForm({ ...form, is_admin: e.target.checked })} /> Admin</label>
      <label className="check"><input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} /> Can sign in</label>
      {user.id !== me.id && <ResetPassword user={user} onDone={onDone} />}
      {user.id !== me.id && (
        <button type="button" className="btn btn-quiet btn-small" onClick={() => go(`/team/${user.id}`)}>Away or gone…</button>
      )}
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy} onClick={() => run(async () => { await api.patch(`/users/${user.id}`, form); onDone(); })}>Save</button>
      </div>
    </Sheet>
  );
}

function runLine(r: SyncRun): string {
  const when = `${niceDate(r.started_at)}, ${niceTime(r.started_at)}`;
  const what = r.mode === "full" ? "Full list" : "Changes";
  if (r.status === "running") return `${what} — running since ${when} (${r.rows_seen} so far)`;
  if (r.status === "ok") return `${what} — ${when} — ${r.rows_seen.toLocaleString()} item${r.rows_seen === 1 ? "" : "s"}`;
  return `${what} — ${when} — failed`;
}

function ItemSync() {
  const { data, error, reload } = useLoad(() => api.get<ItemSyncStatus>("/sync/items"), []);
  const { busy, error: actionError, run } = useAction();
  const running = !!data?.running;
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(reload, 3000);
    return () => window.clearInterval(t);
  }, [running, reload]);
  const start = (full: boolean) =>
    run(async () => {
      await api.post(`/sync/items${full ? "?full=1" : ""}`);
      window.setTimeout(reload, 800);
    });
  const last = data?.runs[0];
  return (
    <section className="section">
      <h2>NetSuite items</h2>
      {!data ? (
        <Loading error={error} />
      ) : !data.configured ? (
        <p className="muted">Not connected. Add the NetSuite keys on Railway (NS_ACCOUNT_ID, NS_CONSUMER_KEY, NS_CONSUMER_SECRET, NS_TOKEN_ID, NS_TOKEN_SECRET) and redeploy.</p>
      ) : (
        <>
          <p className="muted">
            <strong>{data.items_stock.toLocaleString()} stocking items</strong> searchable (custitem4), out of {data.items_active.toLocaleString()} active in NetSuite.
            {data.items_stock > 0 && data.items_with_unit < data.items_stock && ` ${(data.items_stock - data.items_with_unit).toLocaleString()} have no unit label.`}
            {" "}Refreshes from NetSuite {data.every_minutes > 0 ? `every ${data.every_minutes} minutes` : "only when you press Sync now"}. Read-only — nothing is sent to NetSuite.
          </p>
          {last?.status === "failed" && <p className="error-line" role="alert">Last sync failed: {last.error}</p>}
          <ul className="list sync-runs">
            {data.runs.map((r) => (
              <li key={r.id} className="muted">{runLine(r)}</li>
            ))}
          </ul>
          <ErrorLine error={actionError} />
          <div className="actions">
            <button className="btn btn-quiet" disabled={busy || running} onClick={() => start(true)}>Full refresh</button>
            <button className="btn btn-primary" disabled={busy || running} onClick={() => start(false)}>{running ? "Syncing…" : "Sync now"}</button>
          </div>
        </>
      )}
    </section>
  );
}

/** Easy to read out over the phone: no look-alike characters. */
function makeTempPassword(): string {
  const chars = "abcdefghjkmnpqrstuvwxyz23456789";
  const pick = () => chars[Math.floor(Math.random() * chars.length)];
  return `${Array.from({ length: 4 }, pick).join("")}-${Array.from({ length: 4 }, pick).join("")}`;
}

function TempPasswordField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <Field label="Temporary password" hint="Give it to them. They pick their own the first time they sign in.">
      <div className="inline-input">
        <input value={value} onChange={(e) => onChange(e.target.value)} autoComplete="off" spellCheck={false} />
        <button type="button" className="btn btn-quiet btn-small" onClick={() => onChange(makeTempPassword())}>Make one</button>
      </div>
    </Field>
  );
}

function AddUser({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { meta } = useApp();
  const [form, setForm] = useState({
    email: "",
    name: "",
    role: "rep",
    home_showroom: meta.showrooms[0],
    default_class: meta.classes[0],
    is_admin: false,
    password: makeTempPassword(),
  });
  const { busy, error, run } = useAction();
  const [created, setCreated] = useState(false);
  if (created) {
    return (
      <Sheet title="Added" onClose={onDone}>
        <PasswordHandoff name={form.name} email={form.email} password={form.password} />
        <div className="actions"><button className="btn btn-primary" onClick={onDone}>Done</button></div>
      </Sheet>
    );
  }
  return (
    <Sheet title="Add a person" onClose={onClose}>
      <Field label="Name"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
      <Field label="Email" hint="This is what they sign in with.">
        <input type="email" inputMode="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
      </Field>
      <Field label="Role">
        <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
          {Object.entries(ROLE_LABEL).filter(([k]) => k !== "pending").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </Field>
      <Field label="Home showroom" hint="Visits default to this showroom.">
        <select value={form.home_showroom} onChange={(e) => setForm({ ...form, home_showroom: e.target.value })}>
          {meta.showrooms.map((s) => <option key={s}>{s}</option>)}
        </select>
      </Field>
      <Field label="Department" hint="New jobs default to this.">
        <select value={form.default_class} onChange={(e) => setForm({ ...form, default_class: e.target.value })}>
          {meta.classes.map((c) => <option key={c}>{c}</option>)}
        </select>
      </Field>
      <TempPasswordField value={form.password} onChange={(password) => setForm({ ...form, password })} />
      <label className="check"><input type="checkbox" checked={form.is_admin} onChange={(e) => setForm({ ...form, is_admin: e.target.checked })} /> Admin</label>
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button
          className="btn btn-primary"
          disabled={busy || !form.name.trim() || !form.email.trim() || form.password.length < 8}
          onClick={() => run(async () => { await api.post("/users", form); setCreated(true); })}
        >
          Add
        </button>
      </div>
    </Sheet>
  );
}

function ResetPassword({ user, onDone }: { user: User; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState(false);
  const [password, setPassword] = useState(makeTempPassword());
  const { busy, error, run } = useAction();
  if (saved) {
    return (
      <div className="reset-box">
        <PasswordHandoff name={user.name} email={user.email} password={password} />
        <button type="button" className="btn btn-small" onClick={onDone}>Done</button>
      </div>
    );
  }
  if (!open) {
    return (
      <button type="button" className="btn btn-quiet btn-small" onClick={() => setOpen(true)}>
        {user.has_password ? "Reset password" : "Set a password"}
      </button>
    );
  }
  return (
    <div className="reset-box">
      <TempPasswordField value={password} onChange={setPassword} />
      <ErrorLine error={error} />
      <button
        type="button"
        className="btn btn-small"
        disabled={busy || password.length < 8}
        onClick={() => run(async () => { await api.post(`/users/${user.id}/password`, { password }); setSaved(true); })}
      >
        Save temporary password
      </button>
    </div>
  );
}

function PasswordHandoff({ name, email, password }: { name: string; email: string; password: string }) {
  return (
    <div className="handoff">
      <p>Give {name || "them"} these. They'll pick their own password the first time they sign in.</p>
      <dl>
        <dt>Email</dt><dd>{email.trim().toLowerCase()}</dd>
        <dt>Temporary password</dt><dd className="mono">{password}</dd>
      </dl>
      <p className="muted small">This is the only time the password is shown.</p>
    </div>
  );
}

function Defaults({ people }: { people: User[] }) {
  const { toast } = useApp();
  const { data, error, reload } = useLoad(() => api.get<AppSettings>("/settings"), []);
  const { busy, error: saveError, run } = useAction();
  if (!data) return <section className="section"><h2>Defaults</h2><Loading error={error} /></section>;
  return (
    <section className="section">
      <h2>Defaults</h2>
      <Field label="Takeoff person" hint="New takeoffs go to them. Anyone can pick someone else on the job when they're out.">
        <select
          value={data.takeoff_user_id ?? ""}
          disabled={busy}
          onChange={(e) =>
            run(async () => {
              await api.put("/settings", { takeoff_user_id: e.target.value ? Number(e.target.value) : null });
              reload();
              toast("Saved.");
            })
          }
        >
          <option value="">Nobody yet</option>
          {people.map((u) => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}
        </select>
      </Field>
      <ErrorLine error={saveError} />
    </section>
  );
}

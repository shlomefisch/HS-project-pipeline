import { useState } from "react";
import { api } from "../api";
import { useApp, useLoad } from "../state";
import { ErrorLine, Field, Loading, Sheet, useAction } from "../ui";
import type { User } from "../types";

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
  if (!data) return <main className="page"><Loading error={error} /></main>;
  const pending = data.filter((u) => u.role === "pending" && u.active);
  const rest = data.filter((u) => !(u.role === "pending" && u.active));
  const row = (u: User) => (
    <li key={u.id}>
      <button className="row-btn" onClick={() => setEditing(u)}>
        <strong className={u.active ? "" : "struck"}>{u.name || u.email}</strong>
        <span className="muted">{[ROLE_LABEL[u.role], u.home_showroom, u.default_class, u.is_admin ? "admin" : null, u.active ? null : "deactivated"].filter(Boolean).join(" — ")}</span>
      </button>
    </li>
  );
  return (
    <main className="page">
      <header className="page-head"><h1>Team</h1></header>
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
      {editing && <EditUser user={editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); reload(); refreshUsers(); }} />}
    </main>
  );
}

function EditUser({ user, onClose, onDone }: { user: User; onClose: () => void; onDone: () => void }) {
  const { meta } = useApp();
  const [form, setForm] = useState({
    name: user.name,
    role: user.role === "pending" ? "rep" : user.role,
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
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy} onClick={() => run(async () => { await api.patch(`/users/${user.id}`, form); onDone(); })}>Save</button>
      </div>
    </Sheet>
  );
}

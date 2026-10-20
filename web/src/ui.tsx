import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "./api";
import { plusDays, useApp } from "./state";
import type { Entity, Match, NextStep, User } from "./types";

// --------------------------------------------------------------- sheet
export function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <header className="sheet-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <div className="sheet-body">{children}</div>
      </div>
    </div>
  );
}

// -------------------------------------------------------------- fields
export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export function ErrorLine({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p className="error-line" role="alert">
      {error}
    </p>
  );
}

/** Runs an async action with a busy flag and a plain-English error. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, setError, run };
}

// ------------------------------------------------------ person picker
/** Pick one of our people. The top chips are who you assign to most. */
export function UserSelect({ value, onChange, label = "Who" }: { value: number | null; onChange: (id: number) => void; label?: string }) {
  const { users, me } = useApp();
  const [suggested, setSuggested] = useState<User[]>([]);
  useEffect(() => {
    api.get<User[]>("/users/assignee-suggestions").then(setSuggested).catch(() => {});
  }, []);
  const quick = useMemo(() => {
    const list: User[] = [];
    const add = (u: User | undefined) => u && !list.some((x) => x.id === u.id) && list.push(u);
    suggested.forEach(add);
    add(users.find((u) => u.id === me.id));
    return list.slice(0, 4);
  }, [suggested, users, me.id]);
  const assignable = users.filter((u) => u.role !== "pending" && u.active);
  return (
    <Field label={label}>
      <div className="chips" role="radiogroup" aria-label={label}>
        {quick.map((u) => (
          <button
            type="button"
            key={u.id}
            role="radio"
            aria-checked={value === u.id}
            className={`chip ${value === u.id ? "chip-on" : ""}`}
            onClick={() => onChange(u.id)}
          >
            {u.id === me.id ? "Me" : u.name}
          </button>
        ))}
      </div>
      <select value={value ?? ""} onChange={(e) => onChange(Number(e.target.value))}>
        <option value="" disabled>
          Someone else…
        </option>
        {assignable.map((u) => (
          <option key={u.id} value={u.id}>
            {u.name}
          </option>
        ))}
      </select>
    </Field>
  );
}

// ------------------------------------------------------- next step
export function NextStepFields({ value, onChange, heading = "Next step" }: { value: NextStep; onChange: (v: NextStep) => void; heading?: string }) {
  return (
    <fieldset className="next-step">
      <legend>{heading}</legend>
      <Field label="What has to happen">
        <input value={value.title} onChange={(e) => onChange({ ...value, title: e.target.value })} />
      </Field>
      <UserSelect value={value.assignee_id} onChange={(id) => onChange({ ...value, assignee_id: id })} />
      <Field label="By when">
        <div className="chips">
          {[
            ["Today", 0],
            ["Tomorrow", 1],
            ["In 3 days", 3],
            ["Next week", 7],
          ].map(([label, n]) => (
            <button
              type="button"
              key={label}
              className={`chip ${value.due_date === plusDays(n as number) ? "chip-on" : ""}`}
              onClick={() => onChange({ ...value, due_date: plusDays(n as number) })}
            >
              {label}
            </button>
          ))}
        </div>
        <input type="date" value={value.due_date} onChange={(e) => onChange({ ...value, due_date: e.target.value })} />
      </Field>
    </fieldset>
  );
}

export function blankStep(assignee: number, title = ""): NextStep {
  return { title, assignee_id: assignee, due_date: plusDays(1), severity: "silent" };
}

// ----------------------------------------------------- entity picker
/** One box: pick a person or company in the system, or add one after seeing possible duplicates. */
export function EntityPicker({ onPick, placeholder = "Name, phone or email" }: { onPick: (e: Entity) => void; placeholder?: string }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Entity[]>([]);
  const [adding, setAdding] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => {
    window.clearTimeout(timer.current);
    if (!q.trim()) {
      setResults([]);
      return;
    }
    timer.current = window.setTimeout(() => {
      api.get<Entity[]>("/entities", { q }).then(setResults).catch(() => setResults([]));
    }, 200);
  }, [q]);

  if (adding) return <NewEntityForm initialName={q} onCreated={onPick} onCancel={() => setAdding(false)} />;
  return (
    <div className="picker">
      <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder={placeholder} aria-label="Search people" />
      <ul className="list">
        {results.map((e) => (
          <li key={e.id}>
            <button type="button" className="row-btn" onClick={() => onPick(e)}>
              <strong>{e.name}</strong>
              <span className="muted">{[e.kind === "company" ? "Company" : null, e.phone, e.email].filter(Boolean).join(", ")}</span>
            </button>
          </li>
        ))}
      </ul>
      <button type="button" className="btn btn-quiet" onClick={() => setAdding(true)}>
        Add someone new{q.trim() ? `: “${q.trim()}”` : ""}
      </button>
    </div>
  );
}

export function NewEntityForm({ initialName = "", onCreated, onCancel }: { initialName?: string; onCreated: (e: Entity) => void; onCancel: () => void }) {
  const [form, setForm] = useState({ name: initialName, kind: "person" as "person" | "company", phone: "", email: "" });
  const [matches, setMatches] = useState<Match[] | null>(null);
  const { busy, error, run } = useAction();

  const save = (confirm_new: boolean) =>
    run(async () => {
      try {
        const e = await api.post<Entity>("/entities", { ...form, confirm_new });
        onCreated(e);
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          setMatches((err.detail as { matches: Match[] }).matches);
          return;
        }
        throw err;
      }
    });

  if (matches) {
    return (
      <div className="dupes">
        <p className="lead">Is it one of these? Matching on phone, email and name.</p>
        <ul className="list">
          {matches.map((m) => (
            <li key={m.entity.id}>
              <button type="button" className="row-btn" onClick={() => onCreated(m.entity)}>
                <strong>{m.entity.name}</strong>
                <span className="muted">
                  {m.reasons.join(", ")}
                  {m.entity.phone ? ` — ${m.entity.phone}` : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
        <div className="actions">
          <button type="button" className="btn btn-quiet" onClick={() => setMatches(null)}>
            Back
          </button>
          <button type="button" className="btn" disabled={busy} onClick={() => save(true)}>
            None of these — add new
          </button>
        </div>
        <ErrorLine error={error} />
      </div>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save(false);
      }}
    >
      <div className="chips">
        {(["person", "company"] as const).map((k) => (
          <button type="button" key={k} className={`chip ${form.kind === k ? "chip-on" : ""}`} onClick={() => setForm({ ...form, kind: k })}>
            {k === "person" ? "Person" : "Company"}
          </button>
        ))}
      </div>
      <Field label="Name">
        <input autoFocus required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </Field>
      <Field label="Phone">
        <input type="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
      </Field>
      <Field label="Email">
        <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
      </Field>
      <ErrorLine error={error} />
      <div className="actions">
        <button type="button" className="btn btn-quiet" onClick={onCancel}>
          Cancel
        </button>
        <button className="btn btn-primary" disabled={busy || !form.name.trim()}>
          Add
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------- misc
export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

export function Loading({ error }: { error?: string | null }) {
  return error ? <ErrorLine error={error} /> : <p className="loading">Loading…</p>;
}

export const STATUS_LABEL: Record<string, string> = {
  active: "Active",
  on_hold: "On hold",
  lost: "Lost",
  closed: "Closed",
};

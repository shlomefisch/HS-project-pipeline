import { useEffect, useState } from "react";
import { api } from "../api";
import { go, niceDate, useApp, useLoad } from "../state";
import { Empty, ErrorLine, Field, Loading, NewEntityForm, Sheet, STATUS_LABEL, useAction } from "../ui";
import type { Entity } from "../types";

export function People() {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [adding, setAdding] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(q), 250);
    return () => window.clearTimeout(t);
  }, [q]);
  const { data, error } = useLoad(() => api.get<Entity[]>("/entities", { q: debounced }), [debounced]);
  return (
    <main className="page">
      <header className="page-head">
        <h1>People</h1>
        <button className="btn btn-primary" onClick={() => setAdding(true)}>
          Add
        </button>
      </header>
      <input className="search" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, phone or email" aria-label="Search people" />
      {!data ? (
        <Loading error={error} />
      ) : data.length === 0 ? (
        <Empty>{debounced ? "Nobody by that name, phone or email." : "No one yet."}</Empty>
      ) : (
        <>
          <ul className="list only-phone">
            {data.map((e) => (
              <li key={e.id}>
                <a className="row-link" href={`#/people/${e.id}`}>
                  <strong>{e.name}</strong>
                  <span className="muted">{[e.kind === "company" ? "Company" : null, e.phone, e.email].filter(Boolean).join(", ")}</span>
                </a>
              </li>
            ))}
          </ul>
          <table className="data-table only-desk">
            <thead>
              <tr><th>Name</th><th>Type</th><th>Phone</th><th>Email</th><th className="num">Open jobs</th></tr>
            </thead>
            <tbody>
              {data.map((e) => (
                <tr key={e.id} onClick={() => go(`people/${e.id}`)} className="clickable">
                  <td><a href={`#/people/${e.id}`} onClick={(ev) => ev.stopPropagation()}><strong>{e.name}</strong></a></td>
                  <td className="muted">{e.kind === "company" ? "Company" : "Person"}</td>
                  <td>{e.phone ? <a href={`tel:${e.phone}`} onClick={(ev) => ev.stopPropagation()}>{e.phone}</a> : <span className="muted">—</span>}</td>
                  <td>{e.email ? <a href={`mailto:${e.email}`} onClick={(ev) => ev.stopPropagation()}>{e.email}</a> : <span className="muted">—</span>}</td>
                  <td className="num">{(e as Entity & { open_jobs?: number }).open_jobs ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {adding && (
        <Sheet title="Add someone" onClose={() => setAdding(false)}>
          <NewEntityForm initialName={q} onCancel={() => setAdding(false)} onCreated={(e) => go(`people/${e.id}`)} />
        </Sheet>
      )}
    </main>
  );
}

interface EntityPage {
  entity: Entity;
  jobs: { job_id: number; job_name: string; job_status: string; class_code: string; role: string; role_active: boolean; started_at: string; ended_at: string | null }[];
  company: Entity | null;
  contacts: Entity[];
  merged_into: Entity | null;
}

/** One person or company, and every job they are on — "all of Rifky's jobs". */
export function PersonPage({ id }: { id: number }) {
  const { meta, me } = useApp();
  const { data, error, reload } = useLoad(() => api.get<EntityPage>(`/entities/${id}`), [id]);
  const [editing, setEditing] = useState(false);
  const [merging, setMerging] = useState(false);
  if (!data) return <main className="page"><Loading error={error} /></main>;
  const e = data.entity;
  const current = data.jobs.filter((j) => j.role_active);
  const past = data.jobs.filter((j) => !j.role_active);
  return (
    <main className="page">
      <header className="job-head">
        <a href="#/people" className="back">People</a>
        <h1>{e.name}</h1>
        <p className="muted">{[e.kind === "company" ? "Company" : null, e.phone, e.email, data.company ? `at ${data.company.name}` : null].filter(Boolean).join(" — ")}</p>
        {data.merged_into && (
          <p className="status-banner status-on_hold">
            Merged into <a href={`#/people/${data.merged_into.id}`}>{data.merged_into.name}</a>
          </p>
        )}
      </header>
      <div className="job-actions">
        {e.phone && <a className="btn btn-primary" href={`tel:${e.phone}`}>Call</a>}
        {e.active && <button className="btn" onClick={() => setEditing(true)}>Edit</button>}
        {me.is_admin && e.active && <button className="btn btn-quiet" onClick={() => setMerging(true)}>Merge a duplicate into this</button>}
      </div>
      <section className="section">
        <h2>Jobs</h2>
        {current.length === 0 ? (
          <Empty>Not on any open role right now.</Empty>
        ) : (
          <ul className="list">
            {current.map((j) => (
              <li key={`${j.job_id}-${j.role}`}>
                <a className="row-link" href={`#/jobs/${j.job_id}`}>
                  <strong>{j.job_name}</strong>
                  <span className="muted">{meta.role_labels[j.role] ?? j.role} — {STATUS_LABEL[j.job_status] ?? j.job_status} — {j.class_code}</span>
                </a>
              </li>
            ))}
          </ul>
        )}
        {past.length > 0 && (
          <>
            <h2>Before</h2>
            <ul className="list list-quiet">
              {past.map((j) => (
                <li key={`${j.job_id}-${j.role}-${j.started_at}`}>
                  <a className="row-link" href={`#/jobs/${j.job_id}`}>
                    <span>{j.job_name}</span>
                    <span className="muted">{meta.role_labels[j.role] ?? j.role}, until {niceDate(j.ended_at)}</span>
                  </a>
                </li>
              ))}
            </ul>
          </>
        )}
        {data.contacts.length > 0 && (
          <>
            <h2>People at {e.name}</h2>
            <ul className="list">
              {data.contacts.map((c) => (
                <li key={c.id}><a className="row-link" href={`#/people/${c.id}`}><strong>{c.name}</strong><span className="muted">{c.phone ?? ""}</span></a></li>
              ))}
            </ul>
          </>
        )}
      </section>
      {editing && <EditEntity entity={e} onClose={() => setEditing(false)} onDone={() => { setEditing(false); reload(); }} />}
      {merging && <MergeInto target={e} onClose={() => setMerging(false)} onDone={() => { setMerging(false); reload(); }} />}
    </main>
  );
}

function EditEntity({ entity, onClose, onDone }: { entity: Entity; onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({ name: entity.name, phone: entity.phone ?? "", email: entity.email ?? "", address: entity.address ?? "", notes: entity.notes ?? "" });
  const { busy, error, run } = useAction();
  return (
    <Sheet title="Edit" onClose={onClose}>
      {(["name", "phone", "email", "address", "notes"] as const).map((k) => (
        <Field key={k} label={k[0].toUpperCase() + k.slice(1)}>
          {k === "notes" ? <textarea rows={2} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} /> : <input value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />}
        </Field>
      ))}
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || !form.name.trim()} onClick={() => run(async () => { await api.patch(`/entities/${entity.id}`, form); onDone(); })}>Save</button>
      </div>
    </Sheet>
  );
}

function MergeInto({ target, onClose, onDone }: { target: Entity; onClose: () => void; onDone: () => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Entity[]>([]);
  const [pick, setPick] = useState<Entity | null>(null);
  const { busy, error, run } = useAction();
  useEffect(() => {
    if (!q.trim()) return setResults([]);
    let live = true;
    const t = window.setTimeout(() => api.get<Entity[]>("/entities", { q }).then((r) => { if (live) setResults(r.filter((x) => x.id !== target.id)); }).catch(() => {}), 200);
    return () => { live = false; window.clearTimeout(t); };
  }, [q, target.id]);
  return (
    <Sheet title={`Merge into ${target.name}`} onClose={onClose}>
      {!pick ? (
        <>
          <Field label="Find the duplicate">
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} />
          </Field>
          <ul className="list">
            {results.map((r) => (
              <li key={r.id}><button className="row-btn" onClick={() => setPick(r)}><strong>{r.name}</strong><span className="muted">{[r.phone, r.email].filter(Boolean).join(", ")}</span></button></li>
            ))}
          </ul>
        </>
      ) : (
        <>
          <p>
            Every job, contact and visit for <strong>{pick.name}</strong> moves to <strong>{target.name}</strong>. The duplicate is kept, marked as merged — nothing is deleted.
          </p>
          <ErrorLine error={error} />
          <div className="actions">
            <button className="btn btn-quiet" onClick={() => setPick(null)}>Back</button>
            <button className="btn btn-danger" disabled={busy} onClick={() => run(async () => { await api.post(`/entities/${pick.id}/merge-into/${target.id}`); onDone(); })}>Merge</button>
          </div>
        </>
      )}
    </Sheet>
  );
}

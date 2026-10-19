import { useEffect, useState } from "react";
import { api } from "../api";
import { go, niceDate, useApp, useLoad } from "../state";
import { blankStep, Empty, EntityPicker, ErrorLine, Field, Loading, NextStepFields, Sheet, STATUS_LABEL, UserSelect, useAction } from "../ui";
import type { Entity, Job, JobSummary, NextStep } from "../types";

export function Jobs() {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [mine, setMine] = useState(true);
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(q), 250);
    return () => window.clearTimeout(t);
  }, [q]);
  const { data, error } = useLoad(() => api.get<JobSummary[]>("/jobs", { q: debounced, mine: mine && !debounced ? 1 : undefined }), [debounced, mine]);

  return (
    <main className="page">
      <header className="page-head">
        <h1>Jobs</h1>
        <button className="btn btn-primary" onClick={() => go("jobs/new")}>
          New job
        </button>
      </header>
      <input className="search" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Job, address, person or phone" aria-label="Search jobs" />
      {!debounced && (
        <div className="seg" role="tablist">
          <button role="tab" aria-selected={mine} className={mine ? "on" : ""} onClick={() => setMine(true)}>
            Mine
          </button>
          <button role="tab" aria-selected={!mine} className={!mine ? "on" : ""} onClick={() => setMine(false)}>
            Everyone's
          </button>
        </div>
      )}
      {!data ? (
        <Loading error={error} />
      ) : data.length === 0 ? (
        <Empty>{debounced ? "No job matches that." : "No jobs yet. Start one when someone calls or walks in."}</Empty>
      ) : (
        <ul className="list">
          {data.map((j) => (
            <li key={j.id} className={j.stuck ? "task-alert" : ""}>
              <a href={`#/jobs/${j.id}`} className="row-link">
                <strong>{j.name}</strong>
                <span className="muted">
                  {j.status !== "active" ? `${STATUS_LABEL[j.status]} — ` : ""}
                  {j.default_contact?.name ?? ""}
                  {j.stuck ? " — no next step" : j.next_due ? ` — next step ${niceDate(j.next_due).toLowerCase()}` : ""}
                  {!mine || debounced ? ` — ${j.rep?.name ?? ""}` : ""}
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

// ------------------------------------------------------------ new job
interface Person {
  entity: Entity;
  role: string;
}

export function NewJob() {
  const { me, meta, toast } = useApp();
  const [name, setName] = useState("");
  const [people, setPeople] = useState<Person[]>([]);
  const [picking, setPicking] = useState(false);
  const [repId, setRepId] = useState<number | null>(me.role === "rep" ? me.id : null);
  const [classCode, setClassCode] = useState(me.default_class ?? "");
  const [leadSource, setLeadSource] = useState("");
  const [summary, setSummary] = useState("");
  const [step, setStep] = useState<NextStep>(blankStep(me.id, "Book the showroom visit"));
  const { busy, error, run } = useAction();

  const ready = name.trim() && people.length > 0 && repId && classCode && step.title.trim();

  return (
    <main className="page">
      <header className="page-head">
        <h1>New job</h1>
      </header>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          run(async () => {
            const job = await api.post<Job>("/jobs", {
              name,
              rep_id: repId,
              class_code: classCode,
              lead_source: leadSource || null,
              people: people.map((p) => ({ entity_id: p.entity.id, role: p.role })),
              first_event: summary.trim() ? { kind: "contact", channel: "phone", direction: "in", summary } : null,
              next_step: step,
            });
            toast("Job started");
            go(`jobs/${job.id}`);
          });
        }}
      >
        <Field label="Job name" hint="Whatever you heard — “Kisch – Mountain” is fine. Rename it when the address is confirmed.">
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Kisch – Mountain" />
        </Field>

        <fieldset>
          <legend>Who is on it</legend>
          {people.map((p, i) => (
            <div className="person-line" key={p.entity.id}>
              <strong>{p.entity.name}</strong>
              <select value={p.role} onChange={(e) => setPeople(people.map((x, j) => (j === i ? { ...x, role: e.target.value } : x)))} aria-label={`Role for ${p.entity.name}`}>
                {Object.entries(meta.role_labels).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
              <button type="button" className="icon-btn" aria-label={`Remove ${p.entity.name}`} onClick={() => setPeople(people.filter((_, j) => j !== i))}>
                ✕
              </button>
            </div>
          ))}
          <button type="button" className="btn btn-quiet" onClick={() => setPicking(true)}>
            {people.length ? "Add another person" : "Add a person"}
          </button>
        </fieldset>

        <UserSelect label="Rep" value={repId} onChange={setRepId} />
        <Field label="Department">
          <select value={classCode} onChange={(e) => setClassCode(e.target.value)}>
            <option value="" disabled>
              Pick one
            </option>
            {meta.classes.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </Field>
        <Field label="How they found us">
          <select value={leadSource} onChange={(e) => setLeadSource(e.target.value)}>
            <option value="">Not sure yet</option>
            {Object.entries(meta.lead_sources).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>
        <Field label="What was said" hint="Optional. Saved as the first contact on the job.">
          <textarea rows={2} value={summary} onChange={(e) => setSummary(e.target.value)} placeholder="Rifky called: coming in with Kisch next week" />
        </Field>

        <NextStepFields value={step} onChange={setStep} />
        <ErrorLine error={error} />
        <div className="actions">
          <button type="button" className="btn btn-quiet" onClick={() => go("jobs")}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy || !ready}>
            Start job
          </button>
        </div>
      </form>

      {picking && (
        <Sheet title="Add a person" onClose={() => setPicking(false)}>
          <EntityPicker
            onPick={(e) => {
              if (!people.some((p) => p.entity.id === e.id)) setPeople([...people, { entity: e, role: people.length === 0 ? "designer" : "owner" }]);
              setPicking(false);
            }}
          />
        </Sheet>
      )}
    </main>
  );
}

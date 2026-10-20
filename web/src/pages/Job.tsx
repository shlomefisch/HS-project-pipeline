import { useState } from "react";
import { api } from "../api";
import { niceDate, niceTime, useApp, useLoad } from "../state";
import { Empty, EntityPicker, Loading, Sheet, STATUS_LABEL, useAction, ErrorLine, Field } from "../ui";
import type { AuditEntry, Job, Task, Visit } from "../types";
import { CompleteTask } from "./TaskActions";
import { ProgressTiles } from "../progress";
import { Icon } from "../icons";
import { Selection } from "./JobSelection";
import { Plans } from "./JobPlans";
import { EstimateTab } from "./JobEstimate";
import { Orders } from "./JobOrders";
import { NowPanel, Overview, type JobTab } from "./JobOverview";
import { AddTask, EditJob, HoldJob, LogEvent, LoseJob, ResolveVisit, ReviveJob, ScheduleVisit } from "./JobSheets";

type Tab = JobTab;
type SheetKind = null | "log" | "schedule" | "task" | "edit" | "hold" | "lose" | "revive" | "more";

export function JobPage({ id }: { id: number }) {
  const { data: job, error, reload } = useLoad(() => api.get<Job>(`/jobs/${id}`), [id]);
  const [tab, setTab] = useState<Tab>("overview");
  const [sheet, setSheet] = useState<SheetKind>(null);
  const [logVisit, setLogVisit] = useState<Visit | null>(null);
  const { userName } = useApp();

  if (!job) return <main className="page"><Loading error={error} /></main>;
  const close = () => {
    setSheet(null);
    setLogVisit(null);
  };
  const done = () => {
    close();
    reload();
  };
  const contact = job.roles.find((r) => r.entity.id === job.default_contact_id && r.active)?.entity;

  return (
    <main className="page job">
      <header className="job-head">
        <a href="#/jobs" className="back">
          Jobs
        </a>
        <h1>{job.name}</h1>
        <ProgressTiles progress={job.progress} size="large" onPick={(key) => setTab(STAGE_TAB[key] ?? "overview")} />
        <p className="muted">
          {[job.address && job.address !== job.name ? job.address : null, job.class_code, `Rep: ${userName(job.rep_id)}`, contact ? `Contact: ${contact.name}` : null]
            .filter(Boolean)
            .join(" — ")}
        </p>
        {job.status !== "active" && (
          <p className={`status-banner status-${job.status}`}>
            {STATUS_LABEL[job.status]}
            {job.status === "on_hold" && ` until ${niceDate(job.hold_until)} — ${job.hold_reason}`}
            {job.status === "lost" && ` — ${job.lost_reason}${job.lost_note ? `: ${job.lost_note}` : ""}`}
          </p>
        )}
        {job.stuck && <p className="status-banner status-stuck">No next step. Nobody is doing anything on this job — add one.</p>}
      </header>

      {job.status !== "lost" && (
        <div className="job-actions">
          <button className="btn btn-primary" onClick={() => setSheet("log")}>
            Log what happened
          </button>
          <button className="btn" onClick={() => setSheet("schedule")}>
            Book a visit
          </button>
          <button className="btn" onClick={() => setSheet("task")}>
            Add a step
          </button>
          <button className="btn btn-quiet" onClick={() => setSheet("more")} aria-label="More actions">
            More
          </button>
        </div>
      )}
      {job.status === "lost" && (
        <div className="job-actions">
          <button className="btn btn-primary" onClick={() => setSheet("revive")}>
            Bring this job back
          </button>
        </div>
      )}

      {job.status !== "closed" && job.status !== "lost" && <NowPanel job={job} onGo={setTab} reload={reload} />}

      <div className="job-body">
      <div className="job-main">
      <nav className="tabs" role="tablist">
        {(
          [
            ["overview", "Overview"],
            ["selection", "Selection"],
            ["plans", "Plans"],
            ["estimate", "Estimate"],
            ...((job.orders ?? []).length ? ([["orders", "Orders"]] as [Tab, string][]) : []),
            ["steps", `Steps ${job.open_tasks ? `(${job.open_tasks})` : ""}`],
            ["people", "People"],
            ["story", "Story"],
          ] as [Tab, string][]
        ).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </nav>

      {tab === "overview" && <Overview job={job} onGo={setTab} />}
      {tab === "selection" && <Selection job={job} reload={reload} />}
      {tab === "plans" && <Plans job={job} reload={reload} />}
      {tab === "estimate" && <EstimateTab job={job} reload={reload} />}
      {tab === "orders" && <Orders job={job} reload={reload} />}
      {tab === "steps" && <Steps job={job} reload={reload} onLogVisit={(v) => { setLogVisit(v); setSheet("log"); }} />}
      {tab === "people" && <People job={job} reload={reload} />}
      {tab === "story" && <Story jobId={job.id} />}
      </div>
      <JobRail job={job} onSteps={() => setTab("steps")} />
      </div>

      {sheet === "log" && <LogEvent job={job} visit={logVisit} onClose={close} onDone={done} />}
      {sheet === "schedule" && <ScheduleVisit job={job} onClose={close} onDone={done} />}
      {sheet === "task" && <AddTask job={job} onClose={close} onDone={done} />}
      {sheet === "edit" && <EditJob job={job} onClose={close} onDone={done} />}
      {sheet === "hold" && <HoldJob job={job} onClose={close} onDone={done} />}
      {sheet === "lose" && <LoseJob job={job} onClose={close} onDone={done} />}
      {sheet === "revive" && <ReviveJob job={job} onClose={close} onDone={done} />}
      {sheet === "more" && (
        <Sheet title="More" onClose={close}>
          <ul className="list">
            <li><button className="row-btn" onClick={() => setSheet("edit")}><strong>Rename or edit details</strong><span className="muted">Name, address, department, type, how they found us</span></button></li>
            {job.status === "active" && <li><button className="row-btn" onClick={() => setSheet("hold")}><strong>Put on hold</strong><span className="muted">Paused with a date to come back</span></button></li>}
            {job.status === "on_hold" && (
              <li>
                <button className="row-btn" onClick={async () => { await api.post(`/jobs/${job.id}/resume`); done(); }}>
                  <strong>Take off hold</strong>
                  <span className="muted">Back to active now</span>
                </button>
              </li>
            )}
            <li><button className="row-btn" onClick={() => setSheet("lose")}><strong>Close as lost</strong><span className="muted">With the reason</span></button></li>
          </ul>
        </Sheet>
      )}
    </main>
  );
}

// ---------------------------------------------------------------- steps
function Steps({ job, reload, onLogVisit }: { job: Job; reload: () => void; onLogVisit: (v: Visit) => void }) {
  const { userName } = useApp();
  const [open, setOpen] = useState<Task | null>(null);
  const [resolving, setResolving] = useState<Visit | null>(null);
  const [showClosed, setShowClosed] = useState(false);
  const openTasks = job.tasks.filter((t) => t.status === "open" || t.status === "blocked");
  const closed = job.tasks.filter((t) => t.status !== "open" && t.status !== "blocked");
  const booked = job.visits.filter((v) => v.status === "scheduled");

  return (
    <section className="section">
      {booked.length > 0 && (
        <>
          <h2>Booked visits</h2>
          <ul className="list">
            {booked.map((v) => (
              <li key={v.id} className={`row-stack ${new Date(v.starts_at) < new Date() ? "task-alert" : ""}`}>
                <div className="row-static">
                  <strong>
                    {niceDate(v.starts_at)}, {niceTime(v.starts_at)} — {v.kind === "site" ? "site visit" : `showroom${v.showroom ? `, ${v.showroom}` : ""}`}
                  </strong>
                  <span className="muted">
                    {userName(v.rep_id)}
                    {v.purpose ? ` — ${v.purpose}` : ""}
                  </span>
                </div>
                <div className="row-actions">
                  <button className="btn btn-small" onClick={() => onLogVisit(v)}>It happened</button>
                  <button className="btn btn-small btn-quiet" onClick={() => setResolving(v)}>Didn't happen</button>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      <h2>Open steps</h2>
      {openTasks.length === 0 ? (
        <Empty>No open steps. Add one, or this job goes quiet.</Empty>
      ) : (
        <ul className="list">
          {openTasks.map((t) => (
            <li key={t.id} className={`task-row ${t.status === "blocked" ? "task-alert" : ""} ${t.due_date < new Date().toISOString().slice(0, 10) ? "task-overdue" : ""}`}>
              <button className="row-btn" onClick={() => setOpen({ ...t, job_name: job.name, job_rep_id: job.rep_id })}>
                <strong>{t.title}</strong>{t.covering_for_id ? <span className="covering"> covering for {userName(t.covering_for_id)}</span> : null}
                <span className="muted">
                  {userName(t.assignee_id)} — {t.status === "blocked" ? `blocked: ${t.outcome_note}` : `due ${niceDate(t.due_date).toLowerCase()}`}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {closed.length > 0 && (
        <>
          <button className="btn btn-quiet" onClick={() => setShowClosed(!showClosed)}>
            {showClosed ? "Hide" : "Show"} {closed.length} finished
          </button>
          {showClosed && (
            <ul className="list list-quiet">
              {closed.map((t) => (
                <li key={t.id} className="row-static">
                  <span className={t.status === "skipped" ? "struck" : ""}>{t.title}</span>
                  <span className="muted">
                    {t.status === "done" ? "Done" : t.status === "bad_answer" ? "Bad answer" : "Not needed"}
                    {t.outcome_note ? ` — ${t.outcome_note}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {open && <CompleteTask task={open} onClose={() => setOpen(null)} onDone={() => { setOpen(null); reload(); }} />}
      {resolving && <ResolveVisit visit={resolving} job={job} onClose={() => setResolving(null)} onDone={() => { setResolving(null); reload(); }} />}
    </section>
  );
}

// --------------------------------------------------------------- people
function People({ job, reload }: { job: Job; reload: () => void }) {
  const { meta } = useApp();
  const [adding, setAdding] = useState(false);
  const [role, setRole] = useState("owner");
  const [history, setHistory] = useState(false);
  const { error, run } = useAction();
  const active = job.roles.filter((r) => r.active);
  const past = job.roles.filter((r) => !r.active);

  return (
    <section className="section">
      <ul className="list">
        {active.map((r) => (
          <li key={r.id} className="person-row">
            <a href={`#/people/${r.entity.id}`} className="row-link">
              <strong>{r.entity.name}</strong>
              <span className="muted">
                {meta.role_labels[r.role] ?? r.role}
                {r.entity.phone ? ` — ${r.entity.phone}` : ""}
                {job.default_contact_id === r.entity.id ? " — default contact" : ""}
              </span>
            </a>
            <div className="row-actions">
              {r.entity.phone && <a className="btn btn-small" href={`tel:${r.entity.phone}`}>Call</a>}
              {job.default_contact_id !== r.entity.id && (
                <button className="btn btn-small btn-quiet" onClick={() => run(async () => { await api.patch(`/jobs/${job.id}`, { default_contact_id: r.entity.id }); reload(); })}>
                  Make default
                </button>
              )}
              <button className="btn btn-small btn-quiet" onClick={() => run(async () => { await api.del(`/jobs/${job.id}/roles/${r.id}`); reload(); })}>
                Remove
              </button>
            </div>
          </li>
        ))}
      </ul>
      <ErrorLine error={error} />
      <button className="btn" onClick={() => setAdding(true)}>Add someone to the job</button>
      {past.length > 0 && (
        <>
          <button className="btn btn-quiet" onClick={() => setHistory(!history)}>{history ? "Hide" : "Show"} past people</button>
          {history && (
            <ul className="list list-quiet">
              {past.map((r) => (
                <li key={r.id} className="row-static">
                  <span>{r.entity.name}</span>
                  <span className="muted">{meta.role_labels[r.role] ?? r.role}, {niceDate(r.started_at)} to {niceDate(r.ended_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {adding && (
        <Sheet title="Add someone to the job" onClose={() => setAdding(false)}>
          <Field label="As" hint={meta.role_caps[role] === 1 ? "One at a time — whoever holds this role now is replaced, and kept in history." : undefined}>
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              {Object.entries(meta.role_labels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
          <EntityPicker onPick={(e) => run(async () => { await api.post(`/jobs/${job.id}/roles`, { entity_id: e.id, role }); setAdding(false); reload(); })} />
        </Sheet>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- story
function Story({ jobId }: { jobId: number }) {
  const [everything, setEverything] = useState(false);
  const { userName } = useApp();
  const { data, error } = useLoad(() => api.get<AuditEntry[]>(`/jobs/${jobId}/timeline`, { everything: everything ? 1 : undefined }), [jobId, everything]);
  return (
    <section className="section">
      <div className="seg" role="tablist">
        <button role="tab" aria-selected={!everything} className={!everything ? "on" : ""} onClick={() => setEverything(false)}>The story</button>
        <button role="tab" aria-selected={everything} className={everything ? "on" : ""} onClick={() => setEverything(true)}>Everything</button>
      </div>
      {!data ? (
        <Loading error={error} />
      ) : data.length === 0 ? (
        <Empty>Nothing yet.</Empty>
      ) : (
        <ol className="timeline">
          {data.map((e) => (
            <li key={e.id}>
              <span className="when">{niceDate(e.at)}, {niceTime(e.at)}</span>
              <span className="what">{e.summary ?? describe(e)}</span>
              <span className="who">{userName(e.user_id)}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function describe(e: AuditEntry): string {
  const table = e.table_name.replace(/_/g, " ");
  if (e.action === "insert") return `Added to ${table}`;
  const fields = Object.entries(e.changes)
    .map(([k, [from, to]]) => `${k.replace(/_/g, " ")}: ${from ?? "—"} → ${to ?? "—"}`)
    .join("; ");
  return `${table}: ${fields}`;
}

// Tapping a progress tile goes where that stage is worked.
const STAGE_TAB: Record<string, Tab> = {
  lead: "overview", selection: "selection", footage: "plans", availability: "plans",
  estimate: "estimate", ordered: "estimate", delivery: "orders", closed: "orders",
};

// ------------------------------------------- the side panel, on wide screens
function JobRail({ job, onSteps }: { job: Job; onSteps: () => void }) {
  const { userName, meta } = useApp();
  const open = job.tasks.filter((t) => t.status === "open" || t.status === "blocked");
  const upcoming = job.visits.filter((v) => v.status === "scheduled");
  const people = job.roles.filter((r) => r.active);
  const todayIso = new Date().toISOString().slice(0, 10);
  return (
    <aside className="job-rail" aria-label="At a glance">
      <section>
        <h3>Next steps</h3>
        {open.length === 0 ? (
          <p className="rail-empty">Nothing open — add the next step.</p>
        ) : (
          <ul>
            {open.slice(0, 6).map((t) => (
              <li key={t.id}>
                <button className={`rail-item ${t.status === "blocked" ? "rail-bad" : t.due_date < todayIso ? "rail-late" : ""}`} onClick={onSteps}>
                  <strong>{t.title}</strong>
                  <span>{userName(t.assignee_id)} · {t.status === "blocked" ? "blocked" : niceDate(t.due_date)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
      {upcoming.length > 0 && (
        <section>
          <h3>Visits</h3>
          <ul>
            {upcoming.slice(0, 3).map((v) => (
              <li key={v.id} className="rail-line">{niceDate(v.starts_at)}, {niceTime(v.starts_at)} — {v.kind === "site" ? "site visit" : `${v.showroom ?? ""} showroom`}</li>
            ))}
          </ul>
        </section>
      )}
      <section>
        <h3>People</h3>
        <ul>
          {people.map((r) => (
            <li key={r.id} className="rail-person">
              <a href={`#/people/${r.entity.id}`}>
                <strong>{r.entity.name}</strong>
                <span>{meta.role_labels[r.role] ?? r.role}{job.default_contact_id === r.entity.id ? " · contact" : ""}</span>
              </a>
              {r.entity.phone && (
                <a className="icon-btn" href={`tel:${r.entity.phone}`} aria-label={`Call ${r.entity.name}`} title={r.entity.phone}>
                  <Icon name="phone" size={18} />
                </a>
              )}
            </li>
          ))}
        </ul>
      </section>
    </aside>
  );
}

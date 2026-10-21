import { useEffect, useState } from "react";
import { api } from "../api";
import { niceDate, niceTime, useApp, useLoad } from "../state";
import { Empty, EntityPicker, Loading, Sheet, STATUS_LABEL, useAction, ErrorLine, Field } from "../ui";
import type { AuditEntry, Job, Progress, Task, Visit } from "../types";
import { CompleteTask } from "./TaskActions";
import { Icon } from "../icons";
import { Selection } from "./JobSelection";
import { Availability, Files, Footage } from "./JobPlans";
import { EstimateTab } from "./JobEstimate";
import { Orders } from "./JobOrders";
import { NowCard, SECTION_LABEL, STAGE_SECTION, SectionList, whatNow, type Section } from "./JobOverview";
import { AddTask, EditJob, HoldJob, LogEvent, LoseJob, ResolveVisit, ReviveJob, ScheduleVisit } from "./JobSheets";

type SheetKind = null | "log" | "schedule" | "task" | "edit" | "hold" | "lose" | "revive" | "more";

/** Side by side only when the job itself has room — not just a wide screen with the jobs list beside it. */
function useRoomy(): [(el: HTMLElement | null) => void, boolean] {
  const [el, setEl] = useState<HTMLElement | null>(null);
  const [roomy, setRoomy] = useState(false);
  useEffect(() => {
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setRoomy(e.contentRect.width >= 940));
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [setEl, roomy];
}

/** A job, kept simple: who and where it stands at the top, one card saying what's next,
 *  then its parts as a list. One part is open at a time. */
export function JobPage({ id }: { id: number }) {
  const { data: job, error, reload } = useLoad(() => api.get<Job>(`/jobs/${id}`), [id]);
  const [picked, setPicked] = useState<Section | null>(null);
  const [sheet, setSheet] = useState<SheetKind>(null);
  const [logVisit, setLogVisit] = useState<Visit | null>(null);
  const { userName, meta } = useApp();
  const [measure, wide] = useRoomy();

  // A different job starts on its own overview.
  useEffect(() => setPicked(null), [id]);

  if (!job) return <main className="page" ref={measure}><Loading error={error} /></main>;
  const close = () => {
    setSheet(null);
    setLogVisit(null);
  };
  const done = () => {
    close();
    reload();
  };
  const contactRole = job.roles.find((r) => r.entity.id === job.default_contact_id && r.active);
  const contact = contactRole?.entity;
  const active = job.status === "active" || job.status === "on_hold";
  const now = whatNow(job, userName);
  // On a PC one part is always open beside the list; on a phone, only once it's tapped.
  const section: Section | null = picked ?? (wide ? now.go : null);
  const go = (s: Section) => {
    setPicked(s);
    window.scrollTo({ top: 0 });
  };

  const header = (
    <header className="job-top">
      <a href="#/jobs" className="back">Jobs</a>
      <div className="job-title-row">
        <h1>{job.name}</h1>
        <div className="job-title-actions">
          {job.status === "lost" ? (
            <button className="btn btn-primary" onClick={() => setSheet("revive")}>Bring this job back</button>
          ) : (
            <button className="btn btn-primary" onClick={() => setSheet("log")}>Log what happened</button>
          )}
          <button className="btn btn-quiet" onClick={() => setSheet("more")} aria-label="More actions">More</button>
        </div>
      </div>
      <p className="job-who">
        {contact ? (
          <>
            <strong>{contact.name}</strong>
            <span className="muted"> · {meta.role_labels[contactRole!.role] ?? contactRole!.role}</span>
            {contact.phone && (
              <a className="job-call" href={`tel:${contact.phone}`} aria-label={`Call ${contact.name}`}>
                <Icon name="phone" size={16} /> Call
              </a>
            )}
          </>
        ) : (
          <span className="muted">No main contact yet</span>
        )}
        <span className="muted"> · Rep {userName(job.rep_id)}</span>
      </p>
      {job.status !== "active" && (
        <p className={`status-banner status-${job.status}`}>
          {STATUS_LABEL[job.status]}
          {job.status === "on_hold" && ` until ${niceDate(job.hold_until)} — ${job.hold_reason}`}
          {job.status === "lost" && ` — ${job.lost_reason}${job.lost_note ? `: ${job.lost_note}` : ""}`}
        </p>
      )}
      <StageBar progress={job.progress} onPick={(key) => go(STAGE_SECTION[key] ?? "tiles")} />
    </header>
  );

  const content = section && (
    <div className="job-part-view">
      {!wide && (
        <button className="job-part-back" onClick={() => setPicked(null)}>‹ {job.name}</button>
      )}
      <h2 className="job-part-title">{SECTION_LABEL[section]}</h2>
      {section === "tiles" && <Selection job={job} reload={reload} />}
      {section === "footage" && <Footage job={job} reload={reload} />}
      {section === "availability" && <Availability job={job} reload={reload} />}
      {section === "estimate" && <EstimateTab job={job} reload={reload} />}
      {section === "orders" && <Orders job={job} reload={reload} />}
      {section === "files" && <Files job={job} />}
      {section === "steps" && (
        <Steps job={job} reload={reload} onLogVisit={(v) => { setLogVisit(v); setSheet("log"); }} onAdd={() => setSheet("task")} onBook={() => setSheet("schedule")} />
      )}
      {section === "people" && <People job={job} reload={reload} />}
      {section === "history" && <Story jobId={job.id} />}
    </div>
  );

  return (
    <main className={`page job job-simple ${wide ? "is-roomy" : ""}`} ref={measure}>
      {(wide || !section) && header}
      {wide ? (
        <div className="job-split">
          <div className="job-side">
            {active && <NowCard job={job} onGo={go} reload={reload} />}
            <SectionList job={job} current={section} onPick={go} />
          </div>
          <div className="job-content">{content}</div>
        </div>
      ) : section ? (
        content
      ) : (
        <>
          {active && <NowCard job={job} onGo={go} reload={reload} />}
          <SectionList job={job} current={null} onPick={go} />
        </>
      )}

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
            {job.status !== "lost" && <li><button className="row-btn" onClick={() => setSheet("task")}><strong>Add a step</strong><span className="muted">Something someone has to do, with a date</span></button></li>}
            {job.status !== "lost" && <li><button className="row-btn" onClick={() => setSheet("schedule")}><strong>Book a visit</strong><span className="muted">Showroom or site</span></button></li>}
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
            {job.status !== "lost" && job.status !== "closed" && <li><button className="row-btn" onClick={() => setSheet("lose")}><strong>Close as lost</strong><span className="muted">With the reason</span></button></li>}
          </ul>
        </Sheet>
      )}
    </main>
  );
}

/** How far along: a thin bar, one segment per stage, and the stage in words. Tap a segment to open that part. */
function StageBar({ progress, onPick }: { progress?: Progress | null; onPick: (key: string) => void }) {
  if (!progress) return null;
  const n = progress.done;
  const all = progress.stages.length;
  return (
    <div className="stagebar">
      <div className="stagebar-segs" role="group" aria-label={`${n} of ${all} stages done`}>
        {progress.stages.map((s, i) => (
          <button key={s.key} type="button" title={s.label} aria-label={s.label} className={`stagebar-seg ${s.done ? "is-done" : i === n ? "is-now" : ""}`} onClick={() => onPick(s.key)} />
        ))}
      </div>
      <span className="stagebar-text">{n >= all ? "All stages done" : <>Step {n + 1} of {all} · <strong>{progress.current}</strong></>}</span>
    </div>
  );
}

// ---------------------------------------------------------------- steps
function Steps({ job, reload, onLogVisit, onAdd, onBook }: { job: Job; reload: () => void; onLogVisit: (v: Visit) => void; onAdd: () => void; onBook: () => void }) {
  const { userName } = useApp();
  const [open, setOpen] = useState<Task | null>(null);
  const [resolving, setResolving] = useState<Visit | null>(null);
  const [showClosed, setShowClosed] = useState(false);
  const openTasks = job.tasks.filter((t) => t.status === "open" || t.status === "blocked");
  const closed = job.tasks.filter((t) => t.status !== "open" && t.status !== "blocked");
  const booked = job.visits.filter((v) => v.status === "scheduled");

  return (
    <section className="section">
      {job.status !== "lost" && job.status !== "closed" && (
        <div className="actions actions-wrap">
          <button className="btn btn-primary" onClick={onAdd}>Add a step</button>
          <button className="btn" onClick={onBook}>Book a visit</button>
        </div>
      )}
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


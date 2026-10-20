import { useState } from "react";
import { api } from "../api";
import { niceDate, niceTime, useApp, useLoad } from "../state";
import { Empty } from "../ui";
import type { Area, AuditEntry, Job, Task } from "../types";
import { Photo } from "../photo";
import { Icon } from "../icons";
import { CompleteTask } from "./TaskActions";

export type JobTab = "overview" | "selection" | "plans" | "estimate" | "orders" | "steps" | "people" | "story";

const GOOD = ["available", "override", "confirmed"];
const working = (job: Job) => job.areas.filter((a) => a.status === "open" || a.status === "decided");
const chosenIn = (job: Job, areaId: number) => job.candidates.filter((c) => c.tags.some((t) => t.area_id === areaId && t.status === "chosen"));
const names = (list: Area[]) => (list.length <= 2 ? list.map((a) => a.name).join(" and ") : `${list.slice(0, 2).map((a) => a.name).join(", ")} and ${list.length - 2} more`);

/** Where the job stands, in one sentence, and the one place to go next. */
function whatNow(job: Job, userName: (id: number | null | undefined) => string): { stage: string; text: string; go: JobTab; button: string } {
  const p = job.progress;
  const current = p?.stages.find((s) => !s.done)?.key ?? "closed";
  if (job.status === "closed") return { stage: "Closed", text: "Done — nothing open, nothing owed, nothing coming back.", go: "story", button: "See the story" };
  if (job.status === "lost") return { stage: "Lost", text: `Lost — ${job.lost_reason ?? ""}. It can be brought back from the top.`, go: "story", button: "See the story" };
  const live = working(job);
  switch (current) {
    case "selection": {
      if (job.areas.length === 0) return { stage: "Selection", text: "No areas yet. Add the rooms — kitchen, baths, mudroom — then the tiles they're looking at.", go: "selection", button: "Add the areas" };
      const missing = live.filter((a) => chosenIn(job, a.id).length === 0);
      return { stage: "Selection", text: `${names(missing)} ${missing.length === 1 ? "has" : "have"} no tile chosen yet.`, go: "selection", button: "Choose tiles" };
    }
    case "footage": {
      const missing = live.filter((a) => a.footage == null);
      const takeoff = job.tasks.find((t) => t.id === job.open_takeoff_id);
      return {
        stage: "Footage",
        text: `${names(missing)} still ${missing.length === 1 ? "needs" : "need"} a number.` + (takeoff ? ` The takeoff is with ${userName(takeoff.assignee_id)}, due ${niceDate(takeoff.due_date).toLowerCase()}.` : ""),
        go: "plans",
        button: "Enter footage",
      };
    }
    case "availability": {
      const open = live.flatMap((a) => chosenIn(job, a.id).flatMap((c) => c.tags.filter((t) => t.area_id === a.id && t.status === "chosen" && !GOOD.includes(t.avail_status ?? ""))));
      const short = open.filter((t) => t.avail_status === "short" || t.avail_status === "two_lots").length;
      return {
        stage: "Availability",
        text: short ? `${short} tile${short === 1 ? " is" : "s are"} short — the customer needs to hear about it.` : `${open.length} chosen tile${open.length === 1 ? "" : "s"} still to check.`,
        go: "plans",
        button: "Check availability",
      };
    }
    case "estimate":
      return job.draft_estimate_id
        ? { stage: "Estimate", text: "The estimate is being put together. Check the prices and send it.", go: "estimate", button: "Open the estimate" }
        : { stage: "Estimate", text: "Everything is chosen, measured and available. Put the estimate together.", go: "estimate", button: "Build the estimate" };
    case "ordered":
      return { stage: "Ordered", text: "The estimate is ready. Send it, or mark it entered in NetSuite.", go: "estimate", button: "Open the estimate" };
    case "delivery": {
      const o = (job.orders ?? []).find((x) => !["closed", "lost"].includes(x.stage));
      if (o?.stage === "negotiating") return { stage: "Negotiating", text: "Waiting on the customer. When the sales order is made, approve it and pick the handler.", go: "orders", button: "Open the order" };
      return { stage: "Processing", text: `Being processed${o?.handler_id ? ` by ${userName(o.handler_id)}` : ""}. Next: ready for delivery.`, go: "orders", button: "Open the order" };
    }
    default:
      return { stage: "Closing", text: "Delivered. Finish the closing checklist, close the order, then close the job.", go: "orders", button: "Open the order" };
  }
}

/** The top of every job: the stage, what's holding it, and the very next step. */
export function NowPanel({ job, onGo, reload }: { job: Job; onGo: (t: JobTab) => void; reload: () => void }) {
  const { userName } = useApp();
  const [open, setOpen] = useState<Task | null>(null);
  const now = whatNow(job, userName);
  const today = new Date().toISOString().slice(0, 10);
  const next = job.tasks.filter((t) => t.status === "open" || t.status === "blocked").sort((a, b) => a.due_date.localeCompare(b.due_date))[0];
  return (
    <section className="now-panel" aria-label="What's next">
      <div className="now-stage">
        <span className="now-label">Now</span>
        <strong className="now-name">{now.stage}</strong>
        <p className="now-text">{now.text}</p>
        <button className="btn btn-primary" onClick={() => onGo(now.go)}>{now.button}</button>
      </div>
      <div className={`now-next ${!next ? "now-next-none" : next.status === "blocked" ? "now-next-bad" : next.due_date < today ? "now-next-late" : ""}`}>
        <span className="now-label">Next step</span>
        {next ? (
          <>
            <strong>{next.title}</strong>
            <p className="muted small">
              {userName(next.assignee_id)} · {next.status === "blocked" ? `blocked: ${next.outcome_note}` : next.due_date < today ? `overdue since ${niceDate(next.due_date)}` : `due ${niceDate(next.due_date).toLowerCase()}`}
            </p>
            <button className="btn btn-small" onClick={() => setOpen({ ...next, job_name: job.name, job_rep_id: job.rep_id })}><Icon name="check" size={16} /> Done / update</button>
          </>
        ) : (
          <>
            <strong>Nobody has a next step</strong>
            <p className="small">This job goes quiet unless someone owns what happens next.</p>
          </>
        )}
      </div>
      {open && <CompleteTask task={open} onClose={() => setOpen(null)} onDone={() => { setOpen(null); reload(); }} />}
    </section>
  );
}

/** Everything about the job on one screen: every area in a row, then steps, people and what happened lately. */
export function Overview({ job, onGo }: { job: Job; onGo: (t: JobTab) => void }) {
  const { userName, meta } = useApp();
  const story = useLoad(() => api.get<AuditEntry[]>(`/jobs/${job.id}/timeline`), [job.id]);
  const areas = job.areas.filter((a) => a.status !== "dropped");
  const open = job.tasks.filter((t) => t.status === "open" || t.status === "blocked");
  const people = job.roles.filter((r) => r.active);
  const AREA_STATE: Record<string, string> = { open: "Choosing", decided: "Decided", on_hold: "On hold", ordered: "On an order", delivered: "Delivered" };

  return (
    <div className="overview-job">
      <section className="section">
        <div className="section-head"><h2>Areas</h2><button className="btn btn-quiet btn-small" onClick={() => onGo("selection")}>Edit</button></div>
        {areas.length === 0 ? (
          <Empty>No areas yet — add them on the Selection tab.</Empty>
        ) : (
          <div className="area-table" role="table">
            <div className="area-tr area-th" role="row">
              <span role="columnheader">Area</span><span role="columnheader">Tile</span><span role="columnheader">Footage</span><span role="columnheader">Stock</span><span role="columnheader">Where it is</span>
            </div>
            {areas.map((a) => {
              const chosen = chosenIn(job, a.id);
              const first = chosen[0];
              const tags = chosen.flatMap((c) => c.tags.filter((t) => t.area_id === a.id && t.status === "chosen"));
              const considering = job.candidates.filter((c) => c.tags.some((t) => t.area_id === a.id && t.status === "considering")).length;
              const avail = tags.length === 0 ? null : tags.every((t) => GOOD.includes(t.avail_status ?? "")) ? "ok" : tags.some((t) => ["short", "two_lots"].includes(t.avail_status ?? "")) ? "short" : "check";
              return (
                <button key={a.id} className="area-tr" role="row" onClick={() => onGo(a.footage == null && first ? "plans" : "selection")}>
                  <span role="cell" className="area-td-name"><strong>{a.name}</strong></span>
                  <span role="cell" className="area-td-tile">
                    {first ? (
                      <>
                        <Photo url={first.item?.image_url} size={36} />
                        <span>{first.display_name}{chosen.length > 1 && <span className="muted"> +{chosen.length - 1}</span>}</span>
                      </>
                    ) : (
                      <span className="muted">{considering ? `${considering} being considered` : "Nothing yet"}</span>
                    )}
                  </span>
                  <span role="cell">{a.footage != null ? <>{a.footage.toLocaleString()} sf <span className={`pill ${a.footage_confidence === "confirmed" ? "pill-ok" : "pill-warn"}`}>{a.footage_confidence === "confirmed" ? "confirmed" : "approx."}</span></> : a.status === "on_hold" ? <span className="muted">—</span> : <span className="footage-missing">needed</span>}</span>
                  <span role="cell">{avail === "ok" ? <span className="pill pill-ok">available</span> : avail === "short" ? <span className="pill pill-bad">short</span> : avail === "check" ? <span className="pill pill-warn">to check</span> : <span className="muted">—</span>}</span>
                  <span role="cell" className="muted">{AREA_STATE[a.status] ?? a.status}{a.status === "on_hold" && a.hold_until ? ` till ${niceDate(a.hold_until)}` : ""}</span>
                </button>
              );
            })}
          </div>
        )}
      </section>

      <div className="overview-cols">
        <section className="section">
          <div className="section-head"><h2>Open steps</h2><button className="btn btn-quiet btn-small" onClick={() => onGo("steps")}>All steps</button></div>
          {open.length === 0 ? <Empty>Nothing open.</Empty> : (
            <ul className="list">
              {open.slice(0, 5).map((t) => (
                <li key={t.id} className={`task-row ${t.status === "blocked" ? "task-alert" : ""}`}>
                  <button className="row-btn" onClick={() => onGo("steps")}>
                    <strong>{t.title}</strong>
                    <span className="muted">{userName(t.assignee_id)} — {t.status === "blocked" ? "blocked" : `due ${niceDate(t.due_date).toLowerCase()}`}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="section">
          <div className="section-head"><h2>People</h2><button className="btn btn-quiet btn-small" onClick={() => onGo("people")}>Edit</button></div>
          <ul className="list">
            {people.map((r) => (
              <li key={r.id} className="person-line">
                <a href={`#/people/${r.entity.id}`} className="row-link">
                  <strong>{r.entity.name}</strong>
                  <span className="muted">{meta.role_labels[r.role] ?? r.role}{job.default_contact_id === r.entity.id ? " — main contact" : ""}</span>
                </a>
                {r.entity.phone && <a className="btn btn-small" href={`tel:${r.entity.phone}`}><Icon name="phone" size={16} /> Call</a>}
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="section">
        <div className="section-head"><h2>Lately</h2><button className="btn btn-quiet btn-small" onClick={() => onGo("story")}>The whole story</button></div>
        {!story.data ? <p className="muted small">Loading…</p> : (
          <ul className="lately">
            {story.data.filter((e) => e.summary).slice(0, 6).map((e) => (
              <li key={e.id}><span className="muted small">{niceDate(e.at)} {niceTime(e.at)} · {userName(e.user_id)}</span>{e.summary}</li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

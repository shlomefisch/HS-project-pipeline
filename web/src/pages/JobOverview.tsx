import { useState } from "react";
import { isoDate, niceDate, useApp } from "../state";
import type { Job, Task } from "../types";
import { Icon } from "../icons";
import { CompleteTask } from "./TaskActions";
import { chosenTiles, inSqft, num, unitOf } from "../footage";

/** The parts of a job. One is open at a time. */
export type Section = "tiles" | "footage" | "availability" | "estimate" | "orders" | "files" | "steps" | "people" | "history";

const GOOD = ["available", "override", "confirmed"];
const working = (job: Job) => job.areas.filter((a) => a.status === "open" || a.status === "decided");
const names = (list: { name: string }[]) =>
  list.length <= 2 ? list.map((a) => a.name).join(" and ") : `${list.slice(0, 2).map((a) => a.name).join(", ")} and ${list.length - 2} more`;
const todayIso = () => isoDate(new Date());

/** Which stage of the progress bar each part belongs to, and back. */
export const STAGE_SECTION: Record<string, Section> = {
  lead: "tiles", selection: "tiles", footage: "footage", availability: "availability",
  estimate: "estimate", ordered: "estimate", delivery: "orders", closed: "orders",
};

/** Where the job stands, in one sentence, and the one place to go. */
export function whatNow(job: Job, userName: (id: number | null | undefined) => string): { stage: string; text: string; go: Section; button: string } {
  const current = job.progress?.stages.find((s) => !s.done)?.key ?? "closed";
  const live = working(job);
  switch (current) {
    case "lead":
    case "selection": {
      if (job.areas.length === 0) return { stage: "Selection", text: "Add the rooms they talked about, then the tiles they looked at.", go: "tiles", button: "Add the areas" };
      const missing = live.filter((a) => chosenTiles(job, a.id).length === 0);
      if (missing.length === 0) return { stage: "Selection", text: "Every area is on hold or dropped. Reopen one, or add a new area.", go: "tiles", button: "Open tiles" };
      return { stage: "Selection", text: `Choose a tile for ${names(missing)}.`, go: "tiles", button: "Choose tiles" };
    }
    case "footage": {
      const missing = live.filter((a) => chosenTiles(job, a.id).some(({ t }) => t.quantity == null));
      const takeoff = job.tasks.find((t) => t.id === job.open_takeoff_id);
      return {
        stage: "Footage",
        text: `Tiles in ${names(missing)} need their footage.` + (takeoff ? ` The takeoff is with ${userName(takeoff.assignee_id)}.` : ""),
        go: "footage",
        button: "Enter footage",
      };
    }
    case "availability": {
      const tags = live.flatMap((a) => chosenTiles(job, a.id).map(({ t }) => t));
      const short = tags.filter((t) => t.avail_status === "short" || t.avail_status === "two_lots").length;
      const open = tags.filter((t) => !GOOD.includes(t.avail_status ?? "")).length;
      return {
        stage: "Availability",
        text: short ? `${short} tile${short === 1 ? " is" : "s are"} short — the customer needs to hear about it.` : `${open} tile${open === 1 ? "" : "s"} still to check.`,
        go: "availability",
        button: "Check availability",
      };
    }
    case "estimate":
      return job.draft_estimate_id
        ? { stage: "Estimate", text: "The estimate is started. Check the prices and send it.", go: "estimate", button: "Open the estimate" }
        : { stage: "Estimate", text: "Everything is chosen, measured and available. Build the estimate.", go: "estimate", button: "Build the estimate" };
    case "ordered":
      return { stage: "Estimate", text: "The estimate is ready. Send it, or mark it entered in NetSuite.", go: "estimate", button: "Open the estimate" };
    case "delivery": {
      const o = (job.orders ?? []).find((x) => !["closed", "lost"].includes(x.stage));
      if (o?.stage === "negotiating") return { stage: "Negotiating", text: "Waiting on the customer. When the sales order is made, approve it.", go: "orders", button: "Open the order" };
      return { stage: "Processing", text: `Being processed${o?.handler_id ? ` by ${userName(o.handler_id)}` : ""}. Next: ready for delivery.`, go: "orders", button: "Open the order" };
    }
    default:
      return { stage: "Closing", text: "Delivered. Finish the closing checklist, then close the job.", go: "orders", button: "Open the order" };
  }
}

/** One line under each part's name: where that part stands. */
export function summaries(job: Job): Record<Section, { line: string; warn?: boolean }> {
  const live = working(job);
  const tiles = live.flatMap((a) => chosenTiles(job, a.id));
  const considering = job.candidates.filter((c) => c.tags.some((t) => t.status === "considering")).length;
  const noTile = live.filter((a) => chosenTiles(job, a.id).length === 0);
  const noNumber = tiles.filter(({ t }) => t.quantity == null).length;
  const sqft = tiles.reduce((n, { c, t }) => n + (inSqft(unitOf(c)) ? t.quantity ?? 0 : 0), 0);
  const short = tiles.filter(({ t }) => t.avail_status === "short" || t.avail_status === "two_lots").length;
  const unchecked = tiles.filter(({ t }) => !GOOD.includes(t.avail_status ?? "")).length;
  const open = job.tasks.filter((t) => t.status === "open" || t.status === "blocked");
  const late = open.filter((t) => t.status === "blocked" || t.due_date < todayIso()).length;
  const orders = job.orders ?? [];
  const liveOrder = orders.find((o) => !["closed", "lost"].includes(o.stage));
  const people = job.roles.filter((r) => r.active);
  return {
    tiles: job.areas.length === 0
      ? { line: "No areas yet", warn: true }
      : { line: [`${tiles.length} chosen`, considering ? `${considering} being looked at` : null, noTile.length ? `${names(noTile)} still open` : null].filter(Boolean).join(" · "), warn: noTile.length > 0 },
    footage: tiles.length === 0 ? { line: "After tiles are chosen" } : noNumber ? { line: `${noNumber} tile${noNumber === 1 ? " needs" : "s need"} a number`, warn: true } : { line: `${num(sqft)} sf in all` },
    availability: tiles.length === 0 ? { line: "After tiles are chosen" } : short ? { line: `${short} short`, warn: true } : unchecked ? { line: `${unchecked} to check`, warn: true } : { line: "All set" },
    estimate: job.draft_estimate_id ? { line: "Started — not sent yet", warn: true } : orders.length ? { line: "Sent" } : { line: "Not started" },
    orders: liveOrder ? { line: liveOrder.stage.replace(/_/g, " ") } : { line: orders.length ? "All closed" : "None yet" },
    files: { line: "Plans, photos and notes" },
    steps: open.length === 0 ? { line: "Nothing open", warn: job.status === "active" } : { line: `${open.length} open${late ? ` · ${late} late or blocked` : ""}`, warn: late > 0 },
    people: { line: people.length ? names(people.map((r) => r.entity)) : "Nobody yet" },
    history: { line: "Everything that happened" },
  };
}

export const SECTION_LABEL: Record<Section, string> = {
  tiles: "Tiles", footage: "Footage", availability: "Availability", estimate: "Estimate", orders: "Orders",
  files: "Plans & files", steps: "Steps & visits", people: "People", history: "History",
};

/** The list of the job's parts, each with its one-line status. */
export function SectionList({ job, current, onPick }: { job: Job; current: Section | null; onPick: (s: Section) => void }) {
  const sum = summaries(job);
  const list: Section[] = ["tiles", "footage", "availability", "estimate", ...((job.orders ?? []).length ? (["orders"] as Section[]) : []), "steps", "files", "people", "history"];
  return (
    <nav className="job-parts" aria-label="Parts of this job">
      {list.map((k) => (
        <button key={k} className={`job-part ${current === k ? "job-part-on" : ""}`} aria-current={current === k} onClick={() => onPick(k)}>
          <span className="job-part-text">
            <strong>{SECTION_LABEL[k]}</strong>
            <span className={sum[k].warn ? "job-part-warn" : ""}>{sum[k].line}</span>
          </span>
          <span className="job-part-arrow" aria-hidden="true">›</span>
        </button>
      ))}
    </nav>
  );
}

/** The one card that says what to do: what's holding the job, and the very next step. */
export function NowCard({ job, onGo, reload }: { job: Job; onGo: (s: Section) => void; reload: () => void }) {
  const { userName } = useApp();
  const [open, setOpen] = useState<Task | null>(null);
  const now = whatNow(job, userName);
  const next = job.tasks.filter((t) => t.status === "open" || t.status === "blocked").sort((a, b) => a.due_date.localeCompare(b.due_date))[0];
  const late = next && (next.status === "blocked" || next.due_date < todayIso());
  return (
    <section className="now-card" aria-label="What's next">
      <span className="now-label">Now · {now.stage}</span>
      <p className="now-text">{now.text}</p>
      <button className="btn btn-primary" onClick={() => onGo(now.go)}>{now.button}</button>
      <div className={`now-step ${!next ? "now-step-none" : late ? "now-step-late" : ""}`}>
        {next ? (
          <>
            <span>
              <span className="now-step-label">Next step</span>
              <strong>{next.title}</strong>
              <span className="now-step-who">
                {userName(next.assignee_id)} · {next.status === "blocked" ? "blocked" : next.due_date < todayIso() ? `late, was due ${niceDate(next.due_date)}` : `due ${niceDate(next.due_date).toLowerCase()}`}
              </span>
            </span>
            <button className="btn btn-small now-done" onClick={() => setOpen({ ...next, job_name: job.name, job_rep_id: job.rep_id })}>
              <Icon name="check" size={16} /> Done
            </button>
          </>
        ) : (
          <span>
            <span className="now-step-label">Next step</span>
            <strong>Nobody has one.</strong> <span className="now-step-who">Add it under Steps, or the job goes quiet.</span>
          </span>
        )}
      </div>
      {open && <CompleteTask task={open} onClose={() => setOpen(null)} onDone={() => { setOpen(null); reload(); }} />}
    </section>
  );
}

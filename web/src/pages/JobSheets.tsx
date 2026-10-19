import { useState } from "react";
import { api } from "../api";
import { plusDays, useApp } from "../state";
import { blankStep, ErrorLine, Field, NextStepFields, Sheet, UserSelect, useAction } from "../ui";
import type { Job, NextStep, Visit } from "../types";

interface SheetProps {
  job: Job;
  onClose: () => void;
  onDone: () => void;
}

// ------------------------------------------------------- log an event
export function LogEvent({ job, visit, onClose, onDone }: SheetProps & { visit: Visit | null }) {
  const { me, toast } = useApp();
  const [kind, setKind] = useState<"contact" | "showroom_visit" | "site_visit">(visit ? (visit.kind === "site" ? "site_visit" : "showroom_visit") : "contact");
  const [channel, setChannel] = useState("phone");
  const [direction, setDirection] = useState("in");
  const [summary, setSummary] = useState("");
  const active = job.roles.filter((r) => r.active);
  const [people, setPeople] = useState<number[]>(job.default_contact_id ? [job.default_contact_id] : []);
  const [step, setStep] = useState<NextStep>(blankStep(me.id));
  const { busy, error, run } = useAction();

  return (
    <Sheet title={visit ? "How did the visit go?" : "Log what happened"} onClose={onClose}>
      {!visit && (
        <div className="chips" role="radiogroup" aria-label="What kind">
          {(
            [
              ["contact", "Call or message"],
              ["showroom_visit", "They came in"],
              ["site_visit", "We went to them"],
            ] as const
          ).map(([k, label]) => (
            <button key={k} role="radio" aria-checked={kind === k} className={`chip ${kind === k ? "chip-on" : ""}`} onClick={() => setKind(k)}>
              {label}
            </button>
          ))}
        </div>
      )}
      {kind === "contact" && (
        <div className="inline">
          <select value={channel} onChange={(e) => setChannel(e.target.value)} aria-label="How">
            <option value="phone">Phone</option>
            <option value="text">Text</option>
            <option value="whatsapp">WhatsApp</option>
            <option value="email">Email</option>
          </select>
          <select value={direction} onChange={(e) => setDirection(e.target.value)} aria-label="Direction">
            <option value="in">They reached us</option>
            <option value="out">We reached them</option>
          </select>
        </div>
      )}
      <Field label="Who was involved">
        <div className="chips">
          {active.map((r) => (
            <button key={r.id} type="button" className={`chip ${people.includes(r.entity.id) ? "chip-on" : ""}`} aria-pressed={people.includes(r.entity.id)} onClick={() => setPeople(people.includes(r.entity.id) ? people.filter((x) => x !== r.entity.id) : [...people, r.entity.id])}>
              {r.entity.name}
            </button>
          ))}
        </div>
      </Field>
      <Field label="What happened">
        <textarea autoFocus rows={3} value={summary} onChange={(e) => setSummary(e.target.value)} placeholder="Looked at kitchen and vestibule, nothing final, wants samples" />
      </Field>
      <NextStepFields value={step} onChange={setStep} />
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button
          className="btn btn-primary"
          disabled={busy || !summary.trim() || !step.title.trim()}
          onClick={() =>
            run(async () => {
              await api.post(`/jobs/${job.id}/events`, {
                kind,
                channel: kind === "contact" ? channel : "in_person",
                direction: kind === "contact" ? direction : null,
                summary,
                people,
                scheduled_visit_id: visit?.id ?? null,
                next_step: step,
              });
              toast("Logged");
              onDone();
            })
          }
        >
          Save
        </button>
      </div>
    </Sheet>
  );
}

// ---------------------------------------------------- book a visit
export function ScheduleVisit({ job, onClose, onDone }: SheetProps) {
  const { meta, users, toast } = useApp();
  const rep = users.find((u) => u.id === job.rep_id);
  const [kind, setKind] = useState<"showroom" | "site">("showroom");
  const [date, setDate] = useState(plusDays(1));
  const [time, setTime] = useState("11:00");
  const [repId, setRepId] = useState<number | null>(job.rep_id);
  const [showroom, setShowroom] = useState(rep?.home_showroom ?? meta.showrooms[0]);
  const [purpose, setPurpose] = useState("");
  const { busy, error, run } = useAction();
  return (
    <Sheet title="Book a visit" onClose={onClose}>
      <div className="chips">
        <button className={`chip ${kind === "showroom" ? "chip-on" : ""}`} onClick={() => setKind("showroom")}>They come in</button>
        <button className={`chip ${kind === "site" ? "chip-on" : ""}`} onClick={() => setKind("site")}>We go to the site</button>
      </div>
      <div className="inline">
        <Field label="Day"><input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <Field label="Time"><input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></Field>
      </div>
      <UserSelect label="Rep" value={repId} onChange={setRepId} />
      {kind === "showroom" && (
        <Field label="Showroom" hint="Defaults to the rep's showroom.">
          <select value={showroom} onChange={(e) => setShowroom(e.target.value)}>
            {meta.showrooms.map((s) => <option key={s}>{s}</option>)}
          </select>
        </Field>
      )}
      <Field label="What for">
        <input value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="Finish choosing the vestibule" />
      </Field>
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button
          className="btn btn-primary"
          disabled={busy || !date || !time}
          onClick={() =>
            run(async () => {
              const starts_at = new Date(`${date}T${time}:00`).toISOString();
              await api.post(`/jobs/${job.id}/visits`, { kind, starts_at, rep_id: repId, showroom: kind === "showroom" ? showroom : null, purpose: purpose || null });
              toast("Visit booked");
              onDone();
            })
          }
        >
          Book it
        </button>
      </div>
    </Sheet>
  );
}

export function ResolveVisit({ visit, job, onClose, onDone }: SheetProps & { visit: Visit }) {
  const { me } = useApp();
  const [mode, setMode] = useState<"no_show" | "cancelled" | "reschedule">("no_show");
  const [note, setNote] = useState("");
  const [date, setDate] = useState(plusDays(2));
  const [time, setTime] = useState("11:00");
  const [step, setStep] = useState<NextStep>(blankStep(me.id, "Call to rebook"));
  const { busy, error, run } = useAction();
  return (
    <Sheet title="The visit didn't happen" onClose={onClose}>
      <div className="chips">
        <button className={`chip ${mode === "no_show" ? "chip-on" : ""}`} onClick={() => setMode("no_show")}>They didn't come</button>
        <button className={`chip ${mode === "cancelled" ? "chip-on" : ""}`} onClick={() => setMode("cancelled")}>Called off</button>
        <button className={`chip ${mode === "reschedule" ? "chip-on" : ""}`} onClick={() => setMode("reschedule")}>Moved to another day</button>
      </div>
      {mode === "reschedule" ? (
        <div className="inline">
          <Field label="New day"><input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
          <Field label="Time"><input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></Field>
        </div>
      ) : (
        <>
          <Field label="What happened">
            <input autoFocus value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <NextStepFields value={step} onChange={setStep} />
        </>
      )}
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button
          className="btn btn-primary"
          disabled={busy || (mode !== "reschedule" && (!note.trim() || !step.title.trim()))}
          onClick={() =>
            run(async () => {
              if (mode === "reschedule") await api.post(`/visits/${visit.id}/reschedule`, { starts_at: new Date(`${date}T${time}:00`).toISOString() });
              else await api.post(`/visits/${visit.id}/resolve`, { status: mode, note, next_step: step });
              onDone();
            })
          }
        >
          Save
        </button>
      </div>
      <p className="muted small">Job: {job.name}</p>
    </Sheet>
  );
}

// ----------------------------------------------------------- add a step
export function AddTask({ job, onClose, onDone }: SheetProps) {
  const { me, toast } = useApp();
  const [step, setStep] = useState<NextStep>(blankStep(me.id));
  const { busy, error, run } = useAction();
  return (
    <Sheet title="Add a step" onClose={onClose}>
      <NextStepFields value={step} onChange={setStep} heading="The step" />
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || !step.title.trim()} onClick={() => run(async () => { await api.post(`/jobs/${job.id}/tasks`, step); toast("Step added"); onDone(); })}>
          Add step
        </button>
      </div>
    </Sheet>
  );
}

// ----------------------------------------------------------- edit job
export function EditJob({ job, onClose, onDone }: SheetProps) {
  const { meta, users } = useApp();
  const [form, setForm] = useState({
    name: job.name,
    address: job.address ?? "",
    class_code: job.class_code,
    project_type: job.project_type ?? "",
    lead_source: job.lead_source ?? "",
  });
  const [repId, setRepId] = useState<number | null>(job.rep_id);
  const { busy, error, run } = useAction();
  return (
    <Sheet title="Job details" onClose={onClose}>
      <Field label="Name" hint="Renaming keeps everything attached — it's logged on the story.">
        <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </Field>
      <Field label="Address"><input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} /></Field>
      <Field label="Department">
        <select value={form.class_code} onChange={(e) => setForm({ ...form, class_code: e.target.value })}>
          {meta.classes.map((c) => <option key={c}>{c}</option>)}
        </select>
      </Field>
      <Field label="Project type">
        <select value={form.project_type} onChange={(e) => setForm({ ...form, project_type: e.target.value })}>
          <option value="">Not set</option>
          {Object.entries(meta.project_types).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </Field>
      <Field label="How they found us">
        <select value={form.lead_source} onChange={(e) => setForm({ ...form, lead_source: e.target.value })}>
          <option value="">Not set</option>
          {Object.entries(meta.lead_sources).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </Field>
      <UserSelect label="Rep — one per job" value={repId} onChange={setRepId} />
      {repId !== job.rep_id && <p className="muted small">{users.find((u) => u.id === repId)?.name} will own this job and every open step on it.</p>}
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button
          className="btn btn-primary"
          disabled={busy || !form.name.trim()}
          onClick={() =>
            run(async () => {
              await api.patch(`/jobs/${job.id}`, { ...form, address: form.address || null, project_type: form.project_type || null, lead_source: form.lead_source || null });
              if (repId && repId !== job.rep_id) await api.post(`/jobs/${job.id}/rep`, { rep_id: repId });
              onDone();
            })
          }
        >
          Save
        </button>
      </div>
    </Sheet>
  );
}

// -------------------------------------------------- hold, lose, revive
export function HoldJob({ job, onClose, onDone }: SheetProps) {
  const [until, setUntil] = useState(plusDays(60));
  const [reason, setReason] = useState("");
  const { busy, error, run } = useAction();
  return (
    <Sheet title="Put the job on hold" onClose={onClose}>
      <p className="muted">Paused isn't stuck. On the date, the rep gets a check-in step.</p>
      <Field label="Come back on"><input type="date" value={until} onChange={(e) => setUntil(e.target.value)} /></Field>
      <Field label="Why"><input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Not starting till spring" /></Field>
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || !reason.trim()} onClick={() => run(async () => { await api.post(`/jobs/${job.id}/hold`, { until, reason }); onDone(); })}>
          Put on hold
        </button>
      </div>
    </Sheet>
  );
}

export function LoseJob({ job, onClose, onDone }: SheetProps) {
  const { meta } = useApp();
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const { busy, error, run } = useAction();
  return (
    <Sheet title="Close as lost" onClose={onClose}>
      <div className="chips">
        {Object.entries(meta.loss_reasons).map(([k, v]) => (
          <button key={k} className={`chip ${reason === k ? "chip-on" : ""}`} onClick={() => setReason(k)}>{v}</button>
        ))}
      </div>
      <Field label={reason === "other" ? "What happened (required)" : "Anything to add"}>
        <input value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <p className="muted small">Open steps are closed with the reason. The job can be brought back later.</p>
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button className="btn btn-danger" disabled={busy || !reason || (reason === "other" && !note.trim())} onClick={() => run(async () => { await api.post(`/jobs/${job.id}/lose`, { reason, note: note || null }); onDone(); })}>
          Close as lost
        </button>
      </div>
    </Sheet>
  );
}

export function ReviveJob({ job, onClose, onDone }: SheetProps) {
  const { me } = useApp();
  const [mode, setMode] = useState<"resume" | "fresh">("resume");
  const [step, setStep] = useState<NextStep>(blankStep(me.id, "Call to restart"));
  const { busy, error, run } = useAction();
  return (
    <Sheet title="Bring this job back" onClose={onClose}>
      <div className="outcomes">
        <button className={`outcome ${mode === "resume" ? "on" : ""}`} onClick={() => setMode("resume")}>
          <strong>Pick up where it was</strong>
          <span>Areas and choices stay as they were.</span>
        </button>
        <button className={`outcome ${mode === "fresh" ? "on" : ""}`} onClick={() => setMode("fresh")}>
          <strong>Start fresh</strong>
          <span>Open areas are dropped; selection starts over. History stays.</span>
        </button>
      </div>
      <NextStepFields value={step} onChange={setStep} />
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || !step.title.trim()} onClick={() => run(async () => { await api.post(`/jobs/${job.id}/revive`, { mode, next_step: step }); onDone(); })}>
          Bring it back
        </button>
      </div>
    </Sheet>
  );
}

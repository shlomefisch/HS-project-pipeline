import { useState } from "react";
import { api } from "../api";
import { useApp, useLoad } from "../state";
import { Empty, ErrorLine, Field, Loading, Sheet, useAction } from "../ui";
import type { StepTemplate, TemplateList } from "../types";

const SEVERITY: Record<string, string> = { silent: "Silent", notify: "Notify (a buzz)", interrupt: "Interrupt (stays on screen)" };
const HINT: Record<string, string> = {
  job_created: "Added when a new job is opened, after its first next step.",
  takeoff_done: "Added when the takeoff is finished.",
  estimate_started: "Added when an estimate is put together.",
  area_decided: "Added once per area, when the area is marked decided. The area's name goes on the end.",
};

/** The usual steps, written once, added to every job by themselves. */
export function Templates() {
  const { data, error, reload } = useLoad(() => api.get<TemplateList>("/templates"), []);
  const { userName } = useApp();
  const [editing, setEditing] = useState<Partial<StepTemplate> | null>(null);
  if (!data) return <main className="page"><Loading error={error} /></main>;
  const who = (s: StepTemplate) => (s.assignee_kind === "user" ? userName(s.assignee_user_id) : data.assignee_kinds[s.assignee_kind]);
  return (
    <main className="page">
      <header className="page-head">
        <div>
          <a href="#/team" className="back">Team</a>
          <h1>Step templates</h1>
        </div>
      </header>
      <p className="muted small">The steps a job gets by itself at each moment. Change them any time — jobs already open keep what they have.</p>
      {Object.entries(data.triggers).map(([trigger, label]) => {
        const steps = data.steps.filter((s) => s.trigger === trigger);
        return (
          <section key={trigger} className="section">
            <div className="section-head">
              <h2>{label}</h2>
              <button className="btn btn-small" onClick={() => setEditing({ trigger: trigger as StepTemplate["trigger"], playbook: "all", assignee_kind: "rep", due_days: 1, severity: "silent", sort_order: steps.length })}>
                Add a step
              </button>
            </div>
            <p className="muted small">{HINT[trigger]}</p>
            {steps.length === 0 ? (
              <Empty>No steps yet.</Empty>
            ) : (
              <ul className="list">
                {steps.map((s) => (
                  <li key={s.id}>
                    <button className="row-btn" onClick={() => setEditing(s)}>
                      <strong>{s.title}</strong>
                      <span className="muted small">
                        {who(s)} · due {s.due_days === 0 ? "the same day" : `in ${s.due_days} day${s.due_days === 1 ? "" : "s"}`}
                        {s.playbook !== "all" ? ` · ${data.playbooks[s.playbook]} only` : ""}
                        {s.severity !== "silent" ? ` · ${s.severity}` : ""}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}
      {editing && <StepSheet step={editing} list={data} onClose={() => setEditing(null)} onDone={() => { setEditing(null); reload(); }} />}
    </main>
  );
}

function StepSheet({ step, list, onClose, onDone }: { step: Partial<StepTemplate>; list: TemplateList; onClose: () => void; onDone: () => void }) {
  const { users } = useApp();
  const [form, setForm] = useState({
    trigger: step.trigger!,
    playbook: step.playbook ?? "all",
    title: step.title ?? "",
    notes: step.notes ?? "",
    assignee_kind: step.assignee_kind ?? "rep",
    assignee_user_id: step.assignee_user_id ?? null,
    due_days: step.due_days ?? 1,
    severity: step.severity ?? "silent",
    sort_order: step.sort_order ?? 0,
  });
  const { busy, error, run } = useAction();
  const people = users.filter((u) => u.active && u.role !== "pending" && u.role !== "viewer");
  const save = () =>
    run(async () => {
      const body = { ...form, notes: form.notes || null };
      if (step.id) await api.patch(`/templates/${step.id}`, body);
      else await api.post("/templates", body);
      onDone();
    });
  return (
    <Sheet title={step.id ? "Edit step" : `New step — ${list.triggers[form.trigger]}`} onClose={onClose}>
      <Field label="The step"><input autoFocus value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Send the welcome text" /></Field>
      <Field label="Who does it">
        <select value={form.assignee_kind} onChange={(e) => setForm({ ...form, assignee_kind: e.target.value as StepTemplate["assignee_kind"] })}>
          {Object.entries(list.assignee_kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </Field>
      {form.assignee_kind === "user" && (
        <Field label="Person" hint="If they leave or are away, it goes to their cover or the job's rep.">
          <select value={form.assignee_user_id ?? ""} onChange={(e) => setForm({ ...form, assignee_user_id: e.target.value ? Number(e.target.value) : null })}>
            <option value="">Pick someone</option>
            {people.map((u) => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}
          </select>
        </Field>
      )}
      <div className="two-col">
        <Field label="Due in (days)" hint="0 = the same day">
          <input inputMode="numeric" value={String(form.due_days)} onChange={(e) => setForm({ ...form, due_days: Number(e.target.value.replace(/\D/g, "") || 0) })} />
        </Field>
        <Field label="How loud">
          <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value as StepTemplate["severity"] })}>
            {Object.entries(SEVERITY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
      </div>
      <Field label="Which jobs">
        <select value={form.playbook} onChange={(e) => setForm({ ...form, playbook: e.target.value as StepTemplate["playbook"] })}>
          {Object.entries(list.playbooks).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </Field>
      <Field label="Note for whoever does it" hint="Optional."><input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
      <Field label="Order" hint="Lower numbers come first."><input inputMode="numeric" value={String(form.sort_order)} onChange={(e) => setForm({ ...form, sort_order: Number(e.target.value.replace(/\D/g, "") || 0) })} /></Field>
      <ErrorLine error={error} />
      <div className="actions actions-wrap">
        {step.id && <button className="btn btn-quiet" disabled={busy} onClick={() => run(async () => { await api.patch(`/templates/${step.id}`, { active: false }); onDone(); })}>Remove</button>}
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || !form.title.trim() || (form.assignee_kind === "user" && !form.assignee_user_id)} onClick={save}>Save</button>
      </div>
    </Sheet>
  );
}

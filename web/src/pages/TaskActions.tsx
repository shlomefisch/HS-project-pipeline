import { useState } from "react";
import { celebrateHere } from "../celebrate";
import { api } from "../api";
import { niceDate, useApp } from "../state";
import { blankStep, ErrorLine, Field, NextStepFields, Sheet, useAction } from "../ui";
import type { NextStep, Task } from "../types";

type Outcome = "done" | "blocked" | "bad_answer" | "skipped";

const OUTCOMES: { key: Outcome; label: string; help: string }[] = [
  { key: "done", label: "Done", help: "It's finished." },
  { key: "blocked", label: "Blocked", help: "Waiting on someone. Stays open." },
  { key: "bad_answer", label: "Bad answer", help: "The news isn't good. The rep hears about it." },
  { key: "skipped", label: "Not needed", help: "Skip it, with a reason." },
];

/** Closing a task. The next step is asked for here, so the job never goes quiet. */
export function CompleteTask({ task, onClose, onDone }: { task: Task; onClose: () => void; onDone: () => void }) {
  const { me, userName, toast } = useApp();
  const repId = task.job_rep_id ?? me.id;
  const [outcome, setOutcome] = useState<Outcome>("done");
  const [note, setNote] = useState("");
  const [withStep, setWithStep] = useState(true);
  const [step, setStep] = useState<NextStep>(blankStep(me.id));
  const { busy, error, run } = useAction();

  const pick = (o: Outcome) => {
    setOutcome(o);
    if (o === "bad_answer") {
      setWithStep(true);
      setStep((s) => ({ ...s, assignee_id: repId, title: s.title || "Call the customer about this" }));
    }
    if (o === "blocked") setWithStep(false);
  };

  const needsNote = outcome !== "done";
  const stepRequired = outcome === "bad_answer";

  return (
    <Sheet title={task.title} onClose={onClose}>
      <p className="muted">
        {task.job_name ? `${task.job_name} — ` : ""}
        {userName(task.assignee_id)}, due {niceDate(task.due_date)}
      </p>
      <div className="outcomes" role="radiogroup" aria-label="What happened">
        {OUTCOMES.map((o) => (
          <button key={o.key} role="radio" aria-checked={outcome === o.key} className={`outcome ${outcome === o.key ? "on" : ""} outcome-${o.key}`} onClick={() => pick(o.key)}>
            <strong>{o.label}</strong>
            <span>{o.help}</span>
          </button>
        ))}
      </div>
      {needsNote && (
        <Field label={outcome === "blocked" ? "Waiting on what?" : outcome === "bad_answer" ? "What's the bad news?" : "Why isn't it needed?"}>
          <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      )}
      {!stepRequired && (
        <label className="check">
          <input type="checkbox" checked={withStep} onChange={(e) => setWithStep(e.target.checked)} /> Add the next step
        </label>
      )}
      {withStep && <NextStepFields value={step} onChange={setStep} />}
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn btn-primary"
          disabled={busy || (needsNote && !note.trim()) || (withStep && !step.title.trim())}
          onClick={() =>
            run(async () => {
              await api.post(`/tasks/${task.id}/complete`, { outcome, note: note || null, next_step: withStep ? step : null });
              if (outcome === "done") {
                celebrateHere();
                toast(task.job_name ? `Done — ${task.job_name} moves on` : "Done");
              } else toast(outcome === "blocked" ? "Marked blocked" : "Saved");
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

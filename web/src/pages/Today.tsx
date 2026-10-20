import { useState } from "react";
import { api } from "../api";
import { go, niceDate, niceTime, useApp, useLoad } from "../state";
import { Empty, Loading } from "../ui";
import type { Job, Task, User, Visit } from "../types";
import { ChangePasswordSheet } from "./Login";
import { NotificationsBox } from "../notify";
import { Overview } from "./Overview";
import { waiting } from "../offline";
import { CompleteTask } from "./TaskActions";

interface RepView {
  today: string;
  done_today?: number;
  went_wrong: Task[];
  visits_today: Visit[];
  due: Task[];
  stuck: { jobs: Job[]; missed_visits: Visit[] };
  counts: { went_wrong: number; visits_today: number; due: number; stuck: number };
}

interface OfficeView {
  tasks: Task[];
  done_today?: number;
  counts: { tasks: number; overdue: number };
}

export function Today({ onSignOut, onMe }: { onSignOut: () => void; onMe: (u: User) => void }) {
  const { me, toast } = useApp();
  const [pwOpen, setPwOpen] = useState(false);
  const [confirmOut, setConfirmOut] = useState(false);
  const boss = me.is_admin || me.role === "management";
  const [view, setView] = useState<"rep" | "office" | "overview">(me.role === "rep" ? "rep" : boss ? "overview" : "office");
  return (
    <main className="page">
      <header className="page-head today-head">
        <div>
          <h1 className="greeting">{greeting()}, {firstName(me.name || me.email)}</h1>
          <p className="today-date">{new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</p>
        </div>
        <div className="seg" role="tablist">
          <button role="tab" aria-selected={view === "rep"} className={view === "rep" ? "on" : ""} onClick={() => setView("rep")}>
            My jobs
          </button>
          <button role="tab" aria-selected={view === "office"} className={view === "office" ? "on" : ""} onClick={() => setView("office")}>
            My tasks
          </button>
          {boss && (
            <button role="tab" aria-selected={view === "overview"} className={view === "overview" ? "on" : ""} onClick={() => setView("overview")}>
              Everyone
            </button>
          )}
        </div>
      </header>
      {view === "rep" ? <RepDashboard /> : view === "office" ? <OfficeDashboard /> : <Overview />}
      <NotificationsBox />
      <footer className="page-foot">
        <span className="muted small">{me.email}</span>
        <button className="btn btn-small btn-quiet" onClick={() => setPwOpen(true)}>
          {me.has_password === false ? "Set password" : "Change password"}
        </button>
        <button
          className="btn btn-small btn-quiet"
          onClick={() => {
            const n = waiting().length;
            if (n && !confirmOut) return setConfirmOut(true);
            onSignOut();
          }}
        >
          {confirmOut ? `Sign out — ${waiting().length} unsent save(s) will be lost` : "Sign out"}
        </button>
      </footer>
      {pwOpen && (
        <ChangePasswordSheet
          me={me}
          onClose={() => setPwOpen(false)}
          onDone={(u) => {
            setPwOpen(false);
            onMe(u);
            toast("Password saved.");
          }}
        />
      )}
    </main>
  );
}

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

function firstName(name: string): string {
  return name.replace(/@.*/, "").split(/[\s.]+/)[0] || name;
}

/** The small win: what you finished today, laid as tiles. */
function DoneToday({ n }: { n: number }) {
  if (!n) return <p className="done-today done-none">Nothing finished yet today — the first one is the best one.</p>;
  return (
    <p className="done-today">
      <span className="done-tiles" aria-hidden="true">
        {Array.from({ length: Math.min(n, 12) }, (_, i) => <span key={i} />)}
      </span>
      <span>You've finished <strong>{n}</strong> step{n === 1 ? "" : "s"} today.</span>
    </p>
  );
}

function Tile({ n, label, tone, onClick }: { n: number; label: string; tone: string; onClick: () => void }) {
  return (
    <button role="listitem" onClick={onClick} className={`tile ${tone ? `tile-${tone}` : ""}`}>
      <span className="tile-n">{n}</span>
      <span className="tile-label">{label}</span>
    </button>
  );
}

function jump(id: string) {
  document.getElementById(`sec-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function RepDashboard() {
  const { userName } = useApp();
  const { data, error, reload } = useLoad(() => api.get<RepView>("/dashboard/rep"), []);
  const [open, setOpen] = useState<Task | null>(null);
  if (!data) return <Loading error={error} />;
  const c = data.counts;
  return (
    <>
      <DoneToday n={data.done_today ?? 0} />
      <div className="tiles" role="list">
        <Tile n={c.went_wrong} label="went wrong" tone={c.went_wrong ? "alert" : ""} onClick={() => jump("wrong")} />
        <Tile n={c.visits_today} label="visits today" tone="" onClick={() => jump("visits")} />
        <Tile n={c.due} label="due now" tone={data.due.some((t) => t.overdue) ? "warn" : ""} onClick={() => jump("due")} />
        <Tile n={c.stuck} label="stuck" tone={c.stuck ? "alert" : ""} onClick={() => jump("stuck")} />
      </div>

      <section id="sec-wrong" className="section">
        <h2>Went wrong</h2>
        {data.went_wrong.length === 0 ? (
          <Empty>Nothing waiting on you.</Empty>
        ) : (
          <ul className="list">
            {data.went_wrong.map((t) => (
              <li key={t.id} className="task-row task-alert">
                <a href={`#/jobs/${t.job_id}`} className="row-link">
                  <strong>{t.title}</strong>{t.covering_for_id ? <span className="covering"> covering for {userName(t.covering_for_id)}</span> : null}
                  <span className="muted">
                    {t.job_name} — {t.status === "blocked" ? "Blocked" : "Bad answer"}: {t.outcome_note}
                  </span>
                </a>
                {t.needs_rep_attention && (
                  <button
                    className="btn btn-small"
                    onClick={async () => {
                      await api.post(`/tasks/${t.id}/acknowledge`);
                      reload();
                    }}
                  >
                    Seen
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section id="sec-visits" className="section">
        <h2>Today's visits</h2>
        {data.visits_today.length === 0 ? (
          <Empty>No one booked today.</Empty>
        ) : (
          <ul className="list">
            {data.visits_today.map((v) => (
              <li key={v.id}>
                <a href={`#/jobs/${v.job_id}`} className="row-link">
                  <strong>
                    {niceTime(v.starts_at)} — {v.job_name}
                  </strong>
                  <span className="muted">
                    {v.kind === "site" ? "Site visit" : `Showroom, ${v.showroom ?? ""}`}
                    {v.purpose ? ` — ${v.purpose}` : ""}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section id="sec-due" className="section">
        <h2>Due now</h2>
        {data.due.length === 0 ? (
          <Empty>Nothing due. Check your jobs for what's next.</Empty>
        ) : (
          <ul className="list">
            {data.due.map((t) => (
              <li key={t.id} className={`task-row ${t.overdue ? "task-overdue" : ""}`}>
                <button className="row-btn" onClick={() => setOpen(t)}>
                  <strong>{t.title}</strong>{t.covering_for_id ? <span className="covering"> covering for {userName(t.covering_for_id)}</span> : null}
                  <span className="muted">
                    {t.job_name} — {t.overdue ? `overdue since ${niceDate(t.due_date)}` : "due today"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section id="sec-stuck" className="section">
        <h2>Stuck</h2>
        {c.stuck === 0 ? (
          <Empty>Every job has a next step.</Empty>
        ) : (
          <ul className="list">
            {data.stuck.jobs.map((j) => (
              <li key={`j${j.id}`} className="task-row task-alert">
                <a href={`#/jobs/${j.id}`} className="row-link">
                  <strong>{j.name}</strong>
                  <span className="muted">No next step — nobody is doing anything on this job.</span>
                </a>
              </li>
            ))}
            {data.stuck.missed_visits.map((v) => (
              <li key={`v${v.id}`} className="task-row task-alert">
                <a href={`#/jobs/${v.job_id}`} className="row-link">
                  <strong>{v.job_name}</strong>
                  <span className="muted">Visit on {niceDate(v.starts_at)} — nothing logged. What happened?</span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </section>

      {open && (
        <CompleteTask
          task={open}
          onClose={() => setOpen(null)}
          onDone={() => {
            setOpen(null);
            reload();
          }}
        />
      )}
    </>
  );
}

function OfficeDashboard() {
  const { userName } = useApp();
  const { data, error, reload } = useLoad(() => api.get<OfficeView>("/dashboard/office"), []);
  const [open, setOpen] = useState<Task | null>(null);
  if (!data) return <Loading error={error} />;
  return (
    <section className="section">
      <DoneToday n={data.done_today ?? 0} />
      <p className="muted">
        {data.counts.tasks} open{data.counts.overdue ? `, ${data.counts.overdue} overdue` : ""}
      </p>
      {data.tasks.length === 0 ? (
        <Empty>Your list is clear. Nice work.</Empty>
      ) : (
        <ul className="list">
          {data.tasks.map((t) => (
            <li key={t.id} className={`task-row ${t.overdue ? "task-overdue" : ""} ${t.status === "blocked" ? "task-alert" : ""}`}>
              <button className="row-btn" onClick={() => setOpen(t)}>
                <strong>{t.title}</strong>{t.covering_for_id ? <span className="covering"> covering for {userName(t.covering_for_id)}</span> : null}
                <span className="muted">
                  {t.job_name} — {t.status === "blocked" ? `blocked: ${t.outcome_note}` : niceDate(t.due_date)}
                </span>
              </button>
              <button className="icon-btn" aria-label="Open job" onClick={() => go(`jobs/${t.job_id}`)}>
                ›
              </button>
            </li>
          ))}
        </ul>
      )}
      {open && (
        <CompleteTask
          task={open}
          onClose={() => setOpen(null)}
          onDone={() => {
            setOpen(null);
            reload();
          }}
        />
      )}
    </section>
  );
}

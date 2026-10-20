import { useState } from "react";
import { api } from "../api";
import { go, niceDate, niceTime, plusDays, useApp, useLoad } from "../state";
import { Empty, ErrorLine, Field, Loading, useAction } from "../ui";
import type { AwayOrGone as Screen, HeldItem } from "../types";

type Kind = "jobs" | "tasks" | "visits";
const KIND_LABEL: Record<Kind, string> = { jobs: "Jobs they're the rep on", tasks: "Open tasks", visits: "Upcoming visits" };

/** One admin screen, two modes: away (a cover holds everything) or gone (hand it all over, then deactivate). */
export function AwayOrGone({ id }: { id: number }) {
  const { users, userName, refreshUsers, toast } = useApp();
  const { data, error, reload } = useLoad(() => api.get<Screen>(`/users/${id}/away-or-gone`), [id]);
  const [mode, setMode] = useState<"away" | "gone">("away");
  const [cover, setCover] = useState<number | "">("");
  const [from, setFrom] = useState(plusDays(0));
  const [until, setUntil] = useState(plusDays(7));
  const [note, setNote] = useState("");
  const [to, setTo] = useState<number | "">("");
  const { busy, error: actError, run } = useAction();
  if (!data) return <main className="page"><Loading error={error} /></main>;

  const u = data.user;
  const others = users.filter((x) => x.id !== u.id && x.active && x.role !== "pending" && x.role !== "viewer");
  const total = data.counts.jobs + data.counts.tasks + data.counts.visits + data.counts.takeoff;
  const cur = data.current;
  const handOver = (what: Kind | "takeoff", ids?: number[]) =>
    run(async () => {
      await api.post(`/users/${u.id}/hand-over`, { to_user_id: to, what, ids: ids ?? null });
      reload();
    });

  return (
    <main className="page">
      <header className="page-head">
        <div>
          <a href="#/team" className="back">Team</a>
          <h1>{u.name || u.email}</h1>
          <p className="muted">{u.active ? (cur?.status === "active" ? `Away until ${niceDate(cur.ends_on)} — ${userName(cur.cover_id)} is covering` : cur?.status === "planned" ? `Away from ${niceDate(cur.starts_on)}` : "Not away") : "Deactivated"}</p>
          {data.covering_for.length > 0 && <p className="muted small">Covering for {data.covering_for.map(userName).join(", ")}</p>}
        </div>
      </header>

      <section className="section">
        <h2>What they hold</h2>
        <div className="hold-counts">
          <span><strong>{data.counts.jobs}</strong> jobs</span>
          <span><strong>{data.counts.tasks}</strong> open tasks</span>
          <span><strong>{data.counts.visits}</strong> upcoming visits</span>
          <span><strong>{data.holds.takeoff ? "Yes" : "No"}</strong> takeoff slot</span>
        </div>
        {cur?.status === "active" && total === 0 && <p className="muted small">All of it is with {userName(cur.cover_id)} while they're away, marked "covering for".</p>}
      </section>

      {u.active && (
        <nav className="seg" role="tablist">
          <button role="tab" aria-selected={mode === "away"} className={mode === "away" ? "on" : ""} onClick={() => setMode("away")}>Away</button>
          <button role="tab" aria-selected={mode === "gone"} className={mode === "gone" ? "on" : ""} onClick={() => setMode("gone")}>Gone</button>
        </nav>
      )}

      {u.active && mode === "away" && (
        <section className="section">
          {cur ? (
            <>
              <p>
                {cur.status === "active" ? "Away now" : "Away planned"}: {niceDate(cur.starts_on)} → back {niceDate(cur.ends_on)}. Cover: <strong>{userName(cur.cover_id)}</strong>
                {cur.note && <> — {cur.note}</>}
              </p>
              <p className="muted small">When they're back, open work goes back to them by itself. What the cover finished stays credited to the cover.</p>
              <button className="btn btn-primary" disabled={busy} onClick={() => run(async () => { await api.post(`/users/${u.id}/back`); toast(cur.status === "active" ? "Welcome back — open work is home." : "Away cancelled."); reload(); })}>
                {cur.status === "active" ? "They're back now" : "Cancel this away"}
              </button>
            </>
          ) : (
            <>
              <p className="muted small">Everything they hold — and anything new aimed at them — goes to the cover, marked "covering for".</p>
              <Field label="Cover">
                <select value={cover} onChange={(e) => setCover(e.target.value ? Number(e.target.value) : "")}>
                  <option value="">Pick someone</option>
                  {others.map((x) => <option key={x.id} value={x.id}>{x.name || x.email}</option>)}
                </select>
              </Field>
              <div className="two-col">
                <Field label="Away from"><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
                <Field label="Back on"><input type="date" value={until} onChange={(e) => setUntil(e.target.value)} /></Field>
              </div>
              <Field label="Note" hint="Optional."><input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
              <button
                className="btn btn-primary"
                disabled={busy || !cover}
                onClick={() => run(async () => { await api.post(`/users/${u.id}/away`, { cover_id: cover, starts_on: from, ends_on: until, note: note || null }); reload(); })}
              >
                Set away
              </button>
            </>
          )}
        </section>
      )}

      {u.active && mode === "gone" && (
        <section className="section">
          <p className="muted small">Hand everything over — all at once or one by one. The account can be deactivated once every count is zero. History keeps their name.</p>
          <Field label="Give to">
            <select value={to} onChange={(e) => setTo(e.target.value ? Number(e.target.value) : "")}>
              <option value="">Pick someone</option>
              {others.map((x) => <option key={x.id} value={x.id}>{x.name || x.email}</option>)}
            </select>
          </Field>
          {(["jobs", "tasks", "visits"] as Kind[]).map((k) => (
            <div key={k} className="hold-group">
              <div className="section-head">
                <h3>{KIND_LABEL[k]} ({data.counts[k]})</h3>
                {data.counts[k] > 0 && <button className="btn btn-small" disabled={busy || !to} onClick={() => handOver(k)}>Give all</button>}
              </div>
              {data.holds[k].length === 0 ? (
                <Empty>None.</Empty>
              ) : (
                <ul className="list">
                  {data.holds[k].map((x: HeldItem) => (
                    <li key={x.id} className="hold-row">
                      <button className="link-btn" onClick={() => go(`/jobs/${k === "jobs" ? x.id : x.job_id}`)}>
                        {x.label}
                        {x.job_name && <span className="muted small"> — {x.job_name}</span>}
                        {x.due_date && <span className="muted small"> · due {niceDate(x.due_date)}</span>}
                        {x.starts_at && <span className="muted small"> · {niceDate(x.starts_at)} {niceTime(x.starts_at)}</span>}
                      </button>
                      <button className="btn btn-quiet btn-small" disabled={busy || !to} onClick={() => handOver(k, [x.id])}>Give</button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
          <div className="hold-group">
            <div className="section-head">
              <h3>Takeoff slot</h3>
              {data.holds.takeoff && <button className="btn btn-small" disabled={busy || !to} onClick={() => handOver("takeoff")}>Give</button>}
            </div>
            <Empty>{data.holds.takeoff ? "New takeoffs go to them by default." : "Not theirs."}</Empty>
          </div>
          <ErrorLine error={actError} />
          <button
            className="btn btn-primary"
            disabled={busy || total > 0}
            title={total > 0 ? "Hand everything over first" : undefined}
            onClick={() => run(async () => { await api.patch(`/users/${u.id}`, { active: false }); refreshUsers(); toast(`${u.name} is deactivated. History keeps the name.`); go("/team"); })}
          >
            {total > 0 ? `Deactivate — ${total} thing${total === 1 ? "" : "s"} still to hand over` : "Deactivate"}
          </button>
        </section>
      )}
      {mode === "away" && <ErrorLine error={actError} />}

      {data.history.length > 0 && (
        <section className="section">
          <h2>Past aways</h2>
          <ul className="list">
            {data.history.map((a) => (
              <li key={a.id} className="muted small">{niceDate(a.starts_on)} → {niceDate(a.ends_on)} — {userName(a.cover_id)} covered{a.status === "cancelled" ? " (cancelled)" : ""}{a.note ? ` — ${a.note}` : ""}</li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}

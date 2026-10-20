import { api } from "../api";
import { go, niceDate, useApp, useLoad } from "../state";
import { Empty, Loading } from "../ui";

interface Person { user_id: number; name: string; role: string; open: number; overdue: number; jobs: number; stuck: number; went_wrong: number }
interface Mgmt {
  today: string;
  quiet_days: number;
  loss_window_days: number;
  by_class: Record<string, { active: number; on_hold: number; lost: number; closed: number }>;
  people: Person[];
  quiet: { id: number; name: string; rep_id: number; class_code: string; last_at: string }[];
  losses: Record<string, number>;
  away: { user_id: number; cover_id: number; ends_on: string }[];
  totals: { active: number; overdue: number; went_wrong: number; quiet: number };
}

/** Management: everyone at once — where jobs stand, who is behind, what went quiet, why jobs are lost. */
export function Overview() {
  const { meta, userName } = useApp();
  const { data, error } = useLoad(() => api.get<Mgmt>("/dashboard/management"), []);
  if (!data) return <Loading error={error} />;
  const t = data.totals;
  const lossTotal = Object.values(data.losses).reduce((a, b) => a + b, 0);
  return (
    <div className="overview">
      <div className="tiles">
        <div className="tile"><strong>{t.active}</strong><span>active jobs</span></div>
        <div className={`tile ${t.overdue ? "tile-warn" : ""}`}><strong>{t.overdue}</strong><span>overdue steps</span></div>
        <div className={`tile ${t.went_wrong ? "tile-bad" : ""}`}><strong>{t.went_wrong}</strong><span>went wrong</span></div>
        <div className={`tile ${t.quiet ? "tile-warn" : ""}`}><strong>{t.quiet}</strong><span>gone quiet</span></div>
      </div>

      <section className="section">
        <h2>People</h2>
        <p className="muted small">Most behind first.</p>
        <table className="ov-table">
          <thead><tr><th>Who</th><th className="num">Open</th><th className="num">Late</th><th className="num">Jobs</th><th className="num">Stuck</th><th className="num">Wrong</th></tr></thead>
          <tbody>
            {data.people.map((p) => (
              <tr key={p.user_id}>
                <td>{p.name}</td>
                <td className="num">{p.open}</td>
                <td className={`num ${p.overdue ? "bad" : ""}`}>{p.overdue}</td>
                <td className="num">{p.jobs}</td>
                <td className={`num ${p.stuck ? "bad" : ""}`}>{p.stuck}</td>
                <td className={`num ${p.went_wrong ? "bad" : ""}`}>{p.went_wrong}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="section">
        <h2>Gone quiet</h2>
        <p className="muted small">Active jobs with nothing logged or changed in {data.quiet_days} days.</p>
        {data.quiet.length === 0 ? (
          <Empty>None — every active job moved in the last {data.quiet_days} days.</Empty>
        ) : (
          <ul className="list">
            {data.quiet.map((j) => (
              <li key={j.id}>
                <button className="row-btn" onClick={() => go(`/jobs/${j.id}`)}>
                  <strong>{j.name}</strong>
                  <span className="muted small">{userName(j.rep_id)} · {j.class_code} · last touched {niceDate(j.last_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="section">
        <h2>By department</h2>
        <table className="ov-table">
          <thead><tr><th>Department</th><th className="num">Active</th><th className="num">On hold</th><th className="num">Lost</th><th className="num">Closed</th></tr></thead>
          <tbody>
            {meta.classes.map((c) => {
              const r = data.by_class[c] ?? { active: 0, on_hold: 0, lost: 0, closed: 0 };
              return (
                <tr key={c}><td>{c}</td><td className="num">{r.active}</td><td className="num">{r.on_hold}</td><td className="num">{r.lost}</td><td className="num">{r.closed}</td></tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <section className="section">
        <h2>Why jobs were lost</h2>
        <p className="muted small">Last {data.loss_window_days} days.</p>
        {lossTotal === 0 ? (
          <Empty>No jobs lost.</Empty>
        ) : (
          <ul className="bars">
            {Object.entries(data.losses).sort((a, b) => b[1] - a[1]).map(([reason, n]) => (
              <li key={reason}>
                <span className="bar-label">{meta.loss_reasons[reason] ?? reason}</span>
                <span className="bar"><span style={{ width: `${(n / lossTotal) * 100}%` }} /></span>
                <span className="bar-n">{n}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {data.away.length > 0 && (
        <section className="section">
          <h2>Away now</h2>
          <ul className="list">
            {data.away.map((a) => (
              <li key={a.user_id} className="small">{userName(a.user_id)} — back {niceDate(a.ends_on)}, {userName(a.cover_id)} covering</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

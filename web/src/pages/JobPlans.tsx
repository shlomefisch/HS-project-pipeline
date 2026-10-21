import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { niceDate, niceTime, plusDays, useApp, useLoad } from "../state";
import { Empty, ErrorLine, Field, Sheet, UserSelect, useAction } from "../ui";
import type { AppSettings, Area, Candidate, Job, JobFile, Tag } from "../types";
import { chosenTiles, num, parseNum, unitOf, unitShort } from "../footage";

const KIND_LABEL: Record<JobFile["kind"], string> = { plan: "Plans", photo: "Photos", note: "Notes", other: "Other" };

const sf = num;
const size = (b: number | null) => (b == null ? "" : b > 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);

/** The footage: typed on each chosen tile. The takeoff sits here too, since that's what it fills in. */
export function Footage({ job, reload }: { job: Job; reload: () => void }) {
  const files = useLoad(() => api.get<JobFile[]>(`/jobs/${job.id}/files`), [job.id]);
  const [sheet, setSheet] = useState<null | "takeoff" | { area: Area }>(null);
  const live = job.areas.filter((a) => a.status === "open" || a.status === "decided");
  const plans = (files.data ?? []).filter((f) => f.kind === "plan" && f.status === "ready" && (f.url || f.source === "link"));
  const done = () => {
    setSheet(null);
    reload();
  };

  return (
    <div className="plans">
      <section className="section">
        <p className="muted small">The number on each tile is the footage, waste included. The area size only fills in a tile that has no number yet.</p>
        {live.length === 0 ? (
          <Empty>Add the areas and tiles first.</Empty>
        ) : (
          <div className="footage-areas">
            {live.map((a) => {
              const here = chosenTiles(job, a.id);
              return (
                <div key={a.id} className="footage-area">
                  <div className="footage-area-head">
                    <strong>{a.name}</strong>
                    <button className="btn btn-quiet btn-small" onClick={() => setSheet({ area: a })}>
                      {a.footage == null ? "Set area size" : `Area size ${num(a.footage)} sf`}
                    </button>
                  </div>
                  {here.length === 0 ? (
                    <p className="muted small footage-none">No tile chosen yet.</p>
                  ) : (
                    <ul className="list">
                      {here.map(({ c, t }) => <TileNumber key={t.id} cand={c} tag={t} onSaved={reload} />)}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="section">
        <h2>Takeoff</h2>
        {job.open_takeoff_id ? (
          <TakeoffStatus job={job} />
        ) : (
          <>
            <p className="muted small">
              {plans.length ? "Plans are on the job. Send them for a takeoff and the numbers come back here." : "Put the plans on the job first (Plans & files) — then a takeoff can be requested."}
            </p>
            {job.status === "active" && (
              <button className="btn" disabled={!plans.length} onClick={() => setSheet("takeoff")}>
                Request a takeoff
              </button>
            )}
          </>
        )}
      </section>

      {sheet === "takeoff" && <TakeoffSheet job={job} onClose={() => setSheet(null)} onDone={done} />}
      {sheet && typeof sheet === "object" && <FootageSheet job={job} area={sheet.area} onClose={() => setSheet(null)} onDone={done} />}
    </div>
  );
}

/** Plans, photos and notes on the job. Links are pulled in on the server. */
export function Files({ job }: { job: Job }) {
  const files = useLoad(() => api.get<JobFile[]>(`/jobs/${job.id}/files`), [job.id]);
  const [sheet, setSheet] = useState<null | "upload" | "link">(null);
  const fetching = !!files.data?.some((f) => f.status === "fetching");
  const filesReload = files.reload;

  // A pasted link is pulled in on the server; check back until it's done.
  useEffect(() => {
    if (!fetching) return;
    const t = window.setInterval(filesReload, 2500);
    return () => window.clearInterval(t);
  }, [fetching, filesReload]);

  const done = () => {
    setSheet(null);
    files.reload();
  };
  return (
    <section className="section">
      <div className="actions actions-wrap">
        <button className="btn btn-primary" onClick={() => setSheet("upload")}>Upload or take a photo</button>
        <button className="btn" onClick={() => setSheet("link")}>Paste a link</button>
      </div>
      {!files.data ? (
        <Empty>{files.error ?? "Loading…"}</Empty>
      ) : files.data.length === 0 ? (
        <Empty>Nothing yet. Plans come by email, WhatsApp, paper (take a photo), Dropbox or Google Drive.</Empty>
      ) : (
        <FileList job={job} files={files.data} onChanged={files.reload} />
      )}
      {sheet === "upload" && <UploadSheet job={job} onClose={() => setSheet(null)} onDone={done} />}
      {sheet === "link" && <LinkSheet job={job} onClose={() => setSheet(null)} onDone={done} />}
    </section>
  );
}

function TakeoffStatus({ job }: { job: Job }) {
  const { userName } = useApp();
  const t = job.tasks.find((x) => x.id === job.open_takeoff_id);
  if (!t) return null;
  return (
    <p>
      <strong>{userName(t.assignee_id)}</strong> is on it — due {niceDate(t.due_date)}
      {t.status === "blocked" && <span className="pill pill-warn"> blocked: {t.outcome_note}</span>}
      <br />
      <span className="muted small">It's done once every chosen tile has its number. Finish it from Steps.</span>
    </p>
  );
}

// ------------------------------------------------------------ the files
function FileList({ job, files, onChanged }: { job: Job; files: JobFile[]; onChanged: () => void }) {
  const { busy, error, run } = useAction();
  const top = files.filter((f) => f.link_id == null);
  const children = (id: number) => files.filter((f) => f.link_id === id);
  const areaName = (id: number | null) => job.areas.find((a) => a.id === id)?.name;
  const groups = (["plan", "photo", "note", "other"] as const).map((k) => [k, top.filter((f) => f.kind === k)] as const).filter(([, l]) => l.length);
  const remove = (f: JobFile) => run(async () => { await api.patch(`/files/${f.id}`, { removed: true }); onChanged(); });

  const line = (f: JobFile, nested = false) => (
    <li key={f.id} className={`file-row ${nested ? "file-nested" : ""}`}>
      <div className="file-main">
        {f.url ? (
          <a href={f.url} target="_blank" rel="noopener" className="file-name">{f.name}</a>
        ) : (
          <span className="file-name">{f.name}</span>
        )}
        <span className="muted small">
          {[areaName(f.area_id), size(f.size_bytes), f.source === "link" ? "from a link" : null, niceDate(f.created_at)].filter(Boolean).join(" · ")}
        </span>
        {f.status === "fetching" && <span className="pill">Pulling it in…</span>}
      </div>
      {!nested && (
        <div className="file-actions">
          {f.status === "needs_download" && f.source === "link" && !(f.link_url ?? "").includes("/folders/") && (
            <button className="btn btn-quiet btn-small" disabled={busy} onClick={() => run(async () => { await api.post(`/files/${f.id}/retry`); onChanged(); })}>Try again</button>
          )}
          <button className="btn btn-quiet btn-small" disabled={busy} onClick={() => remove(f)} aria-label={`Remove ${f.name}`}>Remove</button>
        </div>
      )}
      {f.status === "needs_download" && (
        <p className="needs-download">
          <strong>Needs a download.</strong> {f.problem}
          {f.link_url && <> <a href={f.link_url} target="_blank" rel="noopener">Open the link</a></>}
        </p>
      )}
    </li>
  );

  return (
    <>
      {groups.map(([k, list]) => (
        <div key={k} className="file-group">
          <h3>{KIND_LABEL[k]}</h3>
          <ul className="list">
            {list.map((f) => [line(f), ...children(f.id).map((c) => line(c, true))])}
          </ul>
        </div>
      ))}
      <ErrorLine error={error} />
    </>
  );
}

function KindAndArea({ job, kind, setKind, areaId, setAreaId }: { job: Job; kind: JobFile["kind"]; setKind: (k: JobFile["kind"]) => void; areaId: number | null; setAreaId: (a: number | null) => void }) {
  return (
    <>
      <Field label="What is it">
        <div className="chips">
          {(["plan", "photo", "note", "other"] as const).map((k) => (
            <button key={k} type="button" className={`chip ${kind === k ? "chip-on" : ""}`} onClick={() => setKind(k)}>
              {{ plan: "Plans", photo: "Site photo", note: "Handwritten notes", other: "Other" }[k]}
            </button>
          ))}
        </div>
      </Field>
      {job.areas.length > 0 && (
        <Field label="For one area?" hint="Leave it on the whole job unless it's only one room.">
          <select value={areaId ?? ""} onChange={(e) => setAreaId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">The whole job</option>
            {job.areas.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </Field>
      )}
    </>
  );
}

function UploadSheet({ job, onClose, onDone }: { job: Job; onClose: () => void; onDone: () => void }) {
  const [picked, setPicked] = useState<File[]>([]);
  const [kind, setKind] = useState<JobFile["kind"]>("plan");
  const [areaId, setAreaId] = useState<number | null>(null);
  const camera = useRef<HTMLInputElement>(null);
  const chooser = useRef<HTMLInputElement>(null);
  const { busy, error, run } = useAction();
  const add = (list: FileList | null) => list && setPicked((p) => [...p, ...Array.from(list)]);
  return (
    <Sheet title="Add files" onClose={onClose}>
      <div className="actions actions-wrap">
        <button type="button" className="btn" onClick={() => camera.current?.click()}>Take a photo</button>
        <button type="button" className="btn" onClick={() => chooser.current?.click()}>Choose files</button>
      </div>
      <input ref={camera} type="file" accept="image/*" capture="environment" hidden onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
      <input ref={chooser} type="file" multiple accept="application/pdf,image/*,.dwg,.dxf,.doc,.docx,.xls,.xlsx,.zip" hidden onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
      {picked.length > 0 && (
        <ul className="list picked">
          {picked.map((f, i) => (
            <li key={i}>
              <span>{f.name || "Photo"}</span> <span className="muted small">{size(f.size)}</span>
              <button type="button" className="btn btn-quiet btn-small" onClick={() => setPicked(picked.filter((_, j) => j !== i))}>Remove</button>
            </li>
          ))}
        </ul>
      )}
      <p className="muted small">Paper plans: lay them flat in good light and take a photo of each page. Up to 25 MB a file.</p>
      <KindAndArea job={job} kind={kind} setKind={setKind} areaId={areaId} setAreaId={setAreaId} />
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button
          className="btn btn-primary"
          disabled={busy || !picked.length}
          onClick={() =>
            run(async () => {
              const form = new FormData();
              picked.forEach((f, i) => form.append("files", f, f.name || `photo-${i + 1}.jpg`));
              form.append("kind", kind);
              if (areaId != null) form.append("area_id", String(areaId));
              await api.upload(`/jobs/${job.id}/files`, form);
              onDone();
            })
          }
        >
          {busy ? "Uploading…" : `Add ${picked.length || ""} file${picked.length === 1 ? "" : "s"}`}
        </button>
      </div>
    </Sheet>
  );
}

function LinkSheet({ job, onClose, onDone }: { job: Job; onClose: () => void; onDone: () => void }) {
  const [url, setUrl] = useState("");
  const [kind, setKind] = useState<JobFile["kind"]>("plan");
  const [areaId, setAreaId] = useState<number | null>(null);
  const { busy, error, run } = useAction();
  return (
    <Sheet title="Paste a link" onClose={onClose}>
      <Field label="Link" hint="Dropbox files and folders, and Google Drive files, are pulled in and kept here. A private link or a Drive folder will say it needs a download.">
        <input type="url" inputMode="url" autoFocus value={url} onChange={(e) => setUrl(e.target.value)} />
      </Field>
      <KindAndArea job={job} kind={kind} setKind={setKind} areaId={areaId} setAreaId={setAreaId} />
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || !url.trim()} onClick={() => run(async () => { await api.post(`/jobs/${job.id}/links`, { url, kind, area_id: areaId }); onDone(); })}>
          Add the link
        </button>
      </div>
    </Sheet>
  );
}

// ------------------------------------------------------------ footage
/** The footage itself: typed straight on the tile, saved when you leave the box. */
function TileNumber({ cand, tag, onSaved }: { cand: Candidate; tag: Tag; onSaved: () => void }) {
  const unit = unitShort(unitOf(cand));
  const saved = tag.quantity != null ? String(tag.quantity) : "";
  const [value, setValue] = useState(saved);
  const { busy, error, run } = useAction();
  useEffect(() => setValue(saved), [saved]);
  const save = () => {
    if (value === saved || busy) return;
    const n = parseNum(value);
    if (!n.ok || n.value === 0) {
      run(async () => { throw new Error("That isn't a number. Type it like 420 or 420.5."); });
      return;
    }
    run(async () => { await api.patch(`/tags/${tag.id}`, { quantity: n.value }); onSaved(); });
  };
  return (
    <li className="tile-number">
      <span className="tile-number-name">{cand.display_name}</span>
      <label className={`tile-number-box ${value ? "" : "tile-number-empty"}`}>
        <input
          inputMode="decimal"
          aria-label={`${cand.display_name} footage`}
          value={value}
          onChange={(e) => setValue(e.target.value.replace(/[^\d.]/g, ""))}
          onBlur={save}
          onKeyDown={(e) => e.key === "Enter" && (e.currentTarget as HTMLInputElement).blur()}
        />
        <span>{unit}</span>
      </label>
      <ErrorLine error={error} />
    </li>
  );
}

/** The area's size: only where newly chosen tiles start. It fills tiles that have no number, never over one. */
function FootageSheet({ area, onClose, onDone }: { job: Job; area: Area; onClose: () => void; onDone: () => void }) {
  const [footage, setFootage] = useState(area.footage != null ? String(area.footage) : "");
  const { busy, error, run } = useAction();
  return (
    <Sheet title={`${area.name} — area size`} onClose={onClose}>
      <Field label="Square feet, waste included" hint="Chosen tiles in this area that have no number yet start from it. A tile's own number is never changed.">
        <input inputMode="decimal" autoFocus value={footage} onChange={(e) => setFootage(e.target.value.replace(/[^\d.]/g, ""))} />
      </Field>
      <ErrorLine error={error} />
      <div className="actions">
        {area.footage != null && (
          <button className="btn btn-quiet" disabled={busy} onClick={() => run(async () => { await api.put(`/areas/${area.id}/footage`, { footage: null }); onDone(); })}>Clear</button>
        )}
        <button
          className="btn btn-primary"
          disabled={busy || !footage || Number(footage) <= 0}
          onClick={() => run(async () => { await api.put(`/areas/${area.id}/footage`, { footage: Number(footage) }); onDone(); })}
        >
          Save
        </button>
      </div>
    </Sheet>
  );
}

// ------------------------------------------------------------ takeoff
function TakeoffSheet({ job, onClose, onDone }: { job: Job; onClose: () => void; onDone: () => void }) {
  const settings = useLoad(() => api.get<AppSettings>("/settings"), []);
  const [assignee, setAssignee] = useState<number | null>(null);
  const [due, setDue] = useState(plusDays(2));
  const [notes, setNotes] = useState("");
  const { busy, error, run } = useAction();
  const who = assignee ?? settings.data?.takeoff_user_id ?? null;
  return (
    <Sheet title="Request a takeoff" onClose={onClose}>
      {settings.data && !settings.data.takeoff_user_id && (
        <p className="muted small">No default takeoff person is set yet — an admin can set one on the Team screen. Pick someone for now.</p>
      )}
      <UserSelect label="Who does it" value={who} onChange={setAssignee} />
      <Field label="Due">
        <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
      </Field>
      <Field label="Anything they should know" hint="Optional — e.g. which pages, or skip the basement.">
        <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || !who} onClick={() => run(async () => { await api.post(`/jobs/${job.id}/takeoff`, { assignee_id: who, due_date: due, notes: notes || null }); onDone(); })}>
          Send for takeoff
        </button>
      </div>
    </Sheet>
  );
}

// ------------------------------------------------------- availability
const AVAIL: Record<string, { label: string; cls: string }> = {
  available: { label: "Available", cls: "pill-ok" },
  override: { label: "OK on two lots", cls: "pill-ok" },
  confirmed: { label: "Confirmed", cls: "pill-ok" },
  two_lots: { label: "Two lots only", cls: "pill-warn" },
  short: { label: "Short", cls: "pill-bad" },
};

export function Availability({ job, reload }: { job: Job; reload: () => void }) {
  const { me } = useApp();
  const [sheet, setSheet] = useState<null | { kind: "two_lots" | "confirm"; tag: Tag; cand: Candidate }>(null);
  const { busy, error, run } = useAction();
  const areas = new Map(job.areas.map((a) => [a.id, a]));
  const lines = job.candidates.flatMap((c) =>
    c.tags.filter((t) => t.status === "chosen" && ["open", "decided"].includes(areas.get(t.area_id)?.status ?? "")).map((t) => ({ c, t, a: areas.get(t.area_id)! })),
  );
  const isRep = me.id === job.rep_id || me.is_admin || me.role === "management";
  const open = lines.filter(({ t }) => !["available", "override", "confirmed"].includes(t.avail_status ?? ""));
  return (
    <section className="section">
      <p className="muted small">Our stock counts only if one lot covers it. Local: call the supplier. Overseas: confirm the lead time.</p>
      {lines.length === 0 ? (
        <Empty>Choose tiles for the areas on the Selection tab first.</Empty>
      ) : (
        <ul className="list">
          {lines.map(({ c, t, a }) => {
            const need = t.quantity;
            const stale = t.avail_status && c.source === "stock" && t.avail_need != null && need != null && Number(t.avail_need) !== Number(need);
            const st = t.avail_status ? AVAIL[t.avail_status] : null;
            return (
              <li key={t.id} className="avail-row">
                <div className="avail-main">
                  <strong>{c.display_name}</strong>
                  <span className="muted small">
                    {a.name}{need != null ? ` · needs ${sf(need)} ${unitShort(unitOf(c))}` : " · no footage on the tile yet"} · {c.source === "stock" ? "our stock" : c.source === "local" ? `local${c.supplier ? `, ${c.supplier}` : ""}` : `overseas${c.supplier ? `, ${c.supplier}` : ""}`}
                  </span>
                  {st && <span><span className={`pill ${st.cls}`}>{st.label}</span>{t.avail_lot && <span className="muted small"> lot {t.avail_lot}</span>}{t.avail_checked_at && <span className="muted small"> · {niceDate(t.avail_checked_at)} {niceTime(t.avail_checked_at)}</span>}</span>}
                  {t.avail_summary && <span className="small">{t.avail_summary.replace(/^.*? — /, "")}</span>}
                  {stale && <span className="stock-warn">The quantity changed since this check — check again.</span>}
                </div>
                <div className="avail-actions">
                  {c.source === "stock" ? (
                    <button className="btn btn-small" disabled={busy || need == null} onClick={() => run(async () => { await api.post(`/tags/${t.id}/availability/check`); reload(); })}>
                      {t.avail_status ? "Check again" : "Check"}
                    </button>
                  ) : (
                    <button className="btn btn-small" disabled={busy} onClick={() => setSheet({ kind: "confirm", tag: t, cand: c })}>
                      {c.source === "overseas" ? "Confirm lead time" : "Supplier's answer"}
                    </button>
                  )}
                  {t.avail_status === "two_lots" && isRep && (
                    <button className="btn btn-quiet btn-small" disabled={busy} onClick={() => setSheet({ kind: "two_lots", tag: t, cand: c })}>Go ahead on two lots</button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <ErrorLine error={error} />
      {sheet?.kind === "two_lots" && <TwoLotsSheet tag={sheet.tag} cand={sheet.cand} onClose={() => setSheet(null)} onDone={() => { setSheet(null); reload(); }} />}
      {sheet?.kind === "confirm" && <ConfirmSheet tag={sheet.tag} cand={sheet.cand} onClose={() => setSheet(null)} onDone={() => { setSheet(null); reload(); }} />}
    </section>
  );
}

function TwoLotsSheet({ tag, cand, onClose, onDone }: { tag: Tag; cand: Candidate; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const { busy, error, run } = useAction();
  return (
    <Sheet title="Go ahead on two lots" onClose={onClose}>
      <p>{cand.display_name}: no single lot covers it. Two lots can differ in shade — it's your call.</p>
      <Field label="Why it's fine" hint="Logged on the job. No customer sign-off needed.">
        <input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || !reason.trim()} onClick={() => run(async () => { await api.post(`/tags/${tag.id}/availability/two-lots`, { reason }); onDone(); })}>Go ahead</button>
      </div>
    </Sheet>
  );
}

function ConfirmSheet({ tag, cand, onClose, onDone }: { tag: Tag; cand: Candidate; onClose: () => void; onDone: () => void }) {
  const overseas = cand.source === "overseas";
  const [weeks, setWeeks] = useState(cand.lead_time_weeks != null ? String(cand.lead_time_weeks) : "");
  const [note, setNote] = useState("");
  const { busy, error, run } = useAction();
  const send = (ok: boolean) =>
    run(async () => {
      await api.post(`/tags/${tag.id}/availability/confirm`, { ok, note: note || null, lead_time_weeks: overseas && weeks ? Number(weeks) : null });
      onDone();
    });
  return (
    <Sheet title={overseas ? "Confirm the lead time" : "What the supplier said"} onClose={onClose}>
      <p className="muted">{cand.display_name}{cand.supplier ? ` — ${cand.supplier}` : ""}</p>
      {overseas && (
        <Field label="Lead time, in weeks">
          <input inputMode="numeric" value={weeks} onChange={(e) => setWeeks(e.target.value.replace(/\D/g, ""))} />
        </Field>
      )}
      <Field label="Note" hint={overseas ? "Optional — e.g. ships from Italy on the 3rd." : "Required if they're short."}>
        <input value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <ErrorLine error={error} />
      <div className="actions actions-wrap">
        <button className="btn" disabled={busy || !note.trim()} onClick={() => send(false)}>{overseas ? "Not possible" : "They're short"}</button>
        <button className="btn btn-primary" disabled={busy || (overseas && !weeks)} onClick={() => send(true)}>{overseas ? "Lead time confirmed" : "They have it"}</button>
      </div>
    </Sheet>
  );
}

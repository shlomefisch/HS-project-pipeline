import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { niceDate, plusDays, useApp, useLoad } from "../state";
import { Empty, ErrorLine, Field, Sheet, UserSelect, useAction } from "../ui";
import type { AppSettings, Area, Job, JobFile } from "../types";

const KIND_LABEL: Record<JobFile["kind"], string> = { plan: "Plans", photo: "Photos", note: "Notes", other: "Other" };
const SOURCE_LABEL: Record<string, string> = { customer: "Customer", designer: "Designer", installer: "Installer", takeoff: "Our takeoff" };

const sf = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 2 });
const size = (b: number | null) => (b == null ? "" : b > 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);

/** Order assembly, first part: what the job is built from — plans, footage per area, the takeoff. */
export function Plans({ job, reload }: { job: Job; reload: () => void }) {
  const files = useLoad(() => api.get<JobFile[]>(`/jobs/${job.id}/files`), [job.id]);
  const [sheet, setSheet] = useState<null | "upload" | "link" | "takeoff" | { area: Area }>(null);
  const fetching = !!files.data?.some((f) => f.status === "fetching");
  const filesReload = files.reload;

  // A pasted link is pulled in on the server; check back until it's done.
  useEffect(() => {
    if (!fetching) return;
    const t = window.setInterval(filesReload, 2500);
    return () => window.clearInterval(t);
  }, [fetching, filesReload]);

  const live = job.areas.filter((a) => a.status === "open" || a.status === "decided");
  const missing = live.filter((a) => a.footage == null);
  const total = live.reduce((n, a) => n + (a.footage ?? 0), 0);
  const plans = (files.data ?? []).filter((f) => f.kind === "plan" && f.status === "ready" && (f.url || f.source === "link"));
  const done = () => {
    setSheet(null);
    reload();
    files.reload();
  };

  return (
    <div className="plans">
      {/* ---- footage ---- */}
      <section className="section">
        <div className="section-head">
          <h2>Footage</h2>
          {live.length > 0 && <span className="muted small">{missing.length ? `${missing.length} area${missing.length === 1 ? " still needs" : "s still need"} a number` : `${sf(total)} sf in all`}</span>}
        </div>
        <p className="muted small">One number per area, waste included. No number, no estimate — an approximate one is fine.</p>
        {live.length === 0 ? (
          <Empty>Add the areas on the Selection tab first.</Empty>
        ) : (
          <ul className="list">
            {live.map((a) => (
              <li key={a.id}>
                <button className="row-btn footage-row" onClick={() => setSheet({ area: a })}>
                  <strong>{a.name}</strong>
                  {a.footage == null ? (
                    <span className="footage-missing">No footage yet</span>
                  ) : (
                    <span>
                      <span className="footage-num">{sf(a.footage)} sf</span>{" "}
                      <span className={`pill ${a.footage_confidence === "confirmed" ? "pill-ok" : "pill-warn"}`}>{a.footage_confidence}</span>
                      <span className="muted small"> — {SOURCE_LABEL[a.footage_source ?? ""] ?? a.footage_source}{a.footage_by ? `, ${a.footage_by}` : ""}</span>
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ---- takeoff ---- */}
      <section className="section">
        <h2>Takeoff</h2>
        {job.open_takeoff_id ? (
          <TakeoffStatus job={job} />
        ) : (
          <>
            <p className="muted small">
              {plans.length ? "Plans are on the job. Send them for a takeoff when the areas are set." : "Put the plans on the job first — then the takeoff can be requested."}
            </p>
            {job.status === "active" && (
              <button className="btn" disabled={!plans.length} onClick={() => setSheet("takeoff")}>
                Request a takeoff
              </button>
            )}
          </>
        )}
      </section>

      {/* ---- files ---- */}
      <section className="section">
        <div className="section-head">
          <h2>Plans and files</h2>
        </div>
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
      </section>

      {sheet === "upload" && <UploadSheet job={job} onClose={() => setSheet(null)} onDone={done} />}
      {sheet === "link" && <LinkSheet job={job} onClose={() => setSheet(null)} onDone={done} />}
      {sheet === "takeoff" && <TakeoffSheet job={job} onClose={() => setSheet(null)} onDone={done} />}
      {sheet && typeof sheet === "object" && <FootageSheet job={job} area={sheet.area} onClose={() => setSheet(null)} onDone={done} />}
    </div>
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
      <span className="muted small">It closes once every area has its footage. Finish it from the Steps tab.</span>
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
        <input type="url" inputMode="url" autoFocus value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://www.dropbox.com/…" />
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
function FootageSheet({ job, area, onClose, onDone }: { job: Job; area: Area; onClose: () => void; onDone: () => void }) {
  const { me } = useApp();
  const [footage, setFootage] = useState(area.footage != null ? String(area.footage) : "");
  const [source, setSource] = useState<string>(area.footage_source ?? "");
  const [by, setBy] = useState(area.footage_by ?? "");
  const [confidence, setConfidence] = useState<string>(area.footage_confidence ?? "approximate");
  const { busy, error, run } = useAction();
  // Suggest the people on the job for "who said it".
  const suggest = (s: string) => {
    if (s === "takeoff") return me.name;
    const role = job.roles.find((r) => r.active && (s === "customer" ? r.role === "owner" : r.role === s));
    return role?.entity.name ?? "";
  };
  return (
    <Sheet title={`${area.name} — footage`} onClose={onClose}>
      <Field label="Square feet, waste included">
        <input inputMode="decimal" autoFocus value={footage} onChange={(e) => setFootage(e.target.value.replace(/[^\d.]/g, ""))} />
      </Field>
      <Field label="Where the number came from">
        <div className="chips">
          {Object.entries(SOURCE_LABEL).map(([k, v]) => (
            <button key={k} type="button" className={`chip ${source === k ? "chip-on" : ""}`} onClick={() => { setSource(k); if (!by) setBy(suggest(k)); }}>
              {v}
            </button>
          ))}
        </div>
      </Field>
      <Field label="Who said it">
        <input value={by} onChange={(e) => setBy(e.target.value)} placeholder={source === "takeoff" ? me.name : "Name"} />
      </Field>
      <Field label="How sure">
        <div className="chips">
          <button type="button" className={`chip ${confidence === "approximate" ? "chip-on" : ""}`} onClick={() => setConfidence("approximate")}>Approximate</button>
          <button type="button" className={`chip ${confidence === "confirmed" ? "chip-on" : ""}`} onClick={() => setConfidence("confirmed")}>Confirmed</button>
        </div>
      </Field>
      <ErrorLine error={error} />
      <div className="actions">
        {area.footage != null && (
          <button className="btn btn-quiet" disabled={busy} onClick={() => run(async () => { await api.put(`/areas/${area.id}/footage`, { footage: null }); onDone(); })}>Clear</button>
        )}
        <button
          className="btn btn-primary"
          disabled={busy || !footage || Number(footage) <= 0 || !source}
          onClick={() => run(async () => { await api.put(`/areas/${area.id}/footage`, { footage: Number(footage), source, by: by || null, confidence }); onDone(); })}
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

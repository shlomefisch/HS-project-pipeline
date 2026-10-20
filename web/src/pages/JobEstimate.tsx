import { useState } from "react";
import { api } from "../api";
import { niceDate, useApp, useLoad } from "../state";
import { Empty, ErrorLine, Field, Loading, Sheet, useAction } from "../ui";
import type { Estimate, EstimateLine, Job } from "../types";

const money = (n: number | null) => (n == null ? "—" : n.toLocaleString(undefined, { style: "currency", currency: "USD" }));
const qtyFmt = (n: number | null) => (n == null ? "—" : n.toLocaleString(undefined, { maximumFractionDigits: 2 }));

/** Order assembly, last part: the estimate. Built here, priced from NetSuite's Base Price. */
export function EstimateTab({ job, reload }: { job: Job; reload: () => void }) {
  const ests = useLoad(() => api.get<Estimate[]>(`/jobs/${job.id}/estimates`), [job.id]);
  if (!ests.data) return <Loading error={ests.error} />;
  const draft = ests.data.find((e) => e.status === "draft");
  const pushed = ests.data.filter((e) => e.status === "pushed");
  const after = () => { ests.reload(); reload(); };
  return (
    <div className="estimate">
      {draft ? <Draft job={job} est={draft} onChanged={after} /> : <Start job={job} onDone={after} />}
      {pushed.length > 0 && (
        <section className="section">
          <h2>Sent to NetSuite</h2>
          <ul className="list">
            {pushed.map((e) => (
              <li key={e.id}>{niceDate(e.pushed_at)} — {money(e.total)} {e.netsuite_estimate_id ? `(NetSuite #${e.netsuite_estimate_id})` : ""}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function Start({ job, onDone }: { job: Job; onDone: () => void }) {
  const ready = job.areas.filter((a) => a.status === "open" || a.status === "decided");
  const [picked, setPicked] = useState<number[]>(ready.filter((a) => a.footage != null).map((a) => a.id));
  const { busy, error, run } = useAction();
  const chosenIn = (areaId: number) => job.candidates.some((c) => c.tags.some((t) => t.area_id === areaId && t.status === "chosen"));
  return (
    <section className="section">
      <h2>Put together an estimate</h2>
      <p className="muted small">Pick the areas that go on this order. Each needs its footage and a chosen tile. Areas on hold become their own order later.</p>
      {ready.length === 0 ? (
        <Empty>No open areas on this job.</Empty>
      ) : (
        <ul className="list">
          {ready.map((a) => {
            const problem = a.footage == null ? "no footage yet" : !chosenIn(a.id) ? "no tile chosen" : null;
            return (
              <li key={a.id}>
                <label className="check">
                  <input type="checkbox" checked={picked.includes(a.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, a.id] : picked.filter((x) => x !== a.id))} />
                  <span><strong>{a.name}</strong>{" "}
                    <span className={problem ? "footage-missing small" : "muted small"}>{problem ?? `${qtyFmt(a.footage)} sf, ${a.footage_confidence}`}</span>
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
      <ErrorLine error={error} />
      <button className="btn btn-primary" disabled={busy || !picked.length || job.status !== "active"} onClick={() => run(async () => { await api.post(`/jobs/${job.id}/estimates`, { area_ids: picked }); onDone(); })}>
        {busy ? "Pricing from NetSuite…" : "Build the estimate"}
      </button>
    </section>
  );
}

function Draft({ job, est, onChanged }: { job: Job; est: Estimate; onChanged: () => void }) {
  const { userName } = useApp();
  const [editing, setEditing] = useState<EstimateLine | null>(null);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const { busy, error, run } = useAction();
  const areaNames = est.area_ids.map((id) => job.areas.find((a) => a.id === id)?.name).filter(Boolean).join(", ");
  return (
    <section className="section">
      <div className="section-head">
        <h2>Estimate — being put together</h2>
        <span className="muted small">{niceDate(est.created_at)} · {userName(est.created_by)}</span>
      </div>
      <p className="muted small">{areaNames}. Prices start at NetSuite's Base Price — tap a line to change it. Nothing has gone to NetSuite yet.</p>
      {est.warnings.length > 0 && (
        <ul className="est-warnings">
          {est.warnings.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}
      <ul className="list est-lines">
        {est.lines.map((ln) => (
          <li key={ln.id}>
            <button className="row-btn est-line" onClick={() => setEditing(ln)}>
              <span className="est-desc">{ln.description}</span>
              <span className="est-math">
                {qtyFmt(ln.quantity)} {ln.unit ?? ""} × {money(ln.price)}
                {ln.overridden && <span className="pill pill-warn">changed</span>}
              </span>
              <span className="est-amount">{money(ln.amount)}</span>
            </button>
          </li>
        ))}
      </ul>
      <p className="est-total">Total <strong>{money(est.total)}</strong> <span className="muted small">before tax</span></p>
      <ErrorLine error={error} />
      <div className="actions actions-wrap">
        <button className="btn btn-quiet" disabled={busy} onClick={() => setConfirmDiscard(true)}>Discard</button>
        <button className="btn" disabled={busy} onClick={() => run(async () => { await api.post(`/estimates/${est.id}/refresh-prices`); onChanged(); })}>Re-read prices</button>
        <button className="btn btn-primary" disabled title="Coming next: sending the estimate to NetSuite">Send to NetSuite (next)</button>
      </div>
      {editing && <LineSheet line={editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); onChanged(); }} />}
      {confirmDiscard && (
        <Sheet title="Discard this estimate?" onClose={() => setConfirmDiscard(false)}>
          <p>The lines and any changed prices go. The job, its tiles and footage stay as they are.</p>
          <div className="actions">
            <button className="btn btn-quiet" onClick={() => setConfirmDiscard(false)}>Keep it</button>
            <button className="btn btn-primary" disabled={busy} onClick={() => run(async () => { await api.post(`/estimates/${est.id}/discard`); setConfirmDiscard(false); onChanged(); })}>Discard</button>
          </div>
        </Sheet>
      )}
    </section>
  );
}

function LineSheet({ line, onClose, onDone }: { line: EstimateLine; onClose: () => void; onDone: () => void }) {
  const [qty, setQty] = useState(line.quantity != null ? String(line.quantity) : "");
  const [price, setPrice] = useState(line.price != null ? String(line.price) : "");
  const [note, setNote] = useState(line.price_note ?? "");
  const { busy, error, run } = useAction();
  const changed = price !== "" && line.base_price != null && Number(price) !== Number(line.base_price);
  return (
    <Sheet title={line.description} onClose={onClose}>
      <Field label={`Quantity (${line.unit ?? "SF"})`}>
        <input inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value.replace(/[^\d.]/g, ""))} />
      </Field>
      <Field label="Price" hint={line.base_price != null ? `NetSuite Base Price: ${money(line.base_price)}` : "NetSuite has no Base Price for this item."}>
        <input inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value.replace(/[^\d.]/g, ""))} />
      </Field>
      {changed && (
        <Field label="Why the change" hint="Optional — shows in the job's story.">
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Contractor deal" />
        </Field>
      )}
      <ErrorLine error={error} />
      <div className="actions actions-wrap">
        {line.overridden && (
          <button className="btn btn-quiet" disabled={busy} onClick={() => run(async () => { await api.patch(`/estimate-lines/${line.id}`, { price: null, price_note: null }); onDone(); })}>Back to Base Price</button>
        )}
        <button
          className="btn btn-primary"
          disabled={busy || !qty || Number(qty) <= 0 || price === ""}
          onClick={() => run(async () => { await api.patch(`/estimate-lines/${line.id}`, { quantity: Number(qty), price: Number(price), price_note: changed ? note || null : null }); onDone(); })}
        >
          Save
        </button>
      </div>
    </Sheet>
  );
}

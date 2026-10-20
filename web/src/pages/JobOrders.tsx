import { useState } from "react";
import { api } from "../api";
import { niceDate, useApp, useLoad } from "../state";
import { Empty, ErrorLine, Field, Loading, Sheet, UserSelect, useAction } from "../ui";
import type { Job, Order } from "../types";
import { celebrateHere } from "../celebrate";

const STAGES: [Order["stage"], string][] = [
  ["negotiating", "Negotiating"],
  ["processing", "Processing"],
  ["delivery", "For delivery"],
  ["closing", "Closing"],
  ["closed", "Closed"],
];
const money = (n: number | null) => (n == null ? "—" : n.toLocaleString(undefined, { style: "currency", currency: "USD" }));
const qty = (n: number | null) => (n == null ? "—" : n.toLocaleString(undefined, { maximumFractionDigits: 2 }));

/** After the estimate: each order on its own track, until it's closed. */
export function Orders({ job, reload }: { job: Job; reload: () => void }) {
  const orders = useLoad(() => api.get<Order[]>(`/jobs/${job.id}/orders`), [job.id]);
  const changed = () => { orders.reload(); reload(); };
  if (!orders.data) return <Loading error={orders.error} />;
  return (
    <div className="orders">
      {orders.data.length === 0 ? (
        <Empty>No orders yet. When an estimate goes out (Estimate tab), it becomes an order here.</Empty>
      ) : (
        orders.data.map((o) => <OrderCard key={o.id} job={job} order={o} onChanged={changed} />)
      )}
      <CloseJob job={job} orders={orders.data} onDone={changed} />
    </div>
  );
}

function OrderCard({ job, order: o, onChanged }: { job: Job; order: Order; onChanged: () => void }) {
  const { userName } = useApp();
  const [sheet, setSheet] = useState<null | "approve" | "lose" | { lineId: number }>(null);
  const { busy, error, run } = useAction();
  const at = STAGES.findIndex(([k]) => k === o.stage);
  const areaNames = o.area_ids.map((id) => job.areas.find((a) => a.id === id)?.name).filter(Boolean).join(", ");
  const act = (path: string, body: unknown = {}, cheer = false) => run(async () => { await api.post(`/orders/${o.id}/${path}`, body); if (cheer) celebrateHere(); onChanged(); });

  return (
    <section className={`order-card order-${o.stage}`}>
      <header className="order-head">
        <div>
          <h2>{areaNames || "Order"} <span className="muted small">#{o.id}</span></h2>
          <p className="muted small">
            Placed {niceDate(o.created_at)}{o.netsuite_estimate_ref ? ` — NetSuite estimate ${o.netsuite_estimate_ref}` : ""}
            {o.netsuite_order_ref ? ` — sales order ${o.netsuite_order_ref}` : ""}
            {o.handler_id ? ` — handled by ${userName(o.handler_id)}` : ""}
          </p>
        </div>
        <strong className="order-total">{money(o.total)}</strong>
      </header>

      {o.stage === "lost" ? (
        <p className="status-banner status-lost">Lost — {o.lost_reason}</p>
      ) : (
        <ol className="order-track" aria-label="Order stage">
          {STAGES.map(([k, label], i) => (
            <li key={k} className={i < at ? "done" : i === at ? "now" : ""}>{label}</li>
          ))}
        </ol>
      )}

      {/* the one next move for this stage */}
      <div className="actions actions-wrap">
        {o.stage === "negotiating" && <button className="btn btn-primary" onClick={() => setSheet("approve")}>Approved — sales order made</button>}
        {o.stage === "processing" && <button className="btn btn-primary" disabled={busy} onClick={() => act("ready")}>Ready for delivery</button>}
        {(o.stage === "processing" || o.stage === "delivery") && !o.checks.delivered && (
          <button className="btn" disabled={busy} onClick={() => act("check", { check: "delivered" }, true)}>Everything delivered</button>
        )}
        {o.stage === "closing" && (
          <button className="btn btn-primary" disabled={busy || Object.values(o.checks).some((v) => !v)} onClick={() => act("close", {}, true)}>Close the order</button>
        )}
        {!["closed", "lost"].includes(o.stage) && <button className="btn btn-quiet" onClick={() => setSheet("lose")}>Lost</button>}
      </div>

      {["processing", "delivery", "closing", "closed"].includes(o.stage) && (
        <div className="checklist">
          <h3>Closing checklist</h3>
          {(Object.keys(o.check_labels) as (keyof Order["checks"])[]).map((k) => (
            <label key={k} className={`check ${o.checks[k] ? "checked" : ""}`}>
              <input type="checkbox" checked={!!o.checks[k]} disabled={busy || o.stage === "closed"} onChange={(e) => act("check", { check: k, done: e.target.checked }, e.target.checked)} />
              <span>{o.check_labels[k]}{o.checks[k] && <span className="muted small"> — {niceDate(o.checks[k])}</span>}</span>
            </label>
          ))}
        </div>
      )}

      <details className="order-lines">
        <summary>{o.lines.length} line{o.lines.length === 1 ? "" : "s"}{o.changes.length ? ` · ${o.changes.length} change${o.changes.length === 1 ? "" : "s"} after the order` : ""}</summary>
        <ul className="list">
          {o.lines.map((ln) => (
            <li key={ln.id} className="order-line">
              <span className="est-desc">{ln.description}</span>
              <span className="muted small">{qty(ln.quantity)} {ln.unit} × {money(ln.price)} = {money(ln.amount)}</span>
              {!["closed", "lost"].includes(o.stage) && <button className="btn btn-quiet btn-small" onClick={() => setSheet({ lineId: ln.id })}>Change quantity</button>}
            </li>
          ))}
        </ul>
        {o.changes.length > 0 && (
          <ul className="changes">
            {o.changes.map((c) => {
              const ln = o.lines.find((l) => l.id === c.line_id);
              return <li key={c.id} className="small">{niceDate(c.created_at)} — {ln?.description}: {qty(c.old_quantity)} → {qty(c.new_quantity)} — {c.reason} ({userName(c.created_by)})</li>;
            })}
          </ul>
        )}
      </details>
      <ErrorLine error={error} />

      {sheet === "approve" && <ApproveSheet job={job} order={o} onClose={() => setSheet(null)} onDone={() => { setSheet(null); celebrateHere(); onChanged(); }} />}
      {sheet === "lose" && <LoseSheet order={o} onClose={() => setSheet(null)} onDone={() => { setSheet(null); onChanged(); }} />}
      {sheet && typeof sheet === "object" && <QtySheet order={o} lineId={sheet.lineId} onClose={() => setSheet(null)} onDone={() => { setSheet(null); onChanged(); }} />}
    </section>
  );
}

function ApproveSheet({ job, order, onClose, onDone }: { job: Job; order: Order; onClose: () => void; onDone: () => void }) {
  const [handler, setHandler] = useState<number | null>(null);
  const [ref, setRef] = useState("");
  const [askPm, setAskPm] = useState(false);
  const { busy, error, run } = useAction();
  // Once it's approved, the customer's PM usually becomes the one to call.
  const pm = job.roles.find((r) => r.active && r.role === "pm" && r.entity.id !== job.default_contact_id);
  const current = job.roles.find((r) => r.active && r.entity.id === job.default_contact_id)?.entity.name;

  if (askPm && pm)
    return (
      <Sheet title="Approved — switch the main contact?" onClose={onDone}>
        <p>
          <strong>{pm.entity.name}</strong> is the customer's PM on this job. Make them the main contact from here on
          {current ? <>, instead of {current}</> : null}?
        </p>
        <ErrorLine error={error} />
        <div className="actions">
          <button className="btn btn-quiet" disabled={busy} onClick={onDone}>Keep {current ?? "it as is"}</button>
          <button className="btn btn-primary" disabled={busy} onClick={() => run(async () => { await api.patch(`/jobs/${job.id}`, { default_contact_id: pm.entity.id }); onDone(); })}>
            Make {pm.entity.name} the main contact
          </button>
        </div>
      </Sheet>
    );

  return (
    <Sheet title="Approved — sales order made" onClose={onClose}>
      <p className="muted small">Pick who handles it from here. From now on the order's work and problems go to them, not the rep.</p>
      <UserSelect label="Handler" value={handler} onChange={setHandler} />
      <Field label="NetSuite sales order number" hint="Optional."><input value={ref} onChange={(e) => setRef(e.target.value)} /></Field>
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button
          className="btn btn-primary"
          disabled={busy || !handler}
          onClick={() => run(async () => { await api.post(`/orders/${order.id}/approve`, { handler_id: handler, netsuite_order_ref: ref || null }); if (pm) setAskPm(true); else onDone(); })}
        >
          Approve
        </button>
      </div>
    </Sheet>
  );
}

function LoseSheet({ order, onClose, onDone }: { order: Order; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const { busy, error, run } = useAction();
  return (
    <Sheet title="Order lost" onClose={onClose}>
      <Field label="Why"><input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || !reason.trim()} onClick={() => run(async () => { await api.post(`/orders/${order.id}/lose`, { reason }); onDone(); })}>Mark lost</button>
      </div>
    </Sheet>
  );
}

function QtySheet({ order, lineId, onClose, onDone }: { order: Order; lineId: number; onClose: () => void; onDone: () => void }) {
  const ln = order.lines.find((l) => l.id === lineId)!;
  const [q, setQ] = useState(ln.quantity != null ? String(ln.quantity) : "");
  const [reason, setReason] = useState("");
  const { busy, error, run } = useAction();
  return (
    <Sheet title="Change after the order" onClose={onClose}>
      <p><strong>{ln.description}</strong><br /><span className="muted small">Ordered: {qty(ln.quantity)} {ln.unit}. A whole new area is a new order instead.</span></p>
      <Field label={`New quantity (${ln.unit ?? "SF"})`}><input inputMode="decimal" value={q} onChange={(e) => setQ(e.target.value.replace(/[^\d.]/g, ""))} /></Field>
      <Field label="Why"><input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || q === "" || !reason.trim()} onClick={() => run(async () => { await api.post(`/orders/${order.id}/quantity`, { line_id: ln.id, quantity: Number(q), reason }); onDone(); })}>Save the change</button>
      </div>
    </Sheet>
  );
}

function CloseJob({ job, orders, onDone }: { job: Job; orders: Order[]; onDone: () => void }) {
  const { busy, error, run } = useAction();
  if (job.status === "closed") return <p className="status-banner status-closed">Job closed — done.</p>;
  const anyClosed = orders.some((o) => o.stage === "closed");
  const openOrders = orders.filter((o) => !["closed", "lost"].includes(o.stage)).length;
  const waiting = job.areas.filter((a) => ["open", "decided", "on_hold", "ordered"].includes(a.status));
  if (!anyClosed) return null;
  return (
    <section className="close-job">
      <h3>Close the job</h3>
      <p className="muted small">
        {openOrders || waiting.length
          ? `Not yet: ${[openOrders ? `${openOrders} order(s) still open` : null, waiting.length ? `${waiting.map((a) => a.name).join(", ")} not delivered or dropped` : null].filter(Boolean).join("; ")}. An area on hold keeps the job open.`
          : "Every order is closed and every area delivered or dropped. Nothing open, nothing owed, nothing coming back."}
      </p>
      <ErrorLine error={error} />
      <button className="btn btn-sand" disabled={busy || openOrders > 0 || waiting.length > 0} onClick={() => run(async () => { await api.post(`/jobs/${job.id}/close`); celebrateHere(); onDone(); })}>Close the job — it's done</button>
    </section>
  );
}

import { useState } from "react";
import { api } from "../api";
import { useLoad } from "../state";
import { ErrorLine, Loading, Sheet, useAction } from "../ui";
import type { Estimate } from "../types";
import { celebrateHere } from "../celebrate";

interface Check {
  configured: boolean;
  bill_to: { entity_id: number; name: string; role: string; netsuite_customer_id: string | null }[];
  blockers: string[];
  warnings: string[];
  account: string;
}
interface Match { id: number; name: string; number: string | null; email: string | null; phone: string | null; why: string[] }

/** Bill-to, the NetSuite customer, the warnings read — then it goes. Only ever an estimate. */
export function SendEstimate({ est, onClose, onDone }: { est: Estimate; onClose: () => void; onDone: () => void }) {
  const check = useLoad(() => api.get<Check>(`/estimates/${est.id}/push`), [est.id]);
  const [billTo, setBillTo] = useState<number | null>(null);
  const [matches, setMatches] = useState<Match[] | null>(null);
  const [customer, setCustomer] = useState<number | "new" | null>(null);
  const [read, setRead] = useState(false);
  const { busy, error, run } = useAction();
  if (!check.data) return <Sheet title="Send to NetSuite" onClose={onClose}><Loading error={check.error} /></Sheet>;
  const c = check.data;
  const who = c.bill_to.find((b) => b.entity_id === (billTo ?? c.bill_to[0]?.entity_id));
  const known = who?.netsuite_customer_id;

  if (!c.configured) {
    return (
      <Sheet title="Send to NetSuite" onClose={onClose}>
        <p>Sending to NetSuite isn't switched on yet.</p>
        <p className="muted small">It needs its own NetSuite role and access token, kept apart from the POS. Once the keys are on Railway (NS_WRITE_TOKEN_ID and NS_WRITE_TOKEN_SECRET), this button sends the estimate.</p>
      </Sheet>
    );
  }

  const pickWho = (id: number) => {
    setBillTo(id);
    setMatches(null);
    setCustomer(null);
  };
  const search = () =>
    run(async () => {
      if (!who) return;
      setMatches(await api.get<Match[]>(`/entities/${who.entity_id}/netsuite-customers`));
    });
  const send = () =>
    run(async () => {
      await api.post(`/estimates/${est.id}/push`, {
        entity_id: who!.entity_id,
        netsuite_customer_id: typeof customer === "number" ? customer : null,
        create_customer: customer === "new",
        acknowledge_warnings: read,
      });
      celebrateHere();
      onDone();
    });
  const ready = !!who && c.blockers.length === 0 && (c.warnings.length === 0 || read) && (known || customer !== null);

  return (
    <Sheet title="Send to NetSuite" onClose={onClose}>
      <p className="muted small">Creates an estimate in NetSuite — nothing further. Total {est.total.toLocaleString(undefined, { style: "currency", currency: "USD" })}.</p>

      {c.blockers.length > 0 && (
        <div className="error-line">
          <strong>Fix these first:</strong>
          <ul>{c.blockers.map((b, i) => <li key={i}>{b}</li>)}</ul>
        </div>
      )}

      <h3 className="send-h">Bill to</h3>
      <div className="chips">
        {c.bill_to.map((b) => (
          <button key={b.entity_id} type="button" className={`chip ${who?.entity_id === b.entity_id ? "chip-on" : ""}`} onClick={() => pickWho(b.entity_id)}>
            {b.name} <span className="muted small">· {b.role}</span>
          </button>
        ))}
      </div>

      {who && (
        <>
          <h3 className="send-h">NetSuite customer</h3>
          {known ? (
            <p>Linked to NetSuite customer <strong>#{known}</strong>.</p>
          ) : matches === null ? (
            <button className="btn" disabled={busy} onClick={search}>Find {who.name} in NetSuite</button>
          ) : (
            <ul className="list">
              {matches.map((m) => (
                <li key={m.id}>
                  <label className="check match-row">
                    <input type="radio" name="cust" checked={customer === m.id} onChange={() => setCustomer(m.id)} />
                    <span>
                      <strong>{m.name}</strong> <span className="muted small">#{m.number ?? m.id}</span>
                      <br />
                      <span className="muted small">{[m.email, m.phone].filter(Boolean).join(" · ")} — {m.why.join(", ")}</span>
                    </span>
                  </label>
                </li>
              ))}
              <li>
                <label className="check match-row">
                  <input type="radio" name="cust" checked={customer === "new"} onChange={() => setCustomer("new")} />
                  <span>{matches.length ? "None of these — create a new customer" : "No match in NetSuite — create a new customer"}</span>
                </label>
              </li>
            </ul>
          )}
        </>
      )}

      {c.warnings.length > 0 && (
        <>
          <ul className="est-warnings">{c.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
          <label className="check"><input type="checkbox" checked={read} onChange={(e) => setRead(e.target.checked)} /> I've read these — send anyway</label>
        </>
      )}

      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || !ready} onClick={send}>{busy ? "Sending…" : "Send the estimate"}</button>
      </div>
    </Sheet>
  );
}

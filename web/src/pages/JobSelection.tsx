import { useEffect, useState } from "react";
import { api } from "../api";
import { go, niceDate, niceTime, plusDays, useApp, useLoad } from "../state";
import { Empty, ErrorLine, Field, Sheet, useAction } from "../ui";
import type { Area, Candidate, Item, Job, Stock, Tag } from "../types";

const SOURCE_SHORT: Record<string, string> = { stock: "Stock", local: "Local", overseas: "Overseas" };

/** One flat list of tiles. Areas are tags, shown as groups — never folders to navigate into. */
export function Selection({ job, reload }: { job: Job; reload: () => void }) {
  const [hideDeclined, setHideDeclined] = useState(false);
  const [adding, setAdding] = useState(false);
  const [tagSheet, setTagSheet] = useState<{ tag: Tag; cand: Candidate } | null>(null);
  const [areaSheet, setAreaSheet] = useState<Area | null>(null);
  const [newArea, setNewArea] = useState(false);
  const [sample, setSample] = useState(false);

  const untagged = job.candidates.filter((c) => c.tags.length === 0);
  const lines = (area: Area) =>
    job.candidates
      .flatMap((c) => c.tags.filter((t) => t.area_id === area.id).map((t) => ({ c, t })))
      .filter(({ t }) => !(hideDeclined && t.status === "declined"));

  return (
    <section className="section selection">
      <div className="area-strip" role="list" aria-label="Areas">
        {job.areas.map((a) => (
          <button role="listitem" key={a.id} className={`area-chip area-${a.status}`} onClick={() => setAreaSheet(a)}>
            {a.name}
            <span className="area-state">{a.status === "open" ? "" : a.status === "on_hold" ? "on hold" : a.status}</span>
          </button>
        ))}
        <button className="area-chip area-add" onClick={() => setNewArea(true)}>
          Add area
        </button>
      </div>

      <div className="selection-bar">
        <button className="btn btn-primary" onClick={() => setAdding(true)}>
          Add a tile
        </button>
        <button className="btn" onClick={() => go(`scan/${job.id}`)}>
          Scan
        </button>
        <label className="check">
          <input type="checkbox" checked={hideDeclined} onChange={(e) => setHideDeclined(e.target.checked)} /> Hide declined
        </label>
      </div>

      {job.areas.length === 0 && job.candidates.length === 0 && <Empty>Add the areas they talked about — kitchen, vestibule — then the tiles they looked at.</Empty>}

      {job.areas.map((a) => {
        const rows = lines(a);
        return (
          <div key={a.id} className={`area-group area-${a.status}`}>
            <h3>
              {a.name}
              {a.status === "on_hold" && <span className="muted"> — on hold until {niceDate(a.hold_until)}</span>}
            </h3>
            {rows.length === 0 ? (
              <p className="muted small">Nothing considered yet.</p>
            ) : (
              <ul className="tile-lines">
                {rows.map(({ c, t }) => (
                  <li key={t.id}>
                    <button className={`tile-line tag-${t.status}`} onClick={() => setTagSheet({ tag: t, cand: c })}>
                      <span className="tile-name">{c.display_name}</span>
                      <span className="tile-meta">
                        {SOURCE_SHORT[c.source]}
                        {c.source === "overseas" ? (c.lead_time_weeks != null ? `, ${c.lead_time_weeks} wks` : ", lead time?") : ""}
                        {t.quantity != null ? `, ${t.quantity} ${t.unit}` : ""}
                        {t.status === "chosen" ? ", chosen" : ""}
                        {t.status === "declined" && t.reason ? `, ${t.reason}` : ""}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}

      {untagged.length > 0 && (
        <div className="area-group">
          <h3>Not tagged to an area yet</h3>
          <ul className="tile-lines">
            {untagged.map((c) => (
              <li key={c.id}>
                <button className="tile-line" onClick={() => setTagSheet({ tag: { id: 0, candidate_id: c.id, area_id: 0, status: "considering", quantity: null, unit: "sf", reason: null, decided_at: null }, cand: c })}>
                  <span className="tile-name">{c.display_name}</span>
                  <span className="tile-meta">{SOURCE_SHORT[c.source]}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="area-group">
        <h3>Samples</h3>
        {job.samples.length === 0 ? (
          <p className="muted small">None requested.</p>
        ) : (
          <ul className="list list-quiet">
            {job.samples.map((s) => (
              <li key={s.id}>
                <div className="row-static">
                <span className={s.status === "cancelled" ? "struck" : ""}>{s.description}</span>
                <span className="muted">
                  {s.status === "requested" && "Requested — not sent yet"}
                  {s.status === "sent" && `Sent ${niceDate(s.sent_on)}${s.expect_reply_by ? `, reply by ${niceDate(s.expect_reply_by)}` : ""}`}
                  {s.status === "replied" && "They got back to us"}
                  {s.status === "cancelled" && "Cancelled"}
                </span>
                </div>
                {(s.status === "requested" || s.status === "sent") && (
                  <button
                    className="btn btn-small"
                    onClick={async () => {
                      await api.patch(`/samples/${s.id}`, s.status === "requested" ? { status: "sent", expect_reply_by: s.expect_reply_by ?? plusDays(7) } : { status: "replied" });
                      reload();
                    }}
                  >
                    {s.status === "requested" ? "Mark sent" : "They replied"}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        <button className="btn btn-quiet" onClick={() => setSample(true)}>
          Request a sample
        </button>
      </div>

      {adding && <AddTile job={job} onClose={() => setAdding(false)} onDone={() => { setAdding(false); reload(); }} />}
      {tagSheet && <TagSheet job={job} {...tagSheet} onClose={() => setTagSheet(null)} onDone={() => { setTagSheet(null); reload(); }} />}
      {areaSheet && <AreaSheet area={areaSheet} onClose={() => setAreaSheet(null)} onDone={() => { setAreaSheet(null); reload(); }} />}
      {newArea && <NewArea job={job} onClose={() => setNewArea(false)} onDone={() => { setNewArea(false); reload(); }} />}
      {sample && <NewSample job={job} onClose={() => setSample(false)} onDone={() => { setSample(false); reload(); }} />}
    </section>
  );
}

// ------------------------------------------------------------ add tile
export function AddTile({ job, onClose, onDone, scanned }: { job: Job; onClose: () => void; onDone: () => void; scanned?: { id: number; item: Item | null } }) {
  const [source, setSource] = useState<"stock" | "local" | "overseas">("stock");
  const [item, setItem] = useState<{ id: number; name: string } | null>(scanned ? { id: scanned.id, name: scanned.item?.name ?? `Item #${scanned.id}` } : null);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Item[]>([]);
  const [searchedFor, setSearchedFor] = useState("");
  const [itemNo, setItemNo] = useState("");
  const [name, setName] = useState("");
  const [supplier, setSupplier] = useState("");
  const [weeks, setWeeks] = useState("");
  const [areas, setAreas] = useState<number[]>(job.areas.filter((a) => a.status === "open").length === 1 ? [job.areas.find((a) => a.status === "open")!.id] : []);
  const { busy, error, run } = useAction();

  useEffect(() => {
    if (source !== "stock" || !q.trim()) {
      setResults([]);
      setSearchedFor("");
      return;
    }
    const t = window.setTimeout(
      () =>
        api
          .get<Item[]>("/items", { q })
          .then((r) => {
            setResults(r);
            setSearchedFor(q);
          })
          .catch(() => {}),
      200,
    );
    return () => window.clearTimeout(t);
  }, [q, source]);

  const ready = source === "stock" ? !!item : !!name.trim();
  return (
    <Sheet title="Add a tile" onClose={onClose}>
      {!scanned && (
        <div className="chips" role="radiogroup" aria-label="Where it comes from">
          {(["stock", "local", "overseas"] as const).map((s) => (
            <button key={s} role="radio" aria-checked={source === s} className={`chip ${source === s ? "chip-on" : ""}`} onClick={() => setSource(s)}>
              {s === "stock" ? "Our stock" : s === "local" ? "Local supply" : "Overseas"}
            </button>
          ))}
        </div>
      )}
      {source === "stock" ? (
        item ? (
          <p className="picked">
            <strong>{item.name}</strong>
            {!scanned && (
              <button className="btn btn-small btn-quiet" onClick={() => setItem(null)}>
                Change
              </button>
            )}
          </p>
        ) : (
          <>
            <Field label="Find the item">
              <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name or SKU" />
            </Field>
            <ul className="list">
              {results.map((i) => (
                <li key={i.netsuite_id}>
                  <button className="row-btn" onClick={() => setItem({ id: i.netsuite_id, name: i.name })}>
                    <strong>{i.name}</strong>
                    <span className="muted">{[i.sku, i.size, i.finish].filter(Boolean).join(", ")}</span>
                  </button>
                </li>
              ))}
            </ul>
            {searchedFor.trim() && results.length === 0 && (
              <div className="no-match">
                <p>
                  Nothing in the item list matches “{searchedFor.trim()}”. The list fills in from NetSuite once the sync is built.
                  For now, enter the item's NetSuite number — the name fills in later, same as a scan.
                </p>
                <div className="inline">
                  <input inputMode="numeric" value={itemNo} onChange={(e) => setItemNo(e.target.value.replace(/\D/g, ""))} placeholder="NetSuite item number" aria-label="NetSuite item number" />
                  <button className="btn" disabled={!itemNo} onClick={() => setItem({ id: Number(itemNo), name: `Item #${itemNo} — ${searchedFor.trim()}` })}>
                    Use it
                  </button>
                </div>
                <p className="muted small">Or, if it isn't a stocking item, switch to Local supply above.</p>
              </div>
            )}
            {!searchedFor.trim() && <p className="muted small">Faster: use Scan and point at the tag.</p>}
          </>
        )
      ) : (
        <>
          <Field label="What is it">
            <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Italian terrazzo 24x24, verde" />
          </Field>
          <Field label="Supplier">
            <input value={supplier} onChange={(e) => setSupplier(e.target.value)} />
          </Field>
          {source === "overseas" && (
            <Field label="Lead time in weeks" hint="Ask now — this is often what kills an overseas choice.">
              <input inputMode="numeric" value={weeks} onChange={(e) => setWeeks(e.target.value.replace(/\D/g, ""))} />
            </Field>
          )}
        </>
      )}
      <AreaPicker job={job} value={areas} onChange={setAreas} />
      <ErrorLine error={error} />
      {!ready && <p className="muted small">{source === "stock" ? "Pick the item first — tap it in the list, or enter its number." : "Give the tile a name first."}</p>}
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn btn-primary"
          disabled={busy || !ready}
          onClick={() =>
            run(async () => {
              await api.post(`/jobs/${job.id}/candidates`, {
                source,
                netsuite_item_id: source === "stock" && item ? item.id : null,
                name: source === "stock" ? (item && item.name.startsWith("Item #") ? item.name.replace(/^Item #\d+ — /, "") : null) : name,
                supplier: source !== "stock" ? supplier || null : null,
                lead_time_weeks: source === "overseas" && weeks ? Number(weeks) : null,
                area_ids: areas,
              });
              onDone();
            })
          }
        >
          Add to the list
        </button>
      </div>
    </Sheet>
  );
}

function AreaPicker({ job, value, onChange }: { job: Job; value: number[]; onChange: (v: number[]) => void }) {
  const live = job.areas.filter((a) => a.status !== "dropped");
  if (live.length === 0) return <p className="muted small">No areas yet — you can tag it later.</p>;
  return (
    <Field label="For which areas" hint="Pick more than one if they're considering it in several rooms.">
      <div className="chips">
        {live.map((a) => (
          <button
            key={a.id}
            type="button"
            className={`chip ${value.includes(a.id) ? "chip-on" : ""}`}
            aria-pressed={value.includes(a.id)}
            onClick={() => onChange(value.includes(a.id) ? value.filter((x) => x !== a.id) : [...value, a.id])}
          >
            {a.name}
          </button>
        ))}
      </div>
    </Field>
  );
}

// --------------------------------------------------- decision on a tag
function TagSheet({ job, tag, cand, onClose, onDone }: { job: Job; tag: Tag; cand: Candidate; onClose: () => void; onDone: () => void }) {
  const area = job.areas.find((a) => a.id === tag.area_id);
  const [reason, setReason] = useState("");
  const [declining, setDeclining] = useState(false);
  const [qty, setQty] = useState(tag.quantity != null ? String(tag.quantity) : "");
  const [more, setMore] = useState<number[]>([]);
  const { busy, error, run } = useAction();
  const otherAreas = job.areas.filter((a) => a.status !== "dropped" && !cand.tags.some((t) => t.area_id === a.id));
  const isReal = tag.id !== 0;
  const set = (body: Record<string, unknown>) => run(async () => { await api.patch(`/tags/${tag.id}`, body); onDone(); });

  return (
    <Sheet title={cand.display_name} onClose={onClose}>
      <p className="muted">
        {isReal ? `In ${area?.name}` : "Not tagged to an area yet"}
        {cand.supplier ? ` — ${cand.supplier}` : ""}
        {tag.status === "declined" && tag.reason ? ` — declined: ${tag.reason}` : ""}
      </p>
      {cand.source === "stock" && cand.netsuite_item_id != null && <StockPanel itemId={cand.netsuite_item_id} need={tag.quantity} />}
      {isReal && !declining && (
        <div className="actions actions-wrap">
          {tag.status !== "chosen" && <button className="btn btn-primary" disabled={busy} onClick={() => set({ status: "chosen" })}>Choose for {area?.name}</button>}
          {tag.status !== "declined" && <button className="btn" disabled={busy} onClick={() => setDeclining(true)}>Decline</button>}
          {tag.status !== "considering" && <button className="btn btn-quiet" disabled={busy} onClick={() => set({ status: "considering" })}>Undo — back to considering</button>}
          {tag.status === "considering" && (
            <button className="btn btn-quiet" disabled={busy} onClick={() => run(async () => { await api.del(`/tags/${tag.id}`); onDone(); })}>
              Remove from {area?.name} (added by mistake)
            </button>
          )}
        </div>
      )}
      {declining && (
        <>
          <Field label="Why not?" hint="Stays on the list, crossed out, with this reason.">
            <input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Too cold next to the floor" />
          </Field>
          <div className="actions">
            <button className="btn btn-quiet" onClick={() => setDeclining(false)}>Back</button>
            <button className="btn btn-primary" disabled={busy || !reason.trim()} onClick={() => set({ status: "declined", reason })}>Decline</button>
          </div>
        </>
      )}
      {isReal && !declining && (
        <Field label={`Quantity for ${area?.name} (sf, waste included)`}>
          <div className="inline">
            <input inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value.replace(/[^\d.]/g, ""))} />
            <button className="btn btn-small" disabled={busy} onClick={() => set({ quantity: qty ? Number(qty) : null })}>Save</button>
          </div>
        </Field>
      )}
      {otherAreas.length > 0 && !declining && (
        <Field label={isReal ? "Also consider it for" : "Tag it to"}>
          <div className="chips">
            {otherAreas.map((a) => (
              <button key={a.id} type="button" className={`chip ${more.includes(a.id) ? "chip-on" : ""}`} onClick={() => setMore(more.includes(a.id) ? more.filter((x) => x !== a.id) : [...more, a.id])}>
                {a.name}
              </button>
            ))}
          </div>
          {more.length > 0 && (
            <button className="btn btn-small" disabled={busy} onClick={() => run(async () => { for (const id of more) await api.post(`/candidates/${cand.id}/tags`, { area_id: id }); onDone(); })}>
              Add
            </button>
          )}
        </Field>
      )}
      <ErrorLine error={error} />
    </Sheet>
  );
}

// -------------------------------------------------------------- areas
function NewArea({ job, onClose, onDone }: { job: Job; onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState("");
  const { busy, error, run } = useAction();
  const common = ["Kitchen", "Vestibule", "Master bath", "Powder room", "Basement", "Laundry", "Mudroom"].filter((n) => !job.areas.some((a) => a.name.toLowerCase() === n.toLowerCase()));
  const save = (n: string) => run(async () => { await api.post(`/jobs/${job.id}/areas`, { name: n }); onDone(); });
  return (
    <Sheet title="Add an area" onClose={onClose}>
      <div className="chips">
        {common.map((n) => (
          <button key={n} className="chip" disabled={busy} onClick={() => save(n)}>{n}</button>
        ))}
      </div>
      <form onSubmit={(e) => { e.preventDefault(); if (name.trim()) save(name); }}>
        <Field label="Or type it">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Guest bath, 2nd floor" />
        </Field>
        <ErrorLine error={error} />
        <div className="actions">
          <button type="button" className="btn btn-quiet" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy || !name.trim()}>Add area</button>
        </div>
      </form>
    </Sheet>
  );
}

function AreaSheet({ area, onClose, onDone }: { area: Area; onClose: () => void; onDone: () => void }) {
  const [holding, setHolding] = useState(false);
  const [until, setUntil] = useState(plusDays(90));
  const [reason, setReason] = useState("");
  const { busy, error, run } = useAction();
  const set = (body: Record<string, unknown>) => run(async () => { await api.patch(`/areas/${area.id}`, body); onDone(); });
  return (
    <Sheet title={area.name} onClose={onClose}>
      {!holding ? (
        <ul className="list">
          {area.status !== "decided" && <li><button className="row-btn" disabled={busy} onClick={() => set({ status: "decided" })}><strong>Decided</strong><span className="muted">A tile is chosen for this area</span></button></li>}
          {area.status !== "on_hold" && <li><button className="row-btn" onClick={() => setHolding(true)}><strong>On hold</strong><span className="muted">The rest of the job keeps moving</span></button></li>}
          {area.status !== "dropped" && <li><button className="row-btn" disabled={busy} onClick={() => set({ status: "dropped" })}><strong>Dropped</strong><span className="muted">Not part of this job any more</span></button></li>}
          {area.status !== "open" && <li><button className="row-btn" disabled={busy} onClick={() => set({ status: "open" })}><strong>Reopen</strong><span className="muted">Back to choosing</span></button></li>}
        </ul>
      ) : (
        <>
          <Field label="Come back on">
            <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} />
          </Field>
          <Field label="Why">
            <input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Basement waits till next year" />
          </Field>
          <div className="actions">
            <button className="btn btn-quiet" onClick={() => setHolding(false)}>Back</button>
            <button className="btn btn-primary" disabled={busy || !reason.trim()} onClick={() => set({ status: "on_hold", hold_until: until, hold_reason: reason })}>Put on hold</button>
          </div>
        </>
      )}
      <ErrorLine error={error} />
    </Sheet>
  );
}

function NewSample({ job, onClose, onDone }: { job: Job; onClose: () => void; onDone: () => void }) {
  const { toast } = useApp();
  const [description, setDescription] = useState("");
  const [areaId, setAreaId] = useState<number | null>(null);
  const { busy, error, run } = useAction();
  return (
    <Sheet title="Request a sample" onClose={onClose}>
      <Field label="Which samples">
        <input autoFocus value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Calacatta + Carrara, 2 pieces each" />
      </Field>
      <Field label="For">
        <select value={areaId ?? ""} onChange={(e) => setAreaId(e.target.value ? Number(e.target.value) : null)}>
          <option value="">The whole job</option>
          {job.areas.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
      </Field>
      <ErrorLine error={error} />
      <div className="actions">
        <button className="btn btn-quiet" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || !description.trim()} onClick={() => run(async () => { await api.post(`/jobs/${job.id}/samples`, { description, area_id: areaId }); toast("Sample requested"); onDone(); })}>
          Request sample
        </button>
      </div>
    </Sheet>
  );
}

// ------------------------------------------------------ live stock check
const qtyFmt = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 2 });

function StockPanel({ itemId, need }: { itemId: number; need: number | null }) {
  const [fresh, setFresh] = useState(0);
  const { data, error } = useLoad(() => api.get<Stock>(`/items/${itemId}/stock`, fresh ? { fresh: 1 } : undefined), [itemId, fresh]);
  const unit = data?.unit ? ` ${data.unit}` : "";
  const bestLot = data?.by_lot ? Math.max(0, ...data.rows.map((r) => r.available)) : null;
  // The job's quantity is in square feet; only compare when NetSuite counts this item in square feet too.
  const sameUnit = !!data?.unit && /^(sf|sq\.? ?ft\.?|sqft|square f)/i.test(data.unit.trim());
  if (!sameUnit) need = null;
  return (
    <section className="stock">
      <div className="stock-head">
        <strong>In stock</strong>
        {data && <button type="button" className="btn btn-quiet btn-small" onClick={() => setFresh((n) => n + 1)}>Refresh</button>}
      </div>
      {!data ? (
        error ? <p className="muted small">{error}</p> : <p className="muted small">Checking NetSuite…</p>
      ) : data.rows.length === 0 ? (
        <p className="stock-none">None on hand right now.</p>
      ) : (
        <>
          <p className="stock-total">
            <span className="stock-free">{qtyFmt(data.totals.available)}{unit}</span> free to sell
            <span className="muted"> · {qtyFmt(data.totals.on_hand)}{unit} on hand</span>
          </p>
          {need != null && bestLot != null && need > 0 && bestLot < need && data.totals.available >= need && (
            <p className="stock-warn">No single lot covers {qtyFmt(need)}{unit} — it would mix lots.</p>
          )}
          {need != null && need > 0 && data.totals.available < need && (
            <p className="stock-warn">Short: needs {qtyFmt(need)}{unit}, only {qtyFmt(data.totals.available)}{unit} free.</p>
          )}
          <table className="stock-table">
            <thead>
              <tr><th>Where</th>{data.by_lot && <th>Lot</th>}<th className="num">Free</th><th className="num">On hand</th></tr>
            </thead>
            <tbody>
              {data.rows.map((r, i) => (
                <tr key={i}>
                  <td>{r.location}</td>
                  {data.by_lot && <td>{r.lot ?? "—"}</td>}
                  <td className="num">{qtyFmt(r.available)}</td>
                  <td className="num muted">{qtyFmt(r.on_hand)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {data && <p className="muted small">From NetSuite, {niceTime(data.as_of)}. Free = on hand minus what's already committed to orders.</p>}
    </section>
  );
}

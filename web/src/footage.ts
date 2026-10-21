import type { Candidate, Job, Tag } from "./types";

/** How a tile is counted: NetSuite's unit for our stock, square feet otherwise. */
export const unitOf = (c: Candidate): string => (c.source === "stock" && c.item?.unit ? c.item.unit : "sf");
export const inSqft = (unit: string) => /^(sf|sq\.? ?ft\.?|sqft|square f)/i.test(unit.trim());
export const unitShort = (unit: string) => (inSqft(unit) ? "sf" : unit.toLowerCase());
export const num = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 2 });

/** The chosen tiles in one area, each with its tag for that area. */
export function chosenTiles(job: Job, areaId: number): { c: Candidate; t: Tag }[] {
  return job.candidates.flatMap((c) => c.tags.filter((t) => t.area_id === areaId && t.status === "chosen").map((t) => ({ c, t })));
}

/** A typed number: "" means empty on purpose; anything that isn't a plain positive number is refused. */
export function parseNum(text: string): { ok: true; value: number | null } | { ok: false } {
  const t = text.trim();
  if (t === "") return { ok: true, value: null };
  if (!/^\d+(\.\d+)?$|^\.\d+$/.test(t)) return { ok: false };
  const v = Number(t);
  return Number.isFinite(v) ? { ok: true, value: v } : { ok: false };
}

/** A footage box that can be saved: empty (clears it) or a number above zero. */
export const okQty = (text: string) => { const n = parseNum(text); return n.ok && n.value !== 0; };

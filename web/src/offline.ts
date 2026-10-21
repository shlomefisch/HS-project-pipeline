// Saves made without signal wait here, on the phone, and go out when it comes back.
// Every waiting save carries a one-time key, so a resend after a dropped answer is
// never applied twice. Screens last seen can still be read while offline.

const OUTBOX = "pipeline.outbox";
const FAILED = "pipeline.outbox.failed";
const CACHE = "pipeline.cache";
const CACHE_MAX = 40;
const OWNER = "pipeline.outbox.owner";

export interface Waiting {
  id: string;
  method: string;
  path: string;
  body: unknown;
  label: string;
  at: string;
  error?: string;
}

// Field work that's safe to hold and send later. Anything that needs the answer
// right away (sign-in, new jobs, new people, uploads, admin) stays online-only.
const QUEUEABLE: [string, RegExp, string][] = [
  ["POST", /^\/jobs\/\d+\/events$/, "Log what happened"],
  ["POST", /^\/jobs\/\d+\/tasks$/, "Add a step"],
  ["POST", /^\/tasks\/\d+\/(complete|reopen|acknowledge)$/, "Finish a step"],
  ["PATCH", /^\/tasks\/\d+$/, "Change a step"],
  ["POST", /^\/jobs\/\d+\/candidates$/, "Add a tile"],
  ["POST", /^\/candidates\/\d+\/tags$/, "Tag a tile to an area"],
  ["PATCH", /^\/tags\/\d+$/, "Choose or decline a tile"],
  ["POST", /^\/jobs\/\d+\/areas$/, "Add an area"],
  ["PATCH", /^\/areas\/\d+$/, "Change an area"],
  ["PUT", /^\/areas\/\d+\/footage$/, "Footage"],
  ["POST", /^\/jobs\/\d+\/samples$/, "Request a sample"],
  ["PATCH", /^\/samples\/\d+$/, "Update a sample"],
  ["POST", /^\/jobs\/\d+\/visits$/, "Book a visit"],
  ["POST", /^\/visits\/\d+\/(resolve|reschedule)$/, "Update a visit"],
];

// Reads worth keeping for offline: the screens people actually open.
// Not the history: it's big, and it would crowd out the waiting saves.
const CACHEABLE = [/^\/auth\/me$/, /^\/meta$/, /^\/users(\?.*)?$/, /^\/dashboard\//, /^\/jobs(\?.*)?$/, /^\/jobs\/\d+(\/(files|estimates))?$/, /^\/entities\/\d+$/];

export function queueLabel(method: string, path: string): string | null {
  const hit = QUEUEABLE.find(([m, re]) => m === method && re.test(path));
  return hit ? hit[2] : null;
}

export function newKey(): string {
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  return "k-" + Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    if (key === CACHE) return; // a full cache just means less to read offline
    // Storage full: the read cache goes first — a waiting save matters more than an old screen.
    try {
      localStorage.removeItem(CACHE);
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      throw new Error("This phone's storage is full, so the save couldn't be kept. Try again with signal.");
    }
  }
}

// ----------------------------------------------------------- listeners
type Listener = () => void;
const listeners = new Set<Listener>();
export function onOutboxChange(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
function changed() {
  listeners.forEach((fn) => fn());
}

let offline = false;
export function isOffline(): boolean {
  return offline;
}
export function setOffline(v: boolean): void {
  if (offline !== v) {
    offline = v;
    changed();
  }
}

// --------------------------------------------------------------- outbox
export function waiting(): Waiting[] {
  return read<Waiting[]>(OUTBOX, []);
}
export function failed(): Waiting[] {
  return read<Waiting[]>(FAILED, []);
}
export function hold(method: string, path: string, body: unknown, label: string, id = newKey()): void {
  write(OUTBOX, [...waiting(), { id, method, path, body, label, at: new Date().toISOString() }]);
  changed();
}
export function dismissFailed(id: string): void {
  write(FAILED, failed().filter((f) => f.id !== id));
  changed();
}

/** Saves belong to whoever made them. Someone else signing in on this phone doesn't send them as their own. */
export function claimFor(userId: number): void {
  let owner: string | null = null;
  try {
    owner = localStorage.getItem(OWNER);
  } catch {
    return;
  }
  if (owner && owner !== String(userId)) forgetAll();
  try {
    localStorage.setItem(OWNER, String(userId));
  } catch {
    /* fine */
  }
}

type Sender = (w: Waiting) => Promise<{ ok: boolean; status: number; message: string }>;
let retryTimer = 0;
let sending = false;

/** Sends what's waiting, oldest first. Stops at the first sign the signal is still gone. */
export async function flush(send: Sender): Promise<void> {
  if (sending) return;
  sending = true;
  try {
    for (;;) {
      const [next] = waiting();
      if (!next) break;
      let r;
      try {
        r = await send(next);
      } catch {
        setOffline(true);
        break; // still no signal: try again later, in the same order
      }
      setOffline(false);
      if (r.status === 401) break; // signed out: keep it until they sign back in
      if (r.status >= 500 || r.status === 429) {
        // The server had a moment (a deploy, a first try still running): keep it, in order, and try again soon.
        window.clearTimeout(retryTimer);
        retryTimer = window.setTimeout(() => void flush(send), 15000);
        break;
      }
      write(OUTBOX, waiting().filter((w) => w.id !== next.id));
      if (!r.ok) write(FAILED, [...failed(), { ...next, error: r.message }]);
      changed();
    }
  } finally {
    sending = false;
  }
}

// ---------------------------------------------------------------- reads
export function cacheable(path: string): boolean {
  return CACHEABLE.some((re) => re.test(path));
}
export function remember(path: string, data: unknown): void {
  const all = read<Record<string, { at: number; data: unknown }>>(CACHE, {});
  all[path] = { at: Date.now(), data };
  const keys = Object.keys(all).sort((a, b) => all[b].at - all[a].at);
  for (const k of keys.slice(CACHE_MAX)) delete all[k];
  write(CACHE, all);
}
export function recall<T>(path: string): T | undefined {
  return read<Record<string, { at: number; data: T }>>(CACHE, {})[path]?.data;
}
export function forgetAll(): void {
  try {
    localStorage.removeItem(CACHE);
    localStorage.removeItem(OUTBOX);
    localStorage.removeItem(FAILED);
    localStorage.removeItem(OWNER);
  } catch {
    /* nothing to do */
  }
}

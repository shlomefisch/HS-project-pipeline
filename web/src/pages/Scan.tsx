import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { go, useLoad } from "../state";
import { ErrorLine, Field, Loading, useAction } from "../ui";
import type { Item, Job, JobSummary } from "../types";
import { AddTile } from "./JobSelection";

interface Resolved {
  netsuite_id: number;
  found: boolean;
  item: Item | null;
}

declare global {
  interface Window {
    BarcodeDetector?: new (o: { formats: string[] }) => { detect: (src: CanvasImageSource) => Promise<{ rawValue: string }[]> };
  }
}

/** Point at the tag; the item lands on the job's list. Works even if the item isn't synced yet. */
export function Scan({ jobId }: { jobId: number | null }) {
  const [scanned, setScanned] = useState<Resolved | null>(null);
  const [pickedJob, setPickedJob] = useState<number | null>(jobId);
  const { error, run } = useAction();

  const resolve = (code: string) =>
    run(async () => {
      const r = await api.get<Resolved>("/items/resolve", { code });
      setScanned(r);
    });

  return (
    <main className="page">
      <header className="page-head">
        <h1>Scan a tag</h1>
      </header>
      {!scanned ? (
        <>
          <Camera onCode={resolve} />
          <ManualCode onCode={resolve} />
          <ErrorLine error={error} />
        </>
      ) : (
        <>
          <p className="picked">
            <strong>{scanned.item?.name ?? `Item #${scanned.netsuite_id}`}</strong>
            <span className="muted">{scanned.found ? [scanned.item?.sku, scanned.item?.size].filter(Boolean).join(", ") : "Not in the item list yet — it's saved with the number, the name fills in later."}</span>
          </p>
          <button className="btn btn-quiet" onClick={() => setScanned(null)}>
            Scan another
          </button>
          {pickedJob ? (
            <ScanIntoJob jobId={pickedJob} scanned={scanned} onDone={() => go(`jobs/${pickedJob}`)} onCancel={() => setScanned(null)} />
          ) : (
            <PickJob onPick={setPickedJob} />
          )}
        </>
      )}
    </main>
  );
}

function ScanIntoJob({ jobId, scanned, onDone, onCancel }: { jobId: number; scanned: Resolved; onDone: () => void; onCancel: () => void }) {
  const { data: job, error } = useLoad(() => api.get<Job>(`/jobs/${jobId}`), [jobId]);
  if (!job) return <Loading error={error} />;
  return <AddTile job={job} scanned={{ id: scanned.netsuite_id, item: scanned.item }} onClose={onCancel} onDone={onDone} />;
}

function PickJob({ onPick }: { onPick: (id: number) => void }) {
  const { data, error } = useLoad(() => api.get<JobSummary[]>("/jobs", { mine: 1, status: "active" }), []);
  if (!data) return <Loading error={error} />;
  return (
    <section className="section">
      <h2>Add it to which job?</h2>
      <ul className="list">
        {data.map((j) => (
          <li key={j.id}>
            <button className="row-btn" onClick={() => onPick(j.id)}>
              <strong>{j.name}</strong>
              <span className="muted">{j.default_contact?.name ?? ""}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Camera({ onCode }: { onCode: (code: string) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<"starting" | "on" | "unsupported" | "denied">("starting");
  // Keep the latest callback without restarting the camera on every render.
  const handler = useRef(onCode);
  handler.current = onCode;

  useEffect(() => {
    if (!window.BarcodeDetector || !navigator.mediaDevices?.getUserMedia) {
      setState("unsupported");
      return;
    }
    const detector = new window.BarcodeDetector({ formats: ["qr_code"] });
    let stream: MediaStream | null = null;
    let stopped = false;
    let timer = 0;
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "environment" } })
      .then(async (s) => {
        stream = s;
        if (!video.current || stopped) return;
        video.current.srcObject = s;
        await video.current.play();
        setState("on");
        const tick = async () => {
          if (stopped || !video.current) return;
          try {
            const codes = await detector.detect(video.current);
            if (codes[0]?.rawValue) {
              stopped = true;
              navigator.vibrate?.(60);
              handler.current(codes[0].rawValue);
              return;
            }
          } catch {
            /* frame not ready */
          }
          timer = window.setTimeout(tick, 250);
        };
        tick();
      })
      .catch(() => setState("denied"));
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  if (state === "unsupported") return <p className="muted">This browser can't scan. Use Chrome on Android, or type the code below.</p>;
  if (state === "denied") return <p className="muted">The camera is blocked. Allow camera access for this app, or type the code below.</p>;
  return (
    <div className="camera">
      <video ref={video} playsInline muted aria-label="Camera" />
      <div className="camera-frame" aria-hidden="true" />
      {state === "starting" && <p className="muted">Starting the camera…</p>}
    </div>
  );
}

function ManualCode({ onCode }: { onCode: (code: string) => void }) {
  const [code, setCode] = useState("");
  return (
    <form
      className="manual-code"
      onSubmit={(e) => {
        e.preventDefault();
        if (code.trim()) onCode(code);
      }}
    >
      <Field label="Or type the item number or tag link">
        <div className="inline">
          <input inputMode="url" value={code} onChange={(e) => setCode(e.target.value)} placeholder="100101" />
          <button className="btn">Look up</button>
        </div>
      </Field>
    </form>
  );
}

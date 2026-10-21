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
  const [attempt, setAttempt] = useState(0);
  const { error, run } = useAction();

  const resolve = (code: string) =>
    run(async () => {
      try {
        const r = await api.get<Resolved>("/items/resolve", { code });
        setScanned(r);
      } finally {
        setAttempt((n) => n + 1); // the camera stops on a read; a miss starts it again
      }
    });

  return (
    <main className="page">
      <header className="page-head">
        <h1>Scan a tag</h1>
      </header>
      {!scanned ? (
        <>
          <Camera key={attempt} onCode={resolve} />
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

type Track = MediaStreamTrack;
type Caps = { zoom?: { min: number; max: number }; torch?: boolean; focusMode?: string[] };
const capsOf = (t: Track): Caps => (t.getCapabilities ? (t.getCapabilities() as unknown as Caps) : {});

/** Phones have several back cameras; the main one (Android names it "camera2 0" / "camera 0") focuses best. */
const mainBack = (all: MediaDeviceInfo[]) => {
  const back = all.filter((d) => d.kind === "videoinput" && /back|rear|environment/i.test(d.label));
  return back.find((d) => /\b(camera2? )?0\b/.test(d.label)) ?? back[0] ?? null;
};

function Camera({ onCode }: { onCode: (code: string) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<"starting" | "on" | "unsupported" | "denied">("starting");
  const [track, setTrack] = useState<Track | null>(null);
  const [torch, setTorch] = useState<boolean | null>(null);
  // Keep the latest callback without restarting the camera on every render.
  const handler = useRef(onCode);
  handler.current = onCode;

  useEffect(() => {
    if (!window.BarcodeDetector || !navigator.mediaDevices?.getUserMedia) {
      setState("unsupported");
      return;
    }
    const detector = new window.BarcodeDetector({ formats: ["qr_code"] });
    const crop = document.createElement("canvas");
    const ctx = crop.getContext("2d", { willReadFrequently: true });
    let stream: MediaStream | null = null;
    let stopped = false;
    let timer = 0;
    let frame = 0;
    const size = { width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 30 } };
    const open = (id?: string) =>
      navigator.mediaDevices.getUserMedia({ audio: false, video: id ? { deviceId: { exact: id }, ...size } : { facingMode: { ideal: "environment" }, ...size } });

    (async () => {
      let s = await open();
      // Camera names only show once it's allowed. If the browser picked a side camera, move to the main one.
      const main = mainBack(await navigator.mediaDevices.enumerateDevices().catch(() => []));
      if (main && s.getVideoTracks()[0]?.getSettings().deviceId !== main.deviceId) {
        s.getTracks().forEach((t) => t.stop());
        s = await open(main.deviceId).catch(() => open());
      }
      stream = s;
      if (!video.current || stopped) {
        s.getTracks().forEach((t) => t.stop());
        return;
      }
      const t = s.getVideoTracks()[0] as Track;
      const caps = capsOf(t);
      if (caps.focusMode?.includes("continuous")) await t.applyConstraints({ advanced: [{ focusMode: "continuous" } as MediaTrackConstraintSet] }).catch(() => {});
      if (caps.torch) setTorch(false);
      setTrack(t);
      video.current.srcObject = s;
      await video.current.play();
      setState("on");
      const tick = async () => {
        const v = video.current;
        if (stopped || !v) return;
        try {
          let source: CanvasImageSource = v;
          // Every other look, just the middle at full detail: a small code from further back still reads.
          if (ctx && v.videoWidth && frame++ % 2 === 0) {
            const side = Math.round(Math.min(v.videoWidth, v.videoHeight) * 0.5);
            crop.width = crop.height = side;
            ctx.drawImage(v, (v.videoWidth - side) / 2, (v.videoHeight - side) / 2, side, side, 0, 0, side, side);
            source = crop;
          }
          const codes = await detector.detect(source);
          if (codes[0]?.rawValue) {
            stopped = true;
            navigator.vibrate?.(60);
            handler.current(codes[0].rawValue);
            return;
          }
        } catch {
          /* frame not ready */
        }
        timer = window.setTimeout(tick, 100);
      };
      tick();
    })().catch(() => setState("denied"));
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const flipTorch = () => {
    if (!track || torch === null) return;
    track.applyConstraints({ advanced: [{ torch: !torch } as MediaTrackConstraintSet] }).catch(() => {});
    setTorch(!torch);
  };

  if (state === "unsupported")
    return (
      <p className="muted scan-desk-hint">
        No camera scanning here. With a USB scanner, just scan the tag — it lands in the box below and looks itself up. Or type the item number.
      </p>
    );
  if (state === "denied") return <p className="muted">The camera is blocked. Allow camera access for this app, or type the code below.</p>;
  return (
    <>
      <div className="camera">
        <video ref={video} playsInline muted aria-label="Camera" />
        <div className="camera-frame" aria-hidden="true" />
        {torch !== null && (
          <button type="button" className={`camera-light ${torch ? "camera-light-on" : ""}`} onClick={flipTorch} aria-pressed={torch}>
            {torch ? "Light off" : "Light"}
          </button>
        )}
        {state === "starting" && <p className="muted">Starting the camera…</p>}
      </div>
      <p className="muted small camera-tip">Stay back about a foot — the code can be small in the box. Close up, the camera can't focus.</p>
    </>
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
      <Field label="Scan with a USB scanner, or type the item number or tag link">
        <div className="inline">
          <input autoFocus inputMode="url" value={code} onChange={(e) => setCode(e.target.value)} />
          <button className="btn">Look up</button>
        </div>
      </Field>
    </form>
  );
}

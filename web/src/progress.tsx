import type { Progress } from "./types";

/** How far along a job is: one tile per stage, glazed in as the job moves on. */
export function ProgressTiles({ progress, size = "small" }: { progress?: Progress | null; size?: "small" | "large" }) {
  if (!progress) return null;
  const n = progress.done;
  return (
    <div className={`progress progress-${size}`} role="img" aria-label={`${n} of ${progress.stages.length} stages done — now at ${progress.current}`}>
      <div className="progress-tiles">
        {progress.stages.map((s, i) => (
          <span key={s.key} className={`ptile ${s.done ? "ptile-done" : i === n ? "ptile-now" : ""}`} title={s.label}>
            {size === "large" && <span className="ptile-label">{s.label}</span>}
          </span>
        ))}
      </div>
      {size === "small" && <span className="progress-now">{n >= progress.stages.length ? "Ordered" : progress.current}</span>}
      {size === "large" && (
        <span className="progress-caption">
          {n >= progress.stages.length ? "Ordered — all stages done" : `Now: ${progress.current} · ${n} of ${progress.stages.length} done`}
        </span>
      )}
    </div>
  );
}

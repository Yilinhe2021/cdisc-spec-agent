import { useEffect, useRef, useState } from "react";
import type { TraceEvent } from "../types";

export function FileInput({ label, hint, multiple, accept, files, onChange }: {
  label: string; hint?: string; multiple?: boolean; accept?: string; files: File[]; onChange: (f: File[]) => void;
}) {
  const [over, setOver] = useState(false);
  return (
    <label className={`drop ${over ? "over" : ""} ${files.length ? "has" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); onChange(Array.from(e.dataTransfer.files)); }}>
      <input type="file" multiple={multiple} accept={accept} onChange={(e) => onChange(Array.from(e.target.files ?? []))} />
      <span className="drop-label">{label}</span>
      <span className="drop-hint">{files.length ? files.map((f) => f.name).join(", ") : hint ?? "drop file or click"}</span>
    </label>
  );
}

const KIND_ICON: Record<string, string> = { start: "▶", done: "✓", error: "✕", warning: "!", llm: "✦", tool: "⚙", result: "●", info: "·" };

export function TracePanel({ events, running }: { events: TraceEvent[]; running: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.scrollTo({ top: ref.current.scrollHeight }); }, [events.length]);
  return (
    <div className="card trace">
      <div className="card-head">
        <h3>Agent trace</h3>
        {running && <span className="spinner" aria-label="running" />}
      </div>
      <div className="trace-body" ref={ref}>
        {events.length === 0 && <div className="muted">Agents will report here while they work.</div>}
        {events.map((e, i) => (
          <div key={i} className={`ev ev-${e.kind}`}>
            <span className="ev-icon">{KIND_ICON[e.kind] ?? "·"}</span>
            <span className="ev-agent">{e.agent}</span>
            <span className="ev-msg">{e.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Stat({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  return (
    <div className={`stat ${tone ?? ""}`}>
      <div className="stat-v">{value}</div>
      <div className="stat-l">{label}</div>
    </div>
  );
}

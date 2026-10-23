import { Fragment, useMemo, useState } from "react";
import { decide, getJob, post, streamEvents } from "../api";
import type { Finding, QCResult, Standard, TraceEvent } from "../types";
import { FileInput, Stat, TracePanel } from "./common";

const SEVS = ["critical", "major", "minor", "info"] as const;

export default function QCPage({ standard, onNext }: { standard: Standard; onNext: () => void }) {
  const [spec, setSpec] = useState<File[]>([]);
  const [docs, setDocs] = useState<File[]>([]);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<QCResult | null>(null);
  const [jobId, setJobId] = useState("");

  async function start(demo: boolean) {
    setError(""); setResult(null); setEvents([]); setRunning(true);
    try {
      const form = new FormData();
      form.append("standard", standard);
      if (!demo) {
        form.append("spec", spec[0]);
        docs.forEach((d) => form.append("documents", d));
      }
      const { job_id } = await post(demo ? "/api/qc/demo" : "/api/qc", form);
      setJobId(job_id);
      await streamEvents(job_id, (e) => setEvents((x) => [...x, e]));
      const job = await getJob<QCResult>(job_id);
      if (job.status === "error") setError(job.error);
      setResult(job.result);
      setEvents((x) => (x.length ? x : job.events));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="page">
      <section className="card intake">
        <div className="card-head"><h2>Spec QC · {standard}</h2></div>
        <p className="muted">Upload a dataset specification (xlsx with Datasets / Variables / Codelists sheets, or a
          variable-level CSV). Rule engine + three LLM reviewers + a judge agent return a ranked list of rows that are
          wrong or unclear, each with a comment and evidence.</p>
        <div className="row">
          <FileInput label="Specification" hint=".xlsx or .csv" accept=".xlsx,.xlsm,.csv" files={spec} onChange={setSpec} />
          <FileInput label="Study documents (optional)" hint="SAP / protocol excerpts as .md or .txt — indexed for RAG"
            multiple accept=".md,.txt" files={docs} onChange={setDocs} />
        </div>
        <div className="actions">
          <button className="primary" disabled={!spec.length || running} onClick={() => start(false)}>Run QC</button>
          <button disabled={running} onClick={() => start(true)}>Try the synthetic demo spec</button>
          {error && <span className="err">{error}</span>}
        </div>
      </section>

      <div className="grid2">
        <TracePanel events={events} running={running} />
        {result ? <Summary r={result} jobId={jobId} onNext={onNext} /> :
          <div className="card placeholder muted">Results appear here.</div>}
      </div>

      {result && <FindingsTable jobId={jobId} findings={result.findings} onChange={(f) =>
        setResult({ ...result, findings: result.findings.map((x) => (x.id === f.id ? f : x)) })} />}
    </div>
  );
}

function Summary({ r, jobId, onNext }: { r: QCResult; jobId: string; onNext: () => void }) {
  const s = r.summary;
  return (
    <div className="card">
      <div className="card-head"><h3>Summary</h3><span className="muted small">{r.spec_name}</span></div>
      <div className="stats">
        <Stat label="findings" value={s.total} />
        <Stat label="rows flagged" value={s.rows_flagged} />
        {SEVS.map((k) => <Stat key={k} label={k} value={s.by_severity[k] ?? 0} tone={k} />)}
      </div>
      <div className="kv">
        <div><span>by agent</span>{Object.entries(s.by_agent).map(([k, v]) => <code key={k}>{k} {v}</code>)}</div>
        <div><span>by category</span>{Object.entries(s.by_category).map(([k, v]) => <code key={k}>{k} {v}</code>)}</div>
        <div><span>LLM</span><code>{s.llm.provider} / {s.llm.model} · {s.llm.calls} calls</code></div>
      </div>
      {r.coverage.some((c) => c.gap) && (
        <div className="gaps">
          <b>Not checked:</b> {r.coverage.filter((c) => c.gap).map((c) => c.gap).join(" ")}
        </div>
      )}
      <div className="actions">
        <a className="button primary" href={`/api/qc/${jobId}/annotated.xlsx`}>Download annotated spec (.xlsx)</a>
        <button onClick={onNext}>Spec updated → go to Build</button>
      </div>
    </div>
  );
}

function FindingsTable({ jobId, findings, onChange }: { jobId: string; findings: Finding[]; onChange: (f: Finding) => void }) {
  const [sev, setSev] = useState<string>("all");
  const [q, setQ] = useState("");
  const [showDismissed, setShowDismissed] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  const rows = useMemo(() => findings.filter((f) =>
    (sev === "all" || f.severity === sev) && (showDismissed || f.status !== "dismissed") &&
    (!q || `${f.dataset} ${f.variable} ${f.message} ${f.rule_id}`.toLowerCase().includes(q.toLowerCase()))), [findings, sev, q, showDismissed]);

  async function mark(f: Finding, decision: Finding["status"]) {
    const next = f.status === decision ? "open" : decision;
    await decide(jobId, f.id, next);
    onChange({ ...f, status: next });
  }

  return (
    <section className="card">
      <div className="card-head">
        <h3>Findings <span className="muted">({rows.length})</span></h3>
        <div className="filters">
          <select value={sev} onChange={(e) => setSev(e.target.value)}>
            <option value="all">all severities</option>
            {SEVS.map((s) => <option key={s}>{s}</option>)}
          </select>
          <input placeholder="search dataset, variable, text…" value={q} onChange={(e) => setQ(e.target.value)} />
          <label className="chk"><input type="checkbox" checked={showDismissed} onChange={(e) => setShowDismissed(e.target.checked)} /> show dismissed</label>
        </div>
      </div>
      <div className="table-wrap">
        <table className="findings">
          <thead>
            <tr><th>Sev</th><th>Target</th><th>Row</th><th>Finding / comment</th><th>Source</th><th>Conf.</th><th>Review</th></tr>
          </thead>
          <tbody>
            {rows.map((f) => (
              <Fragment key={f.id}>
                <tr className={`st-${f.status}`} onClick={() => setOpen(open === f.id ? null : f.id)}>
                  <td><span className={`sev ${f.severity}`}>{f.severity}</span></td>
                  <td className="mono">{f.dataset}{f.variable && <>.<b>{f.variable}</b></>}</td>
                  <td className="mono muted">{f.row ?? "–"}</td>
                  <td>
                    <div>{f.message}</div>
                    {f.suggestion && <div className="sugg">→ {f.suggestion}</div>}
                  </td>
                  <td className="small">
                    <div className="mono">{f.rule_id}</div>
                    <div className="muted">{[f.agent, ...f.merged_from.map((m) => m.split(":")[0])].filter((v, i, a) => a.indexOf(v) === i).join(" + ")}</div>
                  </td>
                  <td><div className="conf"><div style={{ width: `${Math.round(f.confidence * 100)}%` }} /></div></td>
                  <td className="review" onClick={(e) => e.stopPropagation()}>
                    <button title="Accept: real issue" className={f.status === "accepted" ? "ok on" : "ok"} onClick={() => mark(f, "accepted")}>✓</button>
                    <button title="Dismiss: not an issue (teaches the judge)" className={f.status === "dismissed" ? "no on" : "no"} onClick={() => mark(f, "dismissed")}>✕</button>
                  </td>
                </tr>
                {open === f.id && (
                  <tr className="evidence"><td colSpan={7}>
                    <b>{f.category}</b> · evidence retrieved by RAG:
                    {f.evidence.length === 0 && <span className="muted"> none</span>}
                    {f.evidence.map((e, i) => (
                      <blockquote key={i}><span className="mono">{e.source} › {e.section}</span><br />{e.snippet}…</blockquote>
                    ))}
                  </td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

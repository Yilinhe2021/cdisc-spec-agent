import { useState } from "react";
import { getJob, post, streamEvents } from "../api";
import type { BuildResult, DatasetBuild, Standard, TraceEvent } from "../types";
import { FileInput, Stat, TracePanel } from "./common";

export default function BuildPage({ standard }: { standard: Standard }) {
  const [spec, setSpec] = useState<File[]>([]);
  const [data, setData] = useState<File[]>([]);
  const [refs, setRefs] = useState<File[]>([]);
  const [targets, setTargets] = useState("");
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<BuildResult | null>(null);

  async function start(demo: boolean) {
    setError(""); setResult(null); setEvents([]); setRunning(true);
    try {
      const form = new FormData();
      form.append("standard", standard);
      if (!demo) {
        form.append("spec", spec[0]);
        data.forEach((f) => form.append("data", f));
        refs.forEach((f) => form.append("references", f));
        form.append("targets", targets);
      }
      const { job_id } = await post(demo ? "/api/build/demo" : "/api/build", form);
      await streamEvents(job_id, (e) => setEvents((x) => [...x, e]));
      const job = await getJob<BuildResult>(job_id);
      if (job.status === "error") setError(job.error);
      setResult(job.result);
      setEvents((x) => (x.length ? x : job.events));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setRunning(false);
    }
  }

  const source = standard === "SDTM" ? "raw / EDC extracts" : "SDTM datasets (and ADaM dependencies)";
  return (
    <div className="page">
      <section className="card intake">
        <div className="card-head"><h2>Build · {standard}</h2></div>
        <p className="muted">Upload the reviewed spec and the source tables ({source}; file name = table name, e.g.
          <code>RAW_DM.csv</code>). The planner orders datasets by dependency; for each one a coder writes a Python program,
          the executor runs it in a sandbox, the validator checks it against the spec and a repairer fixes build bugs.</p>
        <div className="row three">
          <FileInput label="Reviewed specification" hint=".xlsx or .csv" accept=".xlsx,.xlsm,.csv" files={spec} onChange={setSpec} />
          <FileInput label="Source data" hint=".csv / .xlsx / .sas7bdat / .xpt (multiple)" multiple files={data} onChange={setData} />
          <FileInput label="Reference datasets (optional)" hint="blinded: only the validator sees them" multiple files={refs} onChange={setRefs} />
        </div>
        <div className="actions">
          <input className="targets" placeholder="datasets to build (default: all), e.g. DM, AE" value={targets} onChange={(e) => setTargets(e.target.value)} />
          <button className="primary" disabled={!spec.length || !data.length || running} onClick={() => start(false)}>Build</button>
          <button disabled={running} onClick={() => start(true)}>Try the synthetic demo study</button>
          <a className="button" href={`/api/examples/${standard}/build`}>Download sample inputs (.zip)</a>
          {error && <span className="err">{error}</span>}
        </div>
      </section>

      <div className="grid2">
        <TracePanel events={events} running={running} />
        {result ? <Plan r={result} /> : <div className="card placeholder muted">Plan and outputs appear here.</div>}
      </div>

      {result?.datasets.map((d) => <DatasetCard key={d.dataset} d={d} />)}
    </div>
  );
}

function Plan({ r }: { r: BuildResult }) {
  const levels = Array.from(new Set(r.plan.map((p) => p.level))).sort();
  return (
    <div className="card">
      <div className="card-head">
        <h3>Build plan</h3>
        <a className="button primary" href={`/api/build/${r.job_id}/download.zip`}>Download programs + datasets (.zip)</a>
      </div>
      <div className="plan">
        {levels.map((l, i) => (
          <div key={l} className="plan-level">
            {i > 0 && <span className="arrow">→</span>}
            {r.plan.filter((p) => p.level === l).map((p) => {
              const d = r.datasets.find((x) => x.dataset === p.dataset);
              return (
                <div key={p.dataset} className={`plan-node ${d?.status ?? p.status}`}>
                  <b>{p.dataset}</b>
                  <small>from {p.base || "?"}{p.needs.length ? ` + ${p.needs.join(", ")}` : ""}</small>
                  {p.missing.length > 0 && <small className="err">missing {p.missing.join(", ")}</small>}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

function DatasetCard({ d }: { d: DatasetBuild }) {
  const [tab, setTab] = useState<"preview" | "program" | "validation" | "concordance">(d.concordance ? "concordance" : "preview");
  const c = d.concordance;
  return (
    <section className="card">
      <div className="card-head">
        <h3><span className={`badge ${d.status}`}>{d.status}</span> {d.dataset}</h3>
        <div className="stats inline">
          <Stat label="rows" value={d.rows} />
          <Stat label="columns" value={d.columns.length} />
          <Stat label="attempts" value={d.attempts} />
          <Stat label="issues" value={d.issues.length} tone={d.issues.length ? "major" : ""} />
          {c && <Stat label="reference match" value={`${c.concordance_pct}%`} tone={c.concordance_pct === 100 ? "ok" : "minor"} />}
        </div>
      </div>
      <div className="tabs">
        {(["preview", "program", "validation", "concordance"] as const).filter((t) => t !== "concordance" || c).map((t) => (
          <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      {tab === "program" && <pre className="code">{d.program}</pre>}
      {tab === "preview" && (
        <div className="table-wrap">
          <table className="preview">
            <thead><tr>{d.columns.map((col) => <th key={col}>{col}</th>)}</tr></thead>
            <tbody>{d.preview.map((r, i) => <tr key={i}>{d.columns.map((col) => <td key={col}>{fmt(r[col])}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}
      {tab === "validation" && (d.issues.length === 0 ? <p className="ok-text">No issues: output conforms to the spec.</p> : (
        <table className="issues">
          <thead><tr><th>Class</th><th>Check</th><th>Variable</th><th>Message</th><th>Examples</th></tr></thead>
          <tbody>{d.issues.map((i, k) => (
            <tr key={k}><td><span className={`cls ${i.class}`}>{i.class}</span></td><td>{i.check}</td><td className="mono">{i.variable}</td>
              <td>{i.message}</td><td className="mono small">{i.examples.slice(0, 3).join(" | ")}</td></tr>
          ))}</tbody>
        </table>
      ))}
      {tab === "concordance" && c && (
        <div>
          <p className="muted">{c.cells_equal.toLocaleString()} / {c.cells.toLocaleString()} cells equal across {c.matched_rows} rows matched on {c.keys.join(", ") || "row order"}
            {c.rows_only_in_generated + c.rows_only_in_reference > 0 && ` · unmatched rows: ${c.rows_only_in_generated} generated, ${c.rows_only_in_reference} reference`}
            {c.columns_missing.length > 0 && ` · missing columns: ${c.columns_missing.join(", ")}`}</p>
          <div className="bars">
            {Object.entries(c.per_variable).map(([v, pct]) => (
              <div key={v} className="bar-row"><span className="mono">{v}</span>
                <div className="bar"><div className={pct === 100 ? "full" : "part"} style={{ width: `${pct}%` }} /></div>
                <span className="mono small">{pct}%</span></div>
            ))}
          </div>
          {c.mismatch_examples.length > 0 && (
            <table className="issues"><thead><tr><th>Key</th><th>Variable</th><th>Generated</th><th>Reference</th></tr></thead>
              <tbody>{c.mismatch_examples.map((m, k) => <tr key={k}><td className="mono small">{m.key}</td><td className="mono">{m.variable}</td><td>{m.generated}</td><td>{m.reference}</td></tr>)}</tbody>
            </table>
          )}
        </div>
      )}
    </section>
  );
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T00:00:00/.test(v)) return v.slice(0, 10);
  return String(v);
}

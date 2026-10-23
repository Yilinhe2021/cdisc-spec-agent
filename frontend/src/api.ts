import type { Job, TraceEvent } from "./types";

export async function post(url: string, form: FormData): Promise<{ job_id: string }> {
  const r = await fetch(url, { method: "POST", body: form });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText);
  return r.json();
}

export async function getJob<T>(id: string): Promise<Job<T>> {
  const r = await fetch(`/api/jobs/${id}`);
  if (!r.ok) throw new Error(r.statusText);
  return r.json();
}

/** Stream agent trace events; resolves when the job ends. */
export function streamEvents(id: string, onEvent: (e: TraceEvent) => void): Promise<void> {
  return new Promise((resolve) => {
    const es = new EventSource(`/api/jobs/${id}/events`);
    es.onmessage = (m) => onEvent(JSON.parse(m.data));
    es.addEventListener("end", () => { es.close(); resolve(); });
    es.onerror = () => { es.close(); resolve(); };
  });
}

export async function decide(job: string, finding: string, decision: string) {
  await fetch(`/api/qc/${job}/findings/${finding}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision }),
  });
}

export async function health(): Promise<{ llm: string; model: string; offline: boolean }> {
  return (await fetch("/api/health")).json();
}

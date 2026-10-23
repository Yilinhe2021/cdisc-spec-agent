export type Standard = "SDTM" | "ADaM";
export type Severity = "critical" | "major" | "minor" | "info";

export interface Citation { source: string; section: string; snippet: string; score?: number | null }
export interface Finding {
  id: string; rule_id: string; agent: string; dataset: string; variable: string; row: number | null;
  severity: Severity; category: string; message: string; suggestion: string; evidence: Citation[];
  confidence: number; status: "open" | "accepted" | "dismissed"; merged_from: string[];
}
export interface QCResult {
  job_id: string; standard: Standard; spec_name: string; findings: Finding[];
  summary: { total: number; by_severity: Record<string, number>; by_category: Record<string, number>;
    by_agent: Record<string, number>; rows_flagged: number; profile: Record<string, unknown>;
    llm: { provider: string; model: string; calls: number } };
  coverage: Record<string, string>[];
}
export interface TraceEvent { ts: string; agent: string; kind: string; message: string; data: Record<string, unknown> }
export interface Issue { check: string; class: string; severity: string; variable: string; message: string; count: number; examples: string[] }
export interface Concordance {
  keys: string[]; concordance_pct: number; cells: number; cells_equal: number; matched_rows: number;
  rows_only_in_generated: number; rows_only_in_reference: number; columns_missing: string[];
  per_variable: Record<string, number>;
  mismatch_examples: { key: string; variable: string; generated: string; reference: string }[];
}
export interface DatasetBuild {
  dataset: string; program: string; attempts: number; status: "pending" | "ok" | "warnings" | "failed";
  rows: number; columns: string[]; preview: Record<string, unknown>[]; issues: Issue[]; concordance: Concordance | null;
}
export interface PlanItem { dataset: string; base: string; needs: string[]; inputs: string[]; missing: string[]; status: string; level: number }
export interface BuildResult { job_id: string; standard: Standard; plan: PlanItem[]; datasets: DatasetBuild[] }
export interface Job<T> { id: string; kind: string; status: string; error: string; result: T | null; events: TraceEvent[] }

import { useEffect, useState } from "react";
import { health } from "./api";
import QCPage from "./components/QCPage";
import BuildPage from "./components/BuildPage";
import type { Standard } from "./types";

type Tab = "qc" | "build";

export default function App() {
  const [tab, setTab] = useState<Tab>("qc");
  const [standard, setStandard] = useState<Standard>("SDTM");
  const [llm, setLlm] = useState<{ llm: string; model: string; offline: boolean } | null>(null);

  useEffect(() => { health().then(setLlm).catch(() => setLlm(null)); }, []);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">◆</span> SpecForge
          <span className="tagline">multi-agent spec QC &amp; dataset generation</span>
        </div>
        <div className="seg" role="tablist" aria-label="Standard">
          {(["SDTM", "ADaM"] as Standard[]).map((s) => (
            <button key={s} className={standard === s ? "on" : ""} onClick={() => setStandard(s)}>{s}</button>
          ))}
        </div>
        <div className={`llm-pill ${llm?.offline ? "offline" : ""}`} title={llm ? `${llm.llm} / ${llm.model}` : "backend not reachable"}>
          {llm ? (llm.offline ? "offline heuristics" : `${llm.llm} · ${llm.model}`) : "backend offline"}
        </div>
      </header>

      <nav className="steps">
        <button className={tab === "qc" ? "on" : ""} onClick={() => setTab("qc")}>
          <b>1</b> Spec QC <small>find unclear / wrong rows</small>
        </button>
        <span className="arrow">→</span>
        <button className={tab === "build" ? "on" : ""} onClick={() => setTab("build")}>
          <b>2</b> Build <small>spec + data → programs + datasets</small>
        </button>
      </nav>

      <main>
        <div hidden={tab !== "qc"}><QCPage standard={standard} onNext={() => setTab("build")} /></div>
        <div hidden={tab !== "build"}><BuildPage standard={standard} /></div>
      </main>
      <footer>Synthetic demo data only · findings are AI-assisted suggestions for a human reviewer, not verdicts.</footer>
    </div>
  );
}

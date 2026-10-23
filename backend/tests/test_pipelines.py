import json

from specforge.build.compiler import compile_dataset
from specforge.build.pipeline import read_table, run_build
from specforge.llm import get_provider
from specforge.qc.pipeline import run_qc
from specforge.spec.parser import load_spec
from conftest import EX


async def test_qc_finds_seeded_defects():
    key = json.loads((EX / "answer_key.json").read_text())
    for std in ("SDTM", "ADaM"):
        res = await run_qc(load_spec(EX / std.lower() / "spec_draft.xlsx", std), get_provider("mock"))
        targets = {(f.dataset, f.variable) for f in res.findings} | {(f.dataset, "(dataset)") for f in res.findings}
        missed = [d for d in key[std] if (d["dataset"], d["variable"]) not in targets]
        assert not missed, missed
        assert all(f.evidence for f in res.findings if f.agent == "RuleEngine"), "rule findings must be grounded"


async def test_qc_clean_spec_is_quiet():
    res = await run_qc(load_spec(EX / "adam" / "spec_final.xlsx", "ADaM"), get_provider("mock"))
    assert res.findings == []


def test_compiler_covers_demo_vocabulary():
    spec = load_spec(EX / "sdtm" / "spec_final.xlsx", "SDTM")
    c = compile_dataset(spec, "AE", {"RAW_AE": ["STUDY", "SITE", "SUBJ"], "DM": ["USUBJID", "RFSTDTC"]})
    assert not c.unresolved and c.base == "RAW_AE" and "DM" in c.deps


async def test_build_matches_reference(tmp_path):
    for std, inp in (("SDTM", "raw"), ("ADaM", "inputs")):
        spec = load_spec(EX / std.lower() / "spec_final.xlsx", std)
        inputs = {f.stem.upper(): read_table(f) for f in (EX / std.lower() / inp).glob("*.csv")}
        refs = {f.stem.upper(): read_table(f) for f in (EX / std.lower() / "reference").glob("*.csv")}
        r = await run_build(spec, inputs, get_provider("mock"), tmp_path / std, references=refs)
        assert [p["dataset"] for p in r.plan] == spec.dataset_names()
        for d in r.datasets:
            assert d.status in ("ok", "warnings"), (d.dataset, d.issues)
            assert d.concordance["concordance_pct"] == 100.0, d.concordance["mismatch_examples"]


async def test_unknown_derivation_becomes_spec_gap(tmp_path):
    spec = load_spec(EX / "sdtm" / "spec_final.xlsx", "SDTM")
    spec.find("DM", "AGEU").derivation = "Use whatever unit the site prefers"
    inputs = {f.stem.upper(): read_table(f) for f in (EX / "sdtm" / "raw").glob("*.csv")}
    r = await run_build(spec, inputs, get_provider("mock"), tmp_path, targets=["DM"])
    dm = r.datasets[0]
    assert any(i["class"] == "SPEC_GAP" and i["variable"] == "AGEU" for i in dm.issues)
    assert "TODO(coder)" in dm.program


async def test_feedback_calibration_is_visible_and_never_hides_critical():
    from specforge.rag import feedback

    spec = load_spec(EX / "sdtm" / "spec_draft.xlsx", "SDTM")
    first = await run_qc(spec, get_provider("mock"))
    minor = next(f for f in first.findings if f.rule_id == "GEN-008")
    crit = next(f for f in first.findings if f.severity.value == "critical")

    feedback.record(minor, "dismissed")
    one = await run_qc(spec, get_provider("mock"))
    m1 = next(f for f in one.findings if f.rule_id == "GEN-008")
    assert m1.status == "open" and m1.confidence < 1.0          # one opinion only nudges

    for _ in range(5):
        feedback.record(minor, "dismissed")
        feedback.record(crit, "dismissed")
    later = await run_qc(spec, get_provider("mock"))
    m2 = next(f for f in later.findings if f.rule_id == "GEN-008")
    c2 = next(f for f in later.findings if f.rule_id == crit.rule_id and f.variable == crit.variable)
    assert m2.status == "dismissed" and "auto-dismissed" in m2.note   # demoted, still listed
    assert c2.status == "open"                                           # critical: humans only
    assert later.summary["auto_dismissed"] >= 1


def test_reads_windows_1252_extract():
    df = read_table(EX / "sdtm" / "raw" / "RAW_AE.csv")
    assert df.attrs["encoding"] == "cp1252"
    assert "Eczéma on forearm" in df["AETERM"].tolist()


def test_concordance_treats_nullable_na_as_missing():
    import pandas as pd

    from specforge.build.validate import compare_to_reference

    out = pd.DataFrame({"K": ["a", "b"], "AGE": pd.array([30, None], dtype="Float64")})
    ref = pd.DataFrame({"K": ["a", "b"], "AGE": ["30", ""]})
    assert compare_to_reference(out, ref, ["K"])["concordance_pct"] == 100.0

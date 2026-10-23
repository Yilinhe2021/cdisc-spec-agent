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


async def test_dismissed_feedback_lowers_confidence():
    from specforge.rag import feedback

    spec = load_spec(EX / "sdtm" / "spec_draft.xlsx", "SDTM")
    first = await run_qc(spec, get_provider("mock"))
    target = next(f for f in first.findings if f.rule_id == "GEN-008")
    for _ in range(3):
        feedback.record(target, "dismissed", "origin eCRF is our house convention")
    second = await run_qc(spec, get_provider("mock"))
    assert not any(f.rule_id == "GEN-008" for f in second.findings), "judge should suppress repeatedly dismissed pattern"


def test_missing_clause_wraps_condition():
    from specforge.models import Spec, SpecVariable

    spec = Spec(standard="ADaM", variables=[
        SpecVariable(row=2, dataset="ADSL", variable="USUBJID", type="Char", origin="Predecessor", derivation="DM.USUBJID"),
        SpecVariable(row=3, dataset="ADSL", variable="AGE", type="Num", origin="Predecessor", derivation="DM.AGE"),
        SpecVariable(row=4, dataset="ADSL", variable="AGEGR1", type="Char", origin="Derived",
                     derivation="Set to '<65' if AGE < 65, else '>=65'; missing if AGE is missing")])
    c = compile_dataset(spec, "ADSL", {"DM": ["USUBJID", "AGE"]})
    assert not c.unresolved and 'where(is_missing(df["AGE"]), None' in c.code

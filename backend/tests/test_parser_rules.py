import pandas as pd

from specforge.models import Spec, SpecVariable, CodelistTerm
from specforge.qc.rules import run_rules
from specforge.spec.parser import load_spec, parse_variables
from conftest import EX


def test_load_xlsx_spec():
    spec = load_spec(EX / "sdtm" / "spec_final.xlsx", "SDTM")
    assert spec.dataset_names() == ["DM", "AE"]
    assert spec.find("DM", "USUBJID").origin == "Derived"
    assert "SEX" in spec.codelists and spec.dataset("AE").keys == ["STUDYID", "USUBJID", "AESEQ"]


def test_column_aliases():
    df = pd.DataFrame({"Domain": ["DM"], "Variable Name": ["AGE"], "Variable Label": ["Age"], "Data Type": ["Num"],
                       "Mapping Rule": ["x"]})
    v = parse_variables(df)[0]
    assert (v.dataset, v.variable, v.label, v.type, v.derivation) == ("DM", "AGE", "Age", "Num", "x")


def _spec(*vars_, std="SDTM", cl=None):
    return Spec(standard=std, variables=[SpecVariable(row=i + 2, **v) for i, v in enumerate(vars_)], codelists=cl or {})


def ids(spec):
    return {f.rule_id for f in run_rules(spec)[0]}


def test_rules_fire():
    spec = _spec(
        dict(dataset="AE", variable="AESTDTC", label="x" * 45, type="Num", origin="CRF"),
        dict(dataset="AE", variable="AESER", label="Serious", type="Char", length=1, origin="Derived",
             derivation="Set to 'YES' if X = 'Yes', else 'N'", codelist="NY"),
        dict(dataset="AE", variable="TOOLONGNAME", label="a", type="Char", length=1, origin="Derived"),
        cl={"NY": [CodelistTerm(codelist="NY", code="Y"), CodelistTerm(codelist="NY", code="N")]},
    )
    got = ids(spec)
    assert {"GEN-004", "SDTM-002", "GEN-014", "GEN-002", "GEN-007", "SDTM-001"} <= got


def test_comparison_literal_is_not_assignment():
    spec = _spec(dict(dataset="ADSL", variable="ITTFL", label="ITT", type="Char", length=1, origin="Derived",
                      derivation="Set to 'Y' if ARMCD ne 'SCRNFAIL', else 'N'", codelist="NY"), std="ADaM",
                 cl={"NY": [CodelistTerm(codelist="NY", code="Y"), CodelistTerm(codelist="NY", code="N")]})
    assert "GEN-014" not in ids(spec)


def test_clean_specs_have_no_rule_hits():
    for std in ("SDTM", "ADaM"):
        assert run_rules(load_spec(EX / std.lower() / "spec_final.xlsx", std))[0] == []


def test_quote_problems():
    from specforge.qc.rules.common import quote_problems

    assert quote_problems("Set to 'Y' if AEOUT = 'Ongoing\"") != []          # mixed
    assert quote_problems("Set to 'Y' if AEOUT = 'Ongoing") != []            # never closed
    assert quote_problems("Set to ‘Y’") != []                       # curly
    assert quote_problems("Set to 'Y' if investigator's answer = \"Yes\"") == []
    assert quote_problems("Map RAW_DM.SEX using codelist SEX") == []

import pandas as pd

from specforge.rag.retriever import knowledge_base, tokenize
from specforge.runtime import stdlib as sl


def test_generic_variable_expansion():
    assert "--stdtc" in tokenize("AESTDTC")


def test_retrieval_hits_relevant_section():
    kb = knowledge_base()
    assert kb.search("label longer than 40 characters", k=1)[0].chunk.section == "Variable labels"
    assert kb.search("first dose tie breaker sort", k=1)[0].chunk.section == "Sort order and ties"


def test_iso_date_partial_and_formats():
    s = pd.Series(["05-MAR-2024", "UNK-MAR-2024", "2024-03-05", "", None, "03/05/2024"])
    assert sl.iso_date(s).tolist() == ["2024-03-05", "2024-03", "2024-03-05", "", "", "2024-03-05"]


def test_study_day_has_no_day_zero():
    d = sl.study_day(pd.Series(["2024-03-05", "2024-03-04", "2024-03", ""]), pd.Series(["2024-03-05"] * 4))
    assert d.tolist()[:2] == [1, -1] and d.isna().tolist()[2:] == [True, True]


def test_age_and_seq():
    assert sl.age_years(pd.Series(["1960-06-10"]), pd.Series(["2024-06-09"])).iloc[0] == 63
    df = pd.DataFrame({"U": ["a", "a", "b"], "D": ["2024-02", "2024-01", "2024-01"]})
    assert sl.seq_number(df, ["U"], ["D"]).tolist() == [2, 1, 1]


def test_map_codelist_strict():
    assert sl.map_codelist(pd.Series(["Male", "f"]), {"M": "Male", "F": "Female"}).tolist() == ["M", "F"]
    try:
        sl.map_codelist(pd.Series(["X"]), {"M": "Male"})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

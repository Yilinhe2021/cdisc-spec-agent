"""Generate the fully synthetic demo study SYN-001.

Everything here is invented: subjects, sites, dates and terms are random draws
with a fixed seed. No real study, sponsor or company material is used.

Outputs
  sdtm/raw/RAW_DM.csv, RAW_AE.csv        raw "EDC" extracts
  sdtm/spec_final.xlsx                   clean spec (buildable)
  sdtm/spec_draft.xlsx                   same spec with seeded defects (QC demo)
  sdtm/reference/DM.csv, AE.csv          independently hand-coded reference datasets
  adam/spec_final.xlsx, spec_draft.xlsx
  adam/reference/ADSL.csv, ADAE.csv
  answer_key.json                        seeded defects -> what QC should report
"""
from __future__ import annotations

import copy
import json
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
rng = random.Random(2026)
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def raw_date(d: date | None, unk_day: bool = False) -> str:
    if d is None:
        return ""
    return f"{'UNK' if unk_day else f'{d.day:02d}'}-{MON[d.month - 1]}-{d.year}"


# =============================================================== raw data
def make_raw():
    dm, ae = [], []
    sites = ["101", "102", "205"]
    countries = {"101": "USA", "102": "USA", "205": "CAN"}
    terms = [("Headache", "Headache"), ("Nausea", "Nausea"), ("Tiredness", "Fatigue"), ("Dizzy", "Dizziness"),
             ("Skin rash", "Rash"), ("Lower back pain", "Back pain"), ("Cough", "Cough")]
    n = 0
    for site in sites:
        for k in range(1, 15):
            n += 1
            subj = f"{site}-{k:03d}"
            birth = date(1940, 1, 1) + timedelta(days=rng.randint(0, 365 * 45))
            screen_fail = rng.random() < 0.1
            arm = "" if screen_fail else rng.choice(["Drug A", "Placebo"])
            first = None if screen_fail else date(2024, 1, 8) + timedelta(days=rng.randint(0, 150))
            last = None if screen_fail else first + timedelta(days=rng.randint(20, 120))
            dm.append({"STUDY": "SYN-001", "SITE": site, "SUBJ": subj, "BRTHDAT": raw_date(birth),
                       "SEX": rng.choice(["Male", "Female"]),
                       "RACE": rng.choice(["White", "White", "Asian", "Black or African American"]),
                       "RAND_ARM": arm, "FIRST_DOSE_DT": first.isoformat() if first else "",
                       "LAST_DOSE_DT": last.isoformat() if last else "", "COUNTRY": countries[site]})
            if screen_fail:
                continue
            for _ in range(rng.choice([0, 1, 1, 2, 3, 4])):
                verb, dec = rng.choice(terms)
                st = first + timedelta(days=rng.randint(-10, 90))
                en = st + timedelta(days=rng.randint(0, 20)) if rng.random() < 0.8 else None
                ae.append({"STUDY": "SYN-001", "SITE": site, "SUBJ": subj, "AETERM": verb, "AEDECOD": dec,
                           "AESTDAT": raw_date(st, unk_day=rng.random() < 0.07), "AEENDAT": raw_date(en),
                           "AESEV": rng.choice(["Mild", "Mild", "Moderate", "Severe"]),
                           "AESER": "Yes" if rng.random() < 0.08 else "No"})
    return pd.DataFrame(dm), pd.DataFrame(ae)


# ================================================== independent reference code
# Written separately from the generated programs (plain datetime / pandas, no SpecForge
# helpers) so that agreement between the two is meaningful: blinded double programming.
def _iso(s: str) -> str:
    if not s:
        return ""
    if "-" in s and s[:4].isdigit():
        return s
    d, m, y = s.split("-")
    mm = MON.index(m) + 1
    return f"{y}-{mm:02d}" if d == "UNK" else f"{y}-{mm:02d}-{int(d):02d}"


def _dt(s: str):
    return date.fromisoformat(s) if s and len(s) == 10 else None


def ref_sdtm(rdm: pd.DataFrame, rae: pd.DataFrame):
    sex = {"Male": "M", "Female": "F"}
    arm = {"Drug A": ("DRUGA", "Drug A"), "Placebo": ("PBO", "Placebo")}
    dm = []
    for r in rdm.itertuples():
        b, s = _iso(r.BRTHDAT), r.FIRST_DOSE_DT
        age = None
        if s:
            bd, sd = date.fromisoformat(b), date.fromisoformat(s)
            age = sd.year - bd.year - ((sd.month, sd.day) < (bd.month, bd.day))
        armcd, armt = arm.get(r.RAND_ARM, ("SCRNFAIL", "Screen Failure"))
        dm.append({"STUDYID": r.STUDY, "DOMAIN": "DM", "USUBJID": f"{r.STUDY}-{r.SITE}-{r.SUBJ}", "SUBJID": r.SUBJ,
                   "SITEID": r.SITE, "RFSTDTC": s, "RFENDTC": r.LAST_DOSE_DT, "BRTHDTC": b, "AGE": age,
                   "AGEU": "YEARS", "SEX": sex[r.SEX], "RACE": r.RACE.upper(), "ARMCD": armcd, "ARM": armt,
                   "COUNTRY": r.COUNTRY})
    dm = pd.DataFrame(dm)
    rf = dict(zip(dm.USUBJID, dm.RFSTDTC))
    ae = []
    for r in rae.itertuples():
        u = f"{r.STUDY}-{r.SITE}-{r.SUBJ}"
        st = _iso(r.AESTDAT)
        dy = None
        if _dt(st) and _dt(rf[u]):
            diff = (_dt(st) - _dt(rf[u])).days
            dy = diff + 1 if diff >= 0 else diff
        ae.append({"STUDYID": r.STUDY, "DOMAIN": "AE", "USUBJID": u, "AETERM": r.AETERM, "AEDECOD": r.AEDECOD,
                   "AESEV": r.AESEV.upper(), "AESER": r.AESER[0], "AESTDTC": st, "AEENDTC": _iso(r.AEENDAT),
                   "AESTDY": dy})
    ae = pd.DataFrame(ae)
    ae["_o"] = range(len(ae))
    ae = ae.sort_values(["USUBJID", "AESTDTC", "AETERM", "_o"])
    ae["AESEQ"] = ae.groupby("USUBJID").cumcount() + 1
    ae = ae.sort_values("_o").drop(columns="_o")
    cols = ["STUDYID", "DOMAIN", "USUBJID", "AESEQ", "AETERM", "AEDECOD", "AESEV", "AESER", "AESTDTC", "AEENDTC", "AESTDY"]
    return dm, ae[cols].reset_index(drop=True)


def ref_adam(dm: pd.DataFrame, ae: pd.DataFrame):
    adsl = dm[["STUDYID", "USUBJID", "SUBJID", "SITEID", "AGE", "SEX", "RACE", "ARMCD", "ARM", "COUNTRY"]].copy()
    adsl["AGEGR1"] = ["" if pd.isna(a) else "<65" if a < 65 else ">=65" for a in adsl.AGE]
    adsl["AGEGR1N"] = pd.array([None if g == "" else 1 if g == "<65" else 2 for g in adsl.AGEGR1], dtype="Int64")
    adsl["TRT01P"] = adsl.ARM
    adsl["TRTSDT"] = [d if d else "" for d in dm.RFSTDTC]
    adsl["TRTEDT"] = [d if d else "" for d in dm.RFENDTC]
    adsl["SAFFL"] = ["Y" if d else "N" for d in adsl.TRTSDT]
    adsl["ITTFL"] = ["Y" if a != "SCRNFAIL" else "N" for a in adsl.ARMCD]
    adsl = adsl[["STUDYID", "USUBJID", "SUBJID", "SITEID", "AGE", "AGEGR1", "AGEGR1N", "SEX", "RACE", "COUNTRY",
                 "ARMCD", "ARM", "TRT01P", "TRTSDT", "TRTEDT", "SAFFL", "ITTFL"]]
    m = adsl.set_index("USUBJID")
    rows = []
    for r in ae.itertuples():
        trtsdt = m.at[r.USUBJID, "TRTSDT"]
        ast = r.AESTDTC if len(r.AESTDTC) == 10 else ""
        dy, emf = None, ""
        if ast and trtsdt:
            diff = (date.fromisoformat(ast) - date.fromisoformat(trtsdt)).days
            dy = diff + 1 if diff >= 0 else diff
            emf = "Y" if diff >= 0 else ""
        rows.append({"STUDYID": r.STUDYID, "USUBJID": r.USUBJID, "AESEQ": r.AESEQ, "AETERM": r.AETERM,
                     "AEDECOD": r.AEDECOD, "AESEV": r.AESEV, "AESER": r.AESER, "TRTA": m.at[r.USUBJID, "TRT01P"],
                     "SAFFL": m.at[r.USUBJID, "SAFFL"], "TRTSDT": trtsdt, "AESTDTC": r.AESTDTC, "ASTDT": ast,
                     "ASTDY": dy, "TRTEMFL": emf})
    return adsl, pd.DataFrame(rows)


# ========================================================================= specs
V = ["Dataset", "Variable", "Label", "Type", "Length", "Origin", "Source/Derivation", "Codelist", "Core"]

SDTM_DATASETS = [
    {"Dataset": "DM", "Label": "Demographics", "Structure": "One record per subject", "Keys": "STUDYID, USUBJID",
     "Sources": "RAW_DM"},
    {"Dataset": "AE", "Label": "Adverse Events", "Structure": "One record per adverse event per subject",
     "Keys": "STUDYID, USUBJID, AESEQ", "Sources": "RAW_AE, DM"},
]
SDTM_VARS = [
    ("DM", "STUDYID", "Study Identifier", "Char", 12, "CRF", "RAW_DM.STUDY", "", "Req"),
    ("DM", "DOMAIN", "Domain Abbreviation", "Char", 2, "Assigned", "Set to 'DM'", "", "Req"),
    ("DM", "USUBJID", "Unique Subject Identifier", "Char", 30, "Derived",
     "Concatenate RAW_DM.STUDY, '-', RAW_DM.SITE, '-', RAW_DM.SUBJ", "", "Req"),
    ("DM", "SUBJID", "Subject Identifier for the Study", "Char", 10, "CRF", "RAW_DM.SUBJ", "", "Req"),
    ("DM", "SITEID", "Study Site Identifier", "Char", 5, "CRF", "RAW_DM.SITE", "", "Req"),
    ("DM", "RFSTDTC", "Subject Reference Start Date/Time", "Char", 19, "Derived", "ISO 8601 date of RAW_DM.FIRST_DOSE_DT", "", "Exp"),
    ("DM", "RFENDTC", "Subject Reference End Date/Time", "Char", 19, "Derived", "ISO 8601 date of RAW_DM.LAST_DOSE_DT", "", "Exp"),
    ("DM", "BRTHDTC", "Date/Time of Birth", "Char", 19, "CRF", "ISO 8601 date of RAW_DM.BRTHDAT", "", "Perm"),
    ("DM", "AGE", "Age", "Num", 8, "Derived", "Age in completed years from BRTHDTC to RFSTDTC", "", "Exp"),
    ("DM", "AGEU", "Age Units", "Char", 5, "Assigned", "Set to 'YEARS'", "AGEU", "Exp"),
    ("DM", "SEX", "Sex", "Char", 1, "CRF", "Map RAW_DM.SEX using codelist SEX", "SEX", "Req"),
    ("DM", "RACE", "Race", "Char", 40, "CRF", "Map RAW_DM.RACE using codelist RACE", "RACE", "Exp"),
    ("DM", "ARMCD", "Planned Arm Code", "Char", 8, "Derived",
     "Map RAW_DM.RAND_ARM using codelist ARMCD; if missing set to 'SCRNFAIL'", "ARMCD", "Req"),
    ("DM", "ARM", "Description of Planned Arm", "Char", 40, "Derived",
     "Map RAW_DM.RAND_ARM using codelist ARM; if missing set to 'Screen Failure'", "ARM", "Req"),
    ("DM", "COUNTRY", "Country", "Char", 3, "CRF", "RAW_DM.COUNTRY", "", "Req"),
    ("AE", "STUDYID", "Study Identifier", "Char", 12, "CRF", "RAW_AE.STUDY", "", "Req"),
    ("AE", "DOMAIN", "Domain Abbreviation", "Char", 2, "Assigned", "Set to 'AE'", "", "Req"),
    ("AE", "USUBJID", "Unique Subject Identifier", "Char", 30, "Derived",
     "Concatenate RAW_AE.STUDY, '-', RAW_AE.SITE, '-', RAW_AE.SUBJ", "", "Req"),
    ("AE", "AESEQ", "Sequence Number", "Num", 8, "Derived", "Sequence number within USUBJID ordered by AESTDTC, AETERM", "", "Req"),
    ("AE", "AETERM", "Reported Term for the Adverse Event", "Char", 200, "CRF", "RAW_AE.AETERM", "", "Req"),
    ("AE", "AEDECOD", "Dictionary-Derived Term", "Char", 200, "Assigned", "RAW_AE.AEDECOD", "", "Req"),
    ("AE", "AESEV", "Severity/Intensity", "Char", 10, "CRF", "Map RAW_AE.AESEV using codelist AESEV", "AESEV", "Perm"),
    ("AE", "AESER", "Serious Event", "Char", 1, "CRF", "Map RAW_AE.AESER using codelist NY", "NY", "Exp"),
    ("AE", "AESTDTC", "Start Date/Time of Adverse Event", "Char", 19, "CRF", "ISO 8601 date of RAW_AE.AESTDAT", "", "Exp"),
    ("AE", "AEENDTC", "End Date/Time of Adverse Event", "Char", 19, "CRF", "ISO 8601 date of RAW_AE.AEENDAT", "", "Exp"),
    ("AE", "AESTDY", "Study Day of Start of Adverse Event", "Num", 8, "Derived",
     "Study day of AESTDTC relative to DM.RFSTDTC merged by USUBJID: AESTDTC - RFSTDTC + 1 if on or after RFSTDTC, "
     "else AESTDTC - RFSTDTC (no day 0); missing if either date is partial or missing", "", "Perm"),
]
SDTM_CL = [("SEX", "M", "Male"), ("SEX", "F", "Female"), ("AGEU", "YEARS", "Years"),
           ("RACE", "WHITE", "White"), ("RACE", "ASIAN", "Asian"),
           ("RACE", "BLACK OR AFRICAN AMERICAN", "Black or African American"),
           ("ARMCD", "DRUGA", "Drug A"), ("ARMCD", "PBO", "Placebo"), ("ARMCD", "SCRNFAIL", "Screen Failure"),
           ("ARM", "Drug A", "Drug A"), ("ARM", "Placebo", "Placebo"), ("ARM", "Screen Failure", "Screen Failure"),
           ("AESEV", "MILD", "Mild"), ("AESEV", "MODERATE", "Moderate"), ("AESEV", "SEVERE", "Severe"),
           ("NY", "N", "No"), ("NY", "Y", "Yes")]

ADAM_DATASETS = [
    {"Dataset": "ADSL", "Label": "Subject-Level Analysis Dataset", "Structure": "ADSL - one record per subject",
     "Keys": "STUDYID, USUBJID", "Sources": "DM"},
    {"Dataset": "ADAE", "Label": "Adverse Events Analysis Dataset", "Structure": "OCCDS - one record per AE",
     "Keys": "STUDYID, USUBJID, AESEQ", "Sources": "AE, ADSL"},
]
ADAM_VARS = [
    ("ADSL", "STUDYID", "Study Identifier", "Char", 12, "Predecessor", "DM.STUDYID", "", "Req"),
    ("ADSL", "USUBJID", "Unique Subject Identifier", "Char", 30, "Predecessor", "DM.USUBJID", "", "Req"),
    ("ADSL", "SUBJID", "Subject Identifier for the Study", "Char", 10, "Predecessor", "DM.SUBJID", "", "Req"),
    ("ADSL", "SITEID", "Study Site Identifier", "Char", 5, "Predecessor", "DM.SITEID", "", "Req"),
    ("ADSL", "AGE", "Age", "Num", 8, "Predecessor", "DM.AGE", "", "Req"),
    ("ADSL", "AGEGR1", "Pooled Age Group 1", "Char", 4, "Derived", "Set to '<65' if AGE < 65, else '>=65'; missing if AGE is missing", "AGEGR1", "Perm"),
    ("ADSL", "AGEGR1N", "Pooled Age Group 1 (N)", "Num", 8, "Derived", "Set to 1 if AGEGR1 = '<65', else 2; missing if AGEGR1 is missing", "", "Perm"),
    ("ADSL", "SEX", "Sex", "Char", 1, "Predecessor", "DM.SEX", "SEX", "Req"),
    ("ADSL", "RACE", "Race", "Char", 40, "Predecessor", "DM.RACE", "", "Req"),
    ("ADSL", "COUNTRY", "Country", "Char", 3, "Predecessor", "DM.COUNTRY", "", "Perm"),
    ("ADSL", "ARMCD", "Planned Arm Code", "Char", 8, "Predecessor", "DM.ARMCD", "", "Perm"),
    ("ADSL", "ARM", "Description of Planned Arm", "Char", 40, "Predecessor", "DM.ARM", "", "Req"),
    ("ADSL", "TRT01P", "Planned Treatment for Period 01", "Char", 40, "Predecessor", "DM.ARM", "", "Req"),
    ("ADSL", "TRTSDT", "Date of First Exposure to Treatment", "Num", 8, "Derived", "Numeric date of DM.RFSTDTC", "", "Exp"),
    ("ADSL", "TRTEDT", "Date of Last Exposure to Treatment", "Num", 8, "Derived", "Numeric date of DM.RFENDTC", "", "Exp"),
    ("ADSL", "SAFFL", "Safety Population Flag", "Char", 1, "Derived", "Set to 'Y' if TRTSDT is not missing, else 'N'", "NY", "Req"),
    ("ADSL", "ITTFL", "Intent-To-Treat Population Flag", "Char", 1, "Derived", "Set to 'Y' if ARMCD ne 'SCRNFAIL', else 'N'", "NY", "Req"),
    ("ADAE", "STUDYID", "Study Identifier", "Char", 12, "Predecessor", "AE.STUDYID", "", "Req"),
    ("ADAE", "USUBJID", "Unique Subject Identifier", "Char", 30, "Predecessor", "AE.USUBJID", "", "Req"),
    ("ADAE", "AESEQ", "Sequence Number", "Num", 8, "Predecessor", "AE.AESEQ", "", "Req"),
    ("ADAE", "AETERM", "Reported Term for the Adverse Event", "Char", 200, "Predecessor", "AE.AETERM", "", "Req"),
    ("ADAE", "AEDECOD", "Dictionary-Derived Term", "Char", 200, "Predecessor", "AE.AEDECOD", "", "Req"),
    ("ADAE", "AESEV", "Severity/Intensity", "Char", 10, "Predecessor", "AE.AESEV", "", "Perm"),
    ("ADAE", "AESER", "Serious Event", "Char", 1, "Predecessor", "AE.AESER", "", "Perm"),
    ("ADAE", "TRTA", "Actual Treatment", "Char", 40, "Derived", "ADSL.TRT01P merged by USUBJID", "", "Req"),
    ("ADAE", "SAFFL", "Safety Population Flag", "Char", 1, "Predecessor", "ADSL.SAFFL merged by USUBJID", "NY", "Req"),
    ("ADAE", "TRTSDT", "Date of First Exposure to Treatment", "Num", 8, "Predecessor", "ADSL.TRTSDT merged by USUBJID", "", "Perm"),
    ("ADAE", "AESTDTC", "Start Date/Time of Adverse Event", "Char", 19, "Predecessor", "AE.AESTDTC", "", "Perm"),
    ("ADAE", "ASTDT", "Analysis Start Date", "Num", 8, "Derived",
     "Numeric date of AESTDTC; missing if AESTDTC is partial (no imputation)", "", "Exp"),
    ("ADAE", "ASTDY", "Analysis Start Relative Day", "Num", 8, "Derived",
     "Study day of ASTDT relative to TRTSDT: ASTDT - TRTSDT + 1 if ASTDT >= TRTSDT, else ASTDT - TRTSDT; "
     "missing if either is missing", "", "Perm"),
    ("ADAE", "TRTEMFL", "Treatment Emergent Analysis Flag", "Char", 1, "Derived",
     "Set to 'Y' if ASTDT >= TRTSDT, else null; null if ASTDT or TRTSDT is missing", "Y", "Exp"),
]
ADAM_CL = [("AGEGR1", "<65", "<65"), ("AGEGR1", ">=65", ">=65"), ("SEX", "M", "Male"), ("SEX", "F", "Female"),
           ("NY", "N", "No"), ("NY", "Y", "Yes"), ("Y", "Y", "Yes")]

# -------------------------------------------------------- seeded defects (QC demo)
# (dataset, variable, field, new value, expected rule or agent category)
SDTM_DEFECTS = [
    ("DM", "RFSTDTC", "Type", "Num", "SDTM-002"),
    ("DM", "AGE", "Label", "Age of the Subject in Years at Informed Consent", "GEN-004"),
    ("DM", "ARMCD", "Source/Derivation", "Map RAW_DM.RAND_ARM using codelist ARMCD; TBD for screen failures", "clarity"),
    ("DM", "COUNTRY", "Origin", "eCRF", "GEN-008"),
    ("AE", "AESER", "Source/Derivation", "Set to 'YES' if RAW_AE.AESER = 'Yes', else 'N'", "GEN-014"),
    ("AE", "AESEV", "Codelist", "SEVERITY", "GEN-009"),
    ("AE", "AESTDY", "Source/Derivation", "AESTDTC minus DM.RFSTDTC", "SDTM-004"),
    ("AE", "AESEQ", "Source/Derivation", "Number the events for each subject starting from the first one", "clarity"),
    ("AE", "AEENDTC", "Source/Derivation", "ISO 8601 date of RAW_AE.AEENDAT; impute missing day as last day of month", "conformance"),
    ("AE", "AEOUTCOME", None, ("AE", "AEOUTCOME", "Outcome of Adverse Event", "Char", 40, "CRF", "RAW_AE.AEOUT", "", "Perm"), "GEN-002"),
]
ADAM_DEFECTS = [
    ("ADSL", "SAFFL", "Source/Derivation", "Set to 'Y' if subject received any study treatment", "clarity"),
    ("ADSL", "TRTSDT", "Type", "Char", "ADAM-003"),
    ("ADSL", "AGEGR1N", "Type", "Char", "ADAM-005"),
    ("ADSL", "ITTFL", "Length", 2, "ADAM-004"),
    ("ADSL", "EOSSTT", None, ("ADSL", "EOSSTT", "End of Study Status", "Char", 20, "Derived", "", "", "Perm"), "GEN-007"),
    ("ADAE", "TRTEMFL", "Source/Derivation", "Set to 'Y' if ASTDT >= ADSL.TRTSTDT", "GEN-013"),
    ("ADAE", "ASTDT", "Source/Derivation", "Numeric date of AESTDTC, imputed as appropriate", "clarity"),
    ("ADAE", "SAFFL", "Label", "Safety Flag", "consistency"),
    ("ADAE", "AOCCFL", None, ("ADAE", "AOCCFL", "1st Occurrence within Subject Flag", "Char", 1, "Derived",
                              "Flag the first occurrence of each AEDECOD for the subject with 'Y'", "Y", "Perm"), "clarity"),
    ("ADSL", "(dataset)", "Keys", "STUDYID, USUBJID, SITEID", "ADAM-008"),
]


def apply_defects(vars_, datasets, defects):
    vars_ = [list(v) for v in vars_]
    datasets = copy.deepcopy(datasets)
    for ds, var, field, value, _ in defects:
        if field is None:
            vars_.append(list(value))
        elif var == "(dataset)":
            next(d for d in datasets if d["Dataset"] == ds)[field] = value
        else:
            row = next(v for v in vars_ if v[0] == ds and v[1] == var)
            row[V.index(field)] = value
    return [tuple(v) for v in vars_], datasets


def write_spec(path: Path, datasets, vars_, cl):
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        pd.DataFrame(datasets).to_excel(xw, sheet_name="Datasets", index=False)
        pd.DataFrame(vars_, columns=V).to_excel(xw, sheet_name="Variables", index=False)
        pd.DataFrame(cl, columns=["Codelist", "Code", "Decode"]).to_excel(xw, sheet_name="Codelists", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(60, max(10, max(len(str(c.value or "")) for c in col)))


def main():
    rdm, rae = make_raw()
    (HERE / "sdtm/raw").mkdir(parents=True, exist_ok=True)
    rdm.to_csv(HERE / "sdtm/raw/RAW_DM.csv", index=False)
    rae.to_csv(HERE / "sdtm/raw/RAW_AE.csv", index=False)
    dm, ae = ref_sdtm(rdm, rae)
    adsl, adae = ref_adam(dm, ae)
    for sub, frames in (("sdtm/reference", {"DM": dm, "AE": ae}), ("adam/reference", {"ADSL": adsl, "ADAE": adae})):
        (HERE / sub).mkdir(parents=True, exist_ok=True)
        for k, f in frames.items():
            f.to_csv(HERE / sub / f"{k}.csv", index=False)
    # ADaM inputs = the SDTM reference (so the ADaM demo works without running SDTM first)
    (HERE / "adam/inputs").mkdir(parents=True, exist_ok=True)
    dm.to_csv(HERE / "adam/inputs/DM.csv", index=False)
    ae.to_csv(HERE / "adam/inputs/AE.csv", index=False)

    write_spec(HERE / "sdtm/spec_final.xlsx", SDTM_DATASETS, SDTM_VARS, SDTM_CL)
    write_spec(HERE / "adam/spec_final.xlsx", ADAM_DATASETS, ADAM_VARS, ADAM_CL)
    v, d = apply_defects(SDTM_VARS, SDTM_DATASETS, SDTM_DEFECTS)
    write_spec(HERE / "sdtm/spec_draft.xlsx", d, v, SDTM_CL)
    v, d = apply_defects(ADAM_VARS, ADAM_DATASETS, ADAM_DEFECTS)
    write_spec(HERE / "adam/spec_draft.xlsx", d, v, ADAM_CL)
    key = {"SDTM": [{"dataset": a, "variable": b, "expect": e} for a, b, _, _, e in SDTM_DEFECTS],
           "ADaM": [{"dataset": a, "variable": b, "expect": e} for a, b, _, _, e in ADAM_DEFECTS]}
    (HERE / "answer_key.json").write_text(json.dumps(key, indent=2))
    print(f"raw DM {len(rdm)}, raw AE {len(rae)}; reference DM {len(dm)}, AE {len(ae)}, ADSL {len(adsl)}, ADAE {len(adae)}")


if __name__ == "__main__":
    main()

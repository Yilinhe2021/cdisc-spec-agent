# Evaluation results

LLM provider: `mock` / `offline-heuristics` · generated 2026-10-21

## 1. Seeded defects (examples/*/spec_draft.xlsx)

| Standard | Dataset.Variable | Expected | Detected |
|---|---|---|---|
| SDTM | DM.RFSTDTC | SDTM-002 | yes |
| SDTM | DM.AGE | GEN-004 | yes |
| SDTM | DM.ARMCD | clarity | yes |
| SDTM | DM.COUNTRY | GEN-008 | yes |
| SDTM | AE.AESER | GEN-014 | yes |
| SDTM | AE.AESEV | GEN-009 | yes |
| SDTM | AE.AESTDY | SDTM-004 | yes |
| SDTM | AE.AESEQ | clarity | yes |
| SDTM | AE.AEENDTC | conformance | yes |
| SDTM | AE.AEOUTCOME | GEN-002 | yes |
| ADaM | ADSL.SAFFL | clarity | yes |
| ADaM | ADSL.TRTSDT | ADAM-003 | yes |
| ADaM | ADSL.AGEGR1N | ADAM-005 | yes |
| ADaM | ADSL.ITTFL | ADAM-004 | yes |
| ADaM | ADSL.EOSSTT | GEN-007 | yes |
| ADaM | ADAE.TRTEMFL | GEN-013 | yes |
| ADaM | ADAE.ASTDT | clarity | yes |
| ADaM | ADAE.SAFFL | consistency | yes |
| ADaM | ADAE.AOCCFL | clarity | yes |
| ADaM | ADSL.(dataset) | ADAM-008 | yes |

**Recall 20/20 = 100%**. Additional findings on the drafts not in the answer key: 5 (review manually; may be real).

## 2. False positives on clean specs

| Standard | Findings on spec_final.xlsx |
|---|---|
| SDTM | 0 |
| ADaM | 0 |

## 3. Mutation testing (60 single-defect mutants)

| Operator | Detected | Recall |
|---|---|---|
| long_label | 6/6 | 100% |
| bad_name | 6/6 | 100% |
| drop_derivation | 6/6 | 100% |
| bad_type | 6/6 | 100% |
| undefined_codelist | 6/6 | 100% |
| vague | 6/6 | 100% |
| drop_else | 6/6 | 100% |
| bad_literal | 6/6 | 100% |
| dangling_ref | 6/6 | 100% |
| duplicate | 6/6 | 100% |
| **all** | **60/60** | **100%** |

## 4. Build accuracy vs independent reference (blinded)

| Standard | Dataset | Status | Rows | Concordance | Cells |
|---|---|---|---|---|---|
| SDTM | DM | ok | 42 | 100.0% | 546/546 |
| SDTM | AE | ok | 71 | 100.0% | 568/568 |
| ADaM | ADSL | warnings | 42 | 100.0% | 630/630 |
| ADaM | ADAE | ok | 71 | 100.0% | 781/781 |

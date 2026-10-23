# SDTM essentials (summary)

> Original, simplified summary of public SDTM concepts for retrieval. Confirm details
> against the SDTMIG version used by your study.

## Purpose of SDTM
SDTM organizes collected study data into standard tables called domains. It is a
tabulation model: it represents what was collected with minimal derivation. Heavy
analysis logic belongs in ADaM, not SDTM.

## Identifier variables
Nearly every domain carries STUDYID (study identifier), DOMAIN (the two-letter
domain code, constant within the dataset), and USUBJID (a subject identifier that
is unique across all studies of the product). USUBJID is commonly built by joining
the study identifier, a site identifier and the subject number, but the rule must be
stated explicitly in the spec. Most domains also carry a --SEQ sequence number that
makes records unique within a subject.

## Variable prefixes
Within the general-observation-class domains (interventions, events, findings),
non-identifier variables are named with the two-letter domain code as a prefix:
for example AETERM, AESTDTC and AESEQ in the AE domain. Generic names in the
standards are written with "--" standing in for the prefix.

## Dates and times
Dates and times in SDTM are stored as character strings in ISO 8601 format in
variables ending in DTC (e.g. --STDTC, --ENDTC). Partial dates are represented by
truncating the string (e.g. "2024-03" when the day is unknown); SDTM does not impute
missing parts. Study day variables (--DY, --STDY, --ENDY) are numeric and are
computed relative to the reference start date in DM, with no day zero: the day of
reference start is day 1 and the day before is day -1.

## Demographics (DM)
DM has one record per subject. It holds the reference start and end dates
(RFSTDTC, RFENDTC) used to compute study days in every other domain, as well as
planned and actual arm, age, sex, race and country. AGE is numeric and normally
paired with AGEU giving its unit.

## Adverse events (AE)
AE has one record per adverse event per subject. The verbatim term (AETERM) is
collected; the dictionary-derived term (AEDECOD) and body system come from coding.
Seriousness, severity, relationship and outcome usually use controlled terminology,
and the spec should say how missing or "unknown" responses are represented.

## Supplemental qualifiers
Collected values that have no standard variable in a domain go to a supplemental
qualifier dataset (SUPP--) in a vertical structure: one record per extra value,
identified by QNAM/QLABEL and linked back to the parent record through IDVAR and
IDVARVAL. The spec should state the QNAM, QLABEL and the linking variable.

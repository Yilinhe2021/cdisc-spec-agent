# ADaM essentials (summary)

> Original, simplified summary of public ADaM concepts for retrieval. Confirm details
> against the ADaMIG version used by your study.

## Purpose of ADaM
ADaM datasets are analysis-ready: they are derived from SDTM (and other ADaM
datasets) so that statistical analyses can be run with little additional
programming. Traceability back to the source is a core principle: a reviewer should
be able to see where each value came from.

## ADSL
ADSL is the subject-level analysis dataset with one record per subject. It holds
treatment variables (planned and actual), population flags, treatment start and end
dates, and baseline characteristics. Other ADaM datasets merge subject-level
variables from ADSL instead of re-deriving them.

## BDS structure
The Basic Data Structure (BDS) holds one or more records per subject per analysis
parameter per analysis timepoint. Its central variables are PARAMCD (short code,
at most 8 characters), PARAM (full parameter description), AVAL (numeric analysis
value) and/or AVALC (character analysis value), plus timing variables such as
AVISIT/AVISITN and ADT. Baseline is identified with ABLFL and BASE, and change
from baseline with CHG.

## OCCDS structure
The occurrence data structure is used for events and interventions, e.g. adverse
events and concomitant medications. Typical ADAE content is the SDTM AE record plus
analysis dates (ASTDT, AENDT), treatment-emergent flags (TRTEMFL) and occurrence
flags for counting first events.

## Dates in ADaM
Analysis dates are numeric: names ending in DT are numeric dates, DTM numeric
datetimes and TM numeric times. When dates are imputed, companion flag variables
(e.g. ASTDTF) record which part was imputed. The spec must spell out the imputation
rule, including what happens when the whole date is missing.

## Flags
Analysis flags end in FL and use the values "Y" and "N" (population flags in ADSL)
or "Y" and null (record-level flags in BDS/OCCDS). The spec should say which
convention applies. Flags should be character with length 1.

## Numeric companions
A character variable is often paired with a numeric version ending in N used for
sorting (AVISIT/AVISITN, TRT01P/TRT01PN). The pairing should be one-to-one, and both
variables should exist in the dataset.

## Treatment variables
ADSL carries treatment variables per period, e.g. TRT01P (planned treatment for
period 01) and TRT01A (actual treatment for period 01), with numeric companions. In
record-level datasets, TRTP and TRTA give the treatment applicable to the record.

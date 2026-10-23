# Commonly used standard variables

> Quick reference of frequently used variable names and their usual meaning, written
> for this project. Use the published standard for the authoritative label text.

## Subject identifiers
STUDYID identifies the study. USUBJID uniquely identifies a subject across all
studies of a product. SUBJID is the subject identifier used within the study.
SITEID identifies the investigator site.

## Demographic variables
AGE is the numeric age, AGEU its unit (typically YEARS). SEX, RACE and ETHNIC use
controlled terminology. COUNTRY uses a three-letter country code. BRTHDTC holds the
birth date in ISO 8601 when collected.

## Treatment and reference dates
RFSTDTC / RFENDTC hold the subject reference start and end dates in SDTM DM. In
ADaM, TRTSDT and TRTEDT are the numeric first and last treatment dates. ARM/ARMCD
are the planned arm, ACTARM/ACTARMCD the actual arm.

## Population flags
Common ADSL population flags include SAFFL (safety), ITTFL (intent-to-treat),
FASFL (full analysis set), PPROTFL (per protocol) and RANDFL (randomized). Each flag
needs an explicit definition in the spec.

## Event variables
AETERM verbatim term, AEDECOD dictionary-derived term, AEBODSYS body system,
AESEV severity, AESER serious event, AEREL causality, AEOUT outcome, AESTDTC and
AEENDTC start and end dates. In ADaM, ASTDT/AENDT are the numeric analysis dates
and TRTEMFL flags treatment-emergent events.

## Sequence and timing
--SEQ is a numeric sequence number unique within subject. VISIT/VISITNUM identify
the planned visit, EPOCH the trial epoch. --DY is a numeric study day.

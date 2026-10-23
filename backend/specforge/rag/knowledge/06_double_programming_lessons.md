# Lessons from independent (double) programming

> Practitioner notes: where two independently written programs, or a program and
> its spec, most often disagree. Written from experience; generic, no study data.

## Missing values compare differently in SAS and Python
In SAS a missing numeric value sorts below every number, so `AGE < 65` is true when
AGE is missing, and a missing date is "before" every date. A missing character value
is a blank, so `X ne 'Primary'` is true when X is missing. In pandas, NaN/NaT
comparisons are always false. A spec that says "'<65' if AGE < 65, else '>=65'" gives
different answers in the two languages for subjects without an age. Every condition
on a variable that can be missing should state the missing case explicitly.

## Before blaming the reference, re-read the condition
When a group of records disagrees with the reference and looks like a reference
problem, first check how the comparison treats missing values (see above). A whole
group of subjects without a source value usually means a missing-value branch was
taken differently, not that the reference is wrong.

## One partial date can break several datasets
A partial or incomplete date (for example a death date with an unknown day) can
leave a subject-level date empty, such as the end of treatment. Every downstream
dataset that merges that date then disagrees for that subject. Imputation rules for
partial dates belong in the spec, at the variable where the date is first used.

## Re-typed text is the largest source of small mismatches
Labels, codelist values and literals copied by hand drift in case, spacing,
underscores and punctuation. Programs should copy these strings from the spec rather
than retyping them, and reviewers should treat "looks the same" as not good enough.

## Malformed literals in the spec itself
A literal opened with one quote character and closed with another, or a curly quote
pasted from a word processor, can make a program silently drop records. Fixing the
program does not help if the spec is regenerated; the spec text must be corrected and
programs should parse defensively.

## Encodings and invisible characters
Source files are not always in the encoding their header declares, and a single file
can contain mixed encodings. Non-breaking spaces and full-width characters make
values look identical while comparing unequal. Normalise text (Unicode NFKC, NBSP to
space, trim) before comparing, and detect encoding per file rather than trusting
metadata.

## Identifier formats
Subject identifiers can differ only in zero padding or separators between sources
(`101-001` vs `101-1`). Joins on such keys silently lose rows; normalise identifiers
before merging and check row counts after every merge.

## Do not tune to the answer key
When a change fixes some cells and breaks others (e.g. choosing the earliest instead
of the latest event), measure the net effect. If the spec does not decide the
question, record it as a spec ambiguity instead of tuning the program to the
reference.

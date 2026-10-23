# Writing an implementable derivation

> Project guidance: what makes a spec row programmable by someone who cannot ask
> questions. This is the core review standard used by the clarity reviewer.

## The independent-programmer test
A derivation is clear when two programmers who never talk to each other, given only
the spec and the source data, would write programs that produce identical values.
Anything that forces a programmer to guess, ask, or look at another team's code is a
defect, even if the author "knows what they meant".

## Conditions need every branch
"Set to 'Y' if X" leaves the other case undefined: is it 'N' or null? Every
conditional derivation should state the value for each branch, including what
happens when the input itself is missing.

## Sort order and ties
Words like first, last, earliest, latest, baseline or worst need an explicit ordering
key and a tie-breaker. "First dose" must say which date variable and what to do with
two records on the same date.

## Missing and partial dates
Any derivation that compares or subtracts dates must say how partial or missing
dates are handled: excluded, imputed (and how), or carried as missing.

## Vague words to avoid
Phrases such as "as appropriate", "if applicable", "etc.", "and/or", "TBD", "TBC",
"per SAP" (without a section), "see programming notes", "derived accordingly" or
"use standard algorithm" hide the actual rule. Replace them with the rule itself or
with a precise reference to where it is written.

## Units and thresholds
Numeric thresholds need units and the boundary must be explicit: "age >= 65" rather
than "elderly", and "> 3 x ULN" with which ULN is meant.

## Cross references
When a derivation reads from another dataset, it should name the dataset, the
variable, and the merge key, e.g. "ADSL.TRTSDT merged by USUBJID". Referring to a
variable that is not defined anywhere in the spec is a defect.

## Literal values
When a derivation assigns a literal, it must match the codelist of the target
variable exactly: assigning "YES" to a variable whose codelist is Y/N is an error.

## Copy text, do not retype it
Programmers (and code-generating models) should copy labels, codelist values and
literals from the spec rather than retyping them. Most mismatches in independently
programmed datasets come from re-typed text: case, spacing and punctuation drift.

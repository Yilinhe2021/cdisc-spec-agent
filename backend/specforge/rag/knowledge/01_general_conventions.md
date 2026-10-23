# General dataset conventions

> Original summary of widely known public conventions, written for this project.
> It is not a copy of any CDISC document. Always confirm against the official
> implementation guide version your study uses.

## Variable names
Variable names in submission datasets are short, upper-case identifiers: at most
8 characters, letters and digits only, starting with a letter. Underscores and
lower-case letters are a sign the spec was written for an internal format rather
than for the submission format. Dataset names follow the same 8-character rule.

## Variable labels
Labels are human-readable descriptions limited to 40 characters. A label longer
than 40 characters is truncated by the transport format, so the spec should give
the final, already-shortened label. Labels of well-known standard variables should
be reused verbatim rather than re-worded, because reviewers and tools compare them.

## Data types and lengths
Submission datasets only know two storage types: character and numeric. Specs that
say "integer", "float", "date" or "datetime" must still state which of the two is
stored. Character variables need a length; the length should fit the longest
expected value and should not be wildly larger than needed.

## Origin
Every variable should say where its value comes from. Common origin values are:
Collected / CRF (taken from a case report form), Derived (computed by the
program), Assigned (set by the sponsor, e.g. a constant or a coded value),
Protocol (fixed by the protocol), eDT (electronic data transfer, e.g. a central
lab), and Predecessor (copied unchanged from an earlier dataset). A Derived or
Assigned variable without a derivation text cannot be programmed independently.

## Keys and record uniqueness
Each dataset has a structure statement ("one record per subject", "one record per
subject per parameter per visit") and a set of key variables that make each record
unique. Every declared key must exist as a variable in the dataset, and the keys
must actually be able to identify a record given the structure.

## Controlled terminology
Variables whose values come from a fixed list reference a codelist. The codelist
must be defined somewhere in the spec (or reference a published terminology
version), each code should appear once, and any literal value that a derivation
assigns to the variable must exist in that codelist with exactly the same case and
spelling.

## Required, expected and permissible
Variables are classified by how mandatory they are. Required variables must be
present and never null. Expected variables must be present but can be null when
not applicable. Permissible variables are included when collected or useful.

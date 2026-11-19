# Fragment catalog sources

`fragments.tsv` lists every fragment the dashboard can monitor. Coordinates are
on Pf3D7 (PlasmoDB release 54), 1-based and inclusive.

| Panel | Source | How it was converted |
|---|---|---|
| IGH | `Reference/PCR_fragment_complete.tsv` of this repository (IGH malaria team amplicons) | copied as written; genes with two fragments are numbered `-1`, `-2` in file order |
| NOMADS8 | `nomads8.amplicons.bed` from github.com/JasonAHendry/nomadic, commit 9c5c4c0 (2025-07-08) | BED start + 1 |
| NOMADS16 | `nomads16.amplicons.bed`, same repository and commit | BED start + 1 |
| NOMADS-MVP | `nomadsMVP.amplicons.bed`, same repository and commit | BED start + 1 |

The `gene_id` and `category` columns are not in the nomadic BED files. They were
added for this dashboard: gene IDs are the PlasmoDB identifiers of the targeted
genes, and the categories (Drug resistance, Diversity, Diagnostic, Vaccine) are a
grouping chosen for this dashboard to organise the fragment picker, not a published
classification. Diagnostic holds hrp2, hrp3 and their flanking fragments (targets of
HRP2 based rapid tests and their deletion screen). Vaccine holds csp (antigen of the
RTS,S and R21 vaccines). ama1, msp1 and msp2 are kept under Diversity. The hrp2 and
hrp3 up and down fragments of NOMADS16 flank the deletion targets and have no
single gene ID.

Custom fragments added from the dashboard are stored in `custom.tsv`, same columns.

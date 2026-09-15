# Sync

This section collects the analysis synchronization documents.

## Datasets by era

- [2022 datasets](datasets_2022.pdf)
- [2022EE datasets](datasets_2022EE.pdf)
- [2023 datasets](datasets_2023.pdf)
- [2023BPix datasets](datasets_2023BPix.pdf)
- [2024 datasets](datasets_2024.pdf)
- [2025 datasets](datasets_2025.pdf)
- [2026 datasets](datasets_2026.pdf)

## Running the synchronization

`sync/README.md` documents the procedure: one exact NanoAOD input file per run
through the current skim and nominal selection, then the event-list comparison.
In short:

```bash
python3 sync/python/run_sync_skim.py --run          # produce our side
python3 sync/python/export_event_list.py ours/H_sideband_events.jsonl \
  --output ours/H_sideband_event_list.txt           # agreed column order
python3 sync/python/compare_sync_events.py \
  ours/H_sideband_event_ids.txt theirs/H_sideband_event_ids.txt \
  --output comparison.json                          # exit 0 only if identical
```

Agree on the exact input file with the other analysis before comparing counts.

## Corrections

Correction payloads, paths, tags, and keys used by the analysis.
<!-- This document also explains the PDF-replica and QCD-scale uncertainties derived from the LHE information, including the definitions of $\mu_R$ and $\mu_F$ and the exact Up and Down variations. -->

[Open corrections](corrections.pdf){ .md-button }

## DY reweighting

Method summaries, era coverage, fitted 0/1/2J component weights and their fit
uncertainties, plus the selected-jet and dilepton-$p_T$ corrections.

[Open DY reweighting](dy_reweighting.md){ .md-button }

## Analysis selection flow

A concise analyst-facing table of the event selection, cut order, object requirements, mass regions, and categories. Symbols identify whether each requirement is applied during skimming or histogram production.

[Open analysis selections](selections.pdf){ .md-button .md-button--primary }

## Technical workflow references

The detailed implementation-oriented tables are retained as technical references. They document the individual skim and histogram-production steps and are not intended as the primary analyst summary.

- [Detailed skim workflow](skim_selections.pdf)
- [Detailed histogram workflow](histogram_workflow.pdf)

## Cross sections

Cross sections, branching ratios, uncertainties, references, and comments.

[Open cross sections](cross_sections.pdf){ .md-button }

## Synchronization tables

The complete document contains the analysis synchronization tables.

[Open or download the PDF](sync_tables.pdf){ .md-button .md-button--primary }

<object data="sync_tables.pdf" type="application/pdf" width="100%" height="800px">
  <p>This browser does not support embedded PDF viewing.
  <a href="sync_tables.pdf">Download the document</a>.</p>
</object>

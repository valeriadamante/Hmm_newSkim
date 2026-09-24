---
name: hmm-histograms
description: >
  Produce, speed up, or debug histograms in Hmm_newSkim with
  histograms/hist_maker.py. Use when asked about histogram production,
  slow event loops, systematic/variable batching, or the hist stage of a
  campaign.
---

# Histogram production

Read `hmm-framework` first.

## Entry point

`histograms/hist_maker.py` is the single producer. The DY-weight stages
(`histograms/hist_maker_dy*_reweighting.py`) are thin wrappers that call
`histograms.hist_maker.main` with frozen `STAGE_SETTINGS`, so later corrections
cannot contaminate the fit templates. Campaigns reach the same producer through
`campaigns/workflow.py` → `histograms/scripts/{hists,systematics}.sh`.

## Cost model — this is the thing to get right

`hist_maker` builds the **cartesian product** of systematic batches and variable
batches, and runs one `ROOT.RDF.RunGraphs` per element
(`histograms/hist_maker.py`, `work_batches` and the loop that follows):

    N_event_loops = ceil(N_syst / --systematic-batch-size)
                  × ceil(N_var  / --variable-batch-size)

Each event loop re-reads every input file and re-executes every `Define`,
including DNN inference. Defaults are `--systematic-batch-size 2`,
`--variable-batch-size 5`, `--rdf-threads 1`.

`campaigns/workflow.py` passes `--rdf-threads` and `--variable-batch-size`
(from `REQUEST_CPUS` and `VARIABLE_BATCH_SIZE` in the campaign config) but
**never passes `--systematic-batch-size`**, so campaign jobs always run with 2.

Consequence: a full shifted production with ~32 variations and ~40 variables
does ~80 passes over the data, while a DY-weight stage (1 systematic,
4 variables, 1 region, 2 categories) does 1.

## Making a quick study fast

In order of effect:

1. `--systematics Central` — collapses the systematic dimension to one batch.
2. `--variables ...` and a `--variable-batch-size` ≥ the number of variables —
   collapses the variable dimension to one batch. One event loop total.
3. Drop `DNN_NNOutput` from `--variables` unless needed: it triggers
   `apply_sideband_mass_shifted_dnn` per `(mass_region, selection_suffix)` and
   is re-executed in every event loop.
4. Restrict `--mass-regions` and `--categories`: each combination is a cached
   filter node, and each costs JIT compilation plus per-event evaluation.
5. `--rdf-threads N` (match the allocated CPUs).
6. Limit the inputs with `--input-files-file` or `--input-file-batch-size`.

The trade-off for large batches is memory: the histograms alive at once are
`systematic_batch × regions × categories × variable_batch`. Increase batch sizes
first, raise `REQUEST_MEMORY` if jobs are killed.

## Diagnosing a slow job

`profile_log` already prints per-phase timings. Look at the job log and decide:

- time in `ROOT event loop batch i/N` → too many loops, raise the batch sizes;
- time in `selection and DNN graph construction` → JIT/graph building, reduce
  regions × categories × selection suffixes;
- time in `RDataFrame preparation` → `prepare_rdf` defines, usually
  `want_variations=True`.

Do not attribute slowness to ROOT or to I/O without reading those lines.

## Systematic families

Do not use `SYSTEMATICS=(Central all)` for new campaigns. Split families into
separate jobs and directories, as documented in `config/campaigns/README.md`:

    Central
    JEReta0pt0 JEReta1pt0 JEReta2pt0 JEReta2pt1 JEReta3pt0 JEReta3pt1
    JES_Total Muon PDF PU QCDScale ScaRe

Up/down variations within a family stay together. `--jes regrouped` (11 families,
"simple" inter-year correlation) and `--jes total` must never be mixed in one
product.

## Output layout

Raw per-dataset histograms, then `Central_hadded/` and `Hists_systMerged/` per
era, then the merged-era product. Histogram directories inside the file are
`<mass_region>/<category>`. Aggregated outputs must contain every histogram key
of their inputs; the campaign `check` actions verify this.

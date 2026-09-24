---
name: hmm-framework
description: >
  Work correctly inside the Hmm_newSkim CMS H→μμ Run 3 analysis framework.
  Use whenever modifying analysis code, selections, configurations,
  RDataFrame workflows, histogram production, weights, or studies.
---

# Hmm_newSkim framework

## Goal

Work inside Hmm_newSkim while preserving the analysis conventions,
configuration-driven architecture, event normalization, and existing
interfaces.

Prefer minimal changes over introducing parallel implementations.

## Repository first

Before modifying code:

1. Inspect the relevant existing implementation.
2. Search for analogous code elsewhere in the repository.
3. Inspect the relevant YAML configuration for the requested era.
4. Reuse functions from `common/`, `tools/` and `campaigns/lib/`.
5. Do not guess branch names, process names, selections, or weights.

`source env.sh` from the repository root before running anything.
`ANALYSIS_PATH` must point at the repository.

## Authoritative documentation

Read these before inventing a procedure:

    docs/ANALYSIS_WORKFLOW.md      operational guide, NanoAOD → datacard
    campaigns/README.md            campaign runner interface (authoritative)
    campaigns/SKIM_V4_POST_DY.md   post-DY-weights skim_v4 production plan
    config/campaigns/README.md     systematic-family splitting convention
    docs/SYSTEMATIC_CORRELATIONS.md JES/era correlation model

## Era-dependent configuration

Configuration lives under `config/<era>/` with
`Run3_2022, Run3_2022EE, Run3_2023, Run3_2023BPix, Run3_2024, Run3_2025, Run3_2026`:

    maincfg.yaml         variables and binning
    selections.yaml      mass regions and categories
    systematics.yaml     systematic sources and variations
    process_names.yaml   process → datasets, plot names, weight payload paths
    skim_cfg.yaml        which processes/datasets enter the skim
    samples.yaml         dataset catalogue
    triggers.yaml        trigger paths

Eras are **not** copies of each other. Verify the era you are asked about;
in particular the `categories:` block differs between 2022–2023 and 2024–2026.

Campaign definitions (paths, datasets, systematic families, resources) live in
`config/campaigns/*.sh` and are consumed by `campaigns/submit_campaign.sh`.

## RDataFrame preparation

Always go through `common.prepare_rdf.prepare_rdf`; take `prepared["inclusive"]`
as the base node. Do not recreate selections or weights manually.

For region/category nodes use `common.prepare_rdf.prepare_region_dataframes`,
which caches one filtered node per `(mass_region, category, selection_suffix)`
so a weight-only variation does not re-evaluate the selection.

Standard flow:

    raw RDF → prepare_rdf(...) → prepared["inclusive"] → Filter → Define
            → book all actions → ROOT.RDF.RunGraphs(actions)

Every call to `RunGraphs` is a **full re-read of the input files**; RDataFrame
caches nothing between event loops. Minimize the number of loops.

## Dataset normalization

For MC, use the framework's generator normalization and segmentation machinery.
Before writing custom normalization code, inspect `get_segmentation_dict(...)`,
the `report_*.json` next to the skim files, and `prepare_rdf(...)`.

Never assume that summing `weight__Central` over arbitrary input files gives the
intended normalization without checking how the dataset was prepared.

Data must never receive MC normalization.

## Central weight

Use the framework-provided `weight__Central` for the nominal event weight, unless
the task explicitly requires constructing or studying a different weight.

## Selections and categories

Mass regions currently stored: `Z_sideband, Signal_Fit, H_sideband, Signal_ext,
mass_inclusive`, plus `baseline`-style inclusive entries.

Categories include `base_sel, baseline, baseline_SS, VBF_def, VBF, ggF,
ggF_0J, ggF_1J, ggF_ge2J, VBF_ge2J`, with era-specific extras such as
`baseline_chi2`, `baseline_lowPtTT`, `baseline_chi2_lowPtTT`.

`VBF` and `ggF` are both derived from `baseline`, so anything added to `baseline`
propagates to every analysis category. Never infer exclusivity or content of a
category from its name: read `config/<era>/selections.yaml`.

Selection expressions use suffix placeholders `{mu_suff}`, `{jet_suff}`,
`{tot_suff}` which the framework substitutes per systematic variation. Keep them.

## Region/sample routing

DY and EWK, including their FlashSim variants, are routed to the mass regions
matching their generated phase space (105–160 vs inclusive) by
`config/histogram_sample_routing.yaml`. The producer applies the same rule.
Only `hist_maker.py --no-region-sample-routing` bypasses it, and only for
explicit studies.

## ROOT objects

When reading histograms from TFiles:

- verify the file is valid (`IsZombie`);
- verify the object exists before using it;
- clone histograms that must survive file closure;
- call `SetDirectory(0)` on detached histograms.

## Output

Analysis utilities should produce machine-readable output in addition to plots:
combinations of ROOT, JSON and PNG/PDF. Keep object names stable and descriptive.

Study outputs belong under `results/<study>/...`, plots under
`plots/` or the campaign's `--plot-output`. Do not write new scratch ROOT files
to the repository root.

## Coding style

For small analysis scripts:

- prefer simple functions over classes;
- avoid unnecessary abstractions;
- avoid duplicating large blocks for ggF/VBF or data/MC;
- use `pathlib.Path`;
- fail loudly on missing required inputs;
- print useful fit/sample/category summaries;
- preserve CLI compatibility when modifying an existing tool.

## Validation before finishing

At minimum:

    python3 -m py_compile <script>

When ROOT execution is available, also run a small representative test.

Never claim that a ROOT workflow was executed successfully if only syntax
validation was possible. Never claim a Condor production succeeded without
running the corresponding `check` action.

# Run 3 H→μμ analysis workflow

This is the single operational guide for the repository. It covers the full
chain:

```text
NanoAOD
  → skim production
  → skim validation
  → central and shifted histograms
  → region-dependent DY/EWK routing
  → reco/gen jet components
  → dataset-to-process hadd
  → systematic and era merging
  → plots
  → Combine datacards
```

Commands print a plan or use a dry-run whenever the tool supports it. Inspect
the plan before enabling submission or writes.

## 1. Environment

```bash
cd /afs/cern.ch/work/v/vdamante/Hmm_newSkim
source env.sh
export ANALYSIS_PATH="$PWD"

voms-proxy-init --voms cms --valid 192:00
export X509_USER_PROXY="$(voms-proxy-info -path)"
voms-proxy-info --timeleft
```

Each contributor must use their own proxy. Never share proxy files.

The standard eras are:

```bash
ERAS="Run3_2022,Run3_2022EE,Run3_2023,Run3_2023BPix,Run3_2024,Run3_2025,Run3_2026"
```

Assign one person to each era. Do not submit the same era concurrently from the
same checkout because the processes would update the same local logs and chunk
manifests.

## 2. Configuration overview

The main per-era files are:

```text
config/<ERA>/maincfg.yaml
config/<ERA>/samples.yaml
config/<ERA>/samples_withfiles.yaml
config/<ERA>/process_names.yaml
config/<ERA>/selections.yaml
config/<ERA>/systematics.yaml
config/<ERA>/skim_cfg.yaml
```

Histogram variables and binning are configured in:

```text
config/plot/histograms.yaml
```

Region-dependent sample routing and the default reco/gen component process list
are configured in:

```text
config/histogram_sample_routing.yaml
```

## 3. Refresh NanoAOD datasets and file lists

One coordinator should perform this step before production is split among
contributors.

Inspect possible NanoAOD version updates:

```bash
python3 htcondor/update_nanoaod_versions.py \
  --era "$ERAS" \
  --include-data \
  --dry-run
```

Review every proposed replacement. Apply accepted updates:

```bash
python3 htcondor/update_nanoaod_versions.py \
  --era "$ERAS" \
  --include-data \
  --in-place
```

Regenerate DAS file lists, including configured extension samples:

```bash
python3 htcondor/getfiles.py \
  --era "$ERAS" \
  --use-ext
```

Review the result:

```bash
git diff -- config/Run3_*/samples.yaml config/Run3_*/samples_withfiles.yaml
```

## 4. Skim content

The v3 skims store corrected objects and the nominal/shifted primitives needed
by histogram production. Final analysis categories are deliberately defined at
histogram level, not stored in the skim.

Important stored jet information includes:

```text
GenJet_idx
GenJet_pt
GenJet_eta
GenJet_phi
GenJet_mass
GenJet_partonFlavour
GenJet_hadronFlavour
GenJet_nBHadrons       when available
GenJet_nCHadrons       when available
Jet_genJetIdx
SelectedJet_genJetIdx and JER/JES-selected variants
```

The selected muon track-fit uncertainty is:

```text
Muon_bsConstrainedPtErr  if Muon_bsConstrainedChi2 < 30
Muon_ptErr               otherwise
```

Muon scale and resolution quantities are stored with and without FSR, including
the configured up/down variations for MC. FSR does not modify the track-fit
uncertainty itself.

## 5. Skim chunking and file names

Skim jobs group NanoAOD files deterministically, targeting at most 5 GiB and
five inputs per job. These values are configured in `skim_cfg.yaml`:

```yaml
target_chunk_size_gb: 5.0
max_files_per_chunk: 5
```

Outputs use indexed ROOT/report pairs:

```text
skim_0.root  <-> report_0.json
skim_1.root  <-> report_1.json
```

The chunk mapping is recorded in:

```text
htcondor/log/<ERA>/<DATASET>/skim_chunks.json
```

Default output:

```text
/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v3/<ERA>/<DATASET>/
```

## 6. Skim test and submission

Always test one era and one job first:

```bash
campaigns/run3_skim_v3.sh dry-run --era Run3_2024

campaigns/run3_skim_v3.sh submit \
  --era Run3_2024 \
  --max-submit-jobs 1
```

Check the queue and logs:

```bash
condor_q "$USER"
ls htcondor/log/Run3_2024/
```

After the test succeeds, submit the complete era:

```bash
campaigns/run3_skim_v3.sh submit --era Run3_2024
```

Use another writable destination when required:

```bash
campaigns/run3_skim_v3.sh submit \
  --era Run3_2024 \
  --output-dir /eos/user/X/USERNAME/skim_v3
```

Run3_2025 defaults to JEC 2025 and JER 2025. Select a different mode only when
explicitly agreed:

```bash
campaigns/run3_skim_v3.sh submit \
  --era Run3_2025
```

The alternatives are `jec2024_jer2025` and `2024`, with separate output
directories.

### Optional DY generator-binned 0J/1J/2J skims

The three generator-binned DY samples are not part of the default skim
selection. Add the required dataset keys to `datasets_whitelist` in the era's
`skim_cfg.yaml` before submitting:

```text
DYto2L_M_50_0J_amcatnloFXFX     # 2022–2023BPix
DYto2L_M_50_1J_amcatnloFXFX
DYto2L_M_50_2J_amcatnloFXFX

DYto2Mu_M_50_0J_amcatnloFXFX    # 2024–2026
DYto2Mu_M_50_1J_amcatnloFXFX
DYto2Mu_M_50_2J_amcatnloFXFX
```

Keep them separate from the inclusive DY prediction.

## 7. Skim checks and validation

The lightweight presence check is:

```bash
campaigns/run3_skim_v3.sh check --era Run3_2024
```

This is not a substitute for dataset validation. Validation:

- opens every ROOT file and checks the `Events` tree;
- parses required JSON reports;
- pairs `skim_N.root` with `report_N.json`;
- validates and pairs the produced `skim_N.root` and `report_N.json` files,
  for both data and MC;
- writes one manifest per era and dataset.

Set the agreed paths:

```bash
export SKIM_BASE=/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v3
export MANIFEST_BASE=/eos/user/v/vdamante/H_mumu/manifests_skim_v3
```

Inspect the validation plan:

```bash
bash analysis/scripts/validate.sh \
  --era Run3_2024 \
  --datasets skim_cfg \
  --root-input-folder "$SKIM_BASE" \
  --json-input-folder "$SKIM_BASE" \
  --output-dir "$MANIFEST_BASE" \
  --chunk-size 8 \
  --dry-run
```

Validate one dataset locally:

```bash
bash analysis/scripts/validate.sh \
  --era Run3_2024 \
  --dataset-name <DATASET> \
  --root-input-folder "$SKIM_BASE" \
  --json-input-folder "$SKIM_BASE" \
  --output-dir "$MANIFEST_BASE" \
  --chunk-size 8
```

Submit validation for all configured datasets:

```bash
bash analysis/scripts/validate.sh \
  --era Run3_2024 \
  --datasets skim_cfg \
  --root-input-folder "$SKIM_BASE" \
  --json-input-folder "$SKIM_BASE" \
  --output-dir "$MANIFEST_BASE" \
  --chunk-size 8 \
  --condor
```

Manifests are written to:

```text
<MANIFEST_BASE>/<ERA>/<DATASET>.json
```

Do not start histogram production while required manifests report missing
inputs, unexplained invalid files, or `status: failed`.

## 8. Histogram selections, variables, and systematics

Mass regions and categories come from `config/<ERA>/selections.yaml` and are
defined by `DefineHistogramSelections` at histogram level. This allows category
changes without regenerating skims, provided all primitive columns are present.

Common regions:

```text
Signal_Fit
Z_sideband
H_sideband
```

Common categories:

```text
baseline
ggF
VBF
ggF_0J
ggF_1J
ggF_ge2J
VBF_ge2J
```

Add or modify an observable in `config/plot/histograms.yaml`, including its
column list and binning. Request selected observables with:

```text
--variables m_mumu DNN_NNOutput N_SelectedJets
```

Central histograms use:

```text
--systematics Central
```

All configured shifted templates use:

```text
--systematics all
```

Specific families can be requested, for example:

```text
--systematics JERC Muon PU QCDScale PDF
```

Data always produces Central histograms only.

Histogram and systematic production consume all validated skim files in one
RDataFrame. `--chunk-size` controls validation workers only.

Condor submissions create one batch per physical dataset. Batch names follow
this pattern:

```text
hists/<SYSTEMATIC>_<ERA>_<DATASET>
```

For example, a central Run3 2022 DY job is grouped under
`hists/Central_Run3_2022_DYto2L_M_50_amcatnloFXFX`.

## 9. Automatic DY/EWK routing by mass region

The dedicated campaign guarantees:

| Region | DY | EWK |
|---|---|---|
| `Signal_Fit` | MLL 105–160 | MLL 105–160 Herwig |
| `Z_sideband`, `H_sideband` | generic inclusive | generic inclusive |

For Run3 2024–2026, mass-binned DY is the non-overlapping sum of:

```text
inclusive MLL 105–160     with GenVBFFilter == 0
VBF-filtered MLL 105–160  with GenVBFFilter == 1
```

For Run3 2022–2023BPix, only the available mass-binned sample is used.

The DY generator-binned 0J/1J/2J samples are produced into a separate output and
are never added automatically to inclusive DY.

Inspect one era:

```bash
campaigns/run3_region_routed_backgrounds.sh plan --era Run3_2024
```

Submit:

```bash
campaigns/run3_region_routed_backgrounds.sh submit --era Run3_2024
```

Paths and systematics can be overridden:

```bash
export SKIM_BASE=/path/to/skim_v3
export MANIFEST_BASE=/path/to/manifests_skim_v3
export OUTPUT_BASE=/path/to/RegionRouted
export SYSTEMATICS=all
```

Variables and categories can be forwarded to `hist_maker.py`:

```bash
export EXTRA_HIST_OPTS="--variables m_mumu DNN_NNOutput --categories VBF"
campaigns/run3_region_routed_backgrounds.sh plan --era Run3_2024
```

Outputs are separated into:

```text
<OUTPUT_BASE>/Signal_Fit
<OUTPUT_BASE>/Sidebands
<OUTPUT_BASE>/DY012J
```

Manual histogram commands remain available. Use dataset groups
`DY_amcatnlo`, `DY_amcatnlo_105_160`, `EWK`, `EWK_105_160`, or `DY_012J` to
override automatic routing intentionally.

## 10. Reco/gen jet 0J/1J/2J components

For MC with matching information, histogram production defines:

```text
N_PU_FirstTwoJets
RecoGenJetMatch_0J
RecoGenJetMatch_1J
RecoGenJetMatch_2J
```

`N_PU_FirstTwoJets` counts how many of the first two selected reco jets have
`genJetIdx < 0`. The boolean 0J/1J/2J flags are mutually exclusive.

Default histograms are not split into component files. Splitting is enabled
only with:

```text
--jet-gen-components
```

The allowed processes are configurable:

```text
--jet-gen-component-processes DY EWK OTHER_PROCESS
```

The region-routed campaign enables the splitting for the process list in
`config/histogram_sample_routing.yaml`.

## 10b. Splitting one dataset across parallel jobs

A campaign job covers a whole dataset, so the wall clock of an era is set by
its largest sample. Measured on `Run3_2022EE`, `AllVariables_AllWeights`,
Central: `DYto2L_M_50_amcatnloFXFX` (337 files) takes 8137 s, while every job
other than DY finishes within ~900 s.

`hist_maker.py` reads the normalization denominator from the dataset-wide
report JSONs and not from the processed ROOT files, so a subset of the files
carries the same weights as the full job. `--file-shard INDEX/TOTAL` uses this
to process only one round-robin slice of the inputs; the sum of every shard
reproduces the unsharded output bin by bin.

`tools/shard_hists.py` drives the two steps and takes the same campaign
configuration and input overrides as `campaigns/workflow.py`:

```bash
python3 tools/shard_hists.py submit --config all_variables \
    --era Run3_2022EE --dataset DYto2L_M_50_amcatnloFXFX --shards 10
python3 tools/shard_hists.py merge  --config all_variables \
    --era Run3_2022EE --dataset DYto2L_M_50_amcatnloFXFX --shards 10
```

`submit` writes into `<campaign>/<family>/shards/<dataset>/<i>_of_<N>/<era>/`,
which the campaign stages ignore. `merge` hadds the shards, including the jet
and PU component files, into `<campaign>/<family>/<era>/<dataset>.root`, i.e.
exactly the file `check`, `hadd` and the later stages expect, and refuses to
run if a shard is missing or incomplete. Use `--family` for a systematic
family, `--force` to resubmit existing shards and `--cleanup` to drop the
shard directory after a successful merge.

## 11. Read-only histogram completeness check

Given a histogram directory, list missing or zero-size per-dataset ROOT files:

```bash
./hmumu check-hists /path/to/Hists_Central --era Run3_2024
```

If the directory contains `Run3_*` subdirectories, omit `--era` to check every
discovered era:

```bash
./hmumu check-hists /path/to/Hists_Central
```

The default expected list is resolved from each era's `skim_cfg.yaml`, exactly
as in the standard campaign. For a deliberately restricted or routed
production, provide the expected datasets explicitly:

```bash
./hmumu check-hists /path/to/Signal_Fit \
  --era Run3_2024 \
  --dataset DYto2Mu_MLL_105to160_amcatnloFXFX \
  --dataset DYto2Mu_MLL_105to160_amcatnloFXFX_Fil_VBF
```

`--dataset` can be repeated or comma-separated. It accepts both physical
dataset names and configured process names: for example, `--dataset Data_Muon`
is automatically expanded to the era-dependent `Muon0_Run*` and `Muon1_Run*`
subsamples. Use `--exact --dataset Data_Muon` only when checking a post-hadd
directory expected to contain the literal file `Data_Muon.root`.

A one-name-per-line file can be passed with `--datasets-file`; use `--suffix` for outputs such as
`sample_shifted.root`, `--show-unexpected` to list extra ROOT files, and
`--json` for machine-readable output.

For a per-dataset directory, expand a configured process such as the
era-dependent data selection with:

```bash
./hmumu check-hists /path/to/Hists_Central \
  --era Run3_2024 \
  --process Data_Muon
```

The explicit `--process Data_Muon` spelling is equivalent to the automatic
process expansion performed by `--dataset Data_Muon`.

For macrogroup-oriented checks, use `--group` (the older `--process` spelling
remains accepted):

```bash
./hmumu check-hists \
  /eos/user/v/vdamante/H_mumu/campaigns/InputFeatures_VBFEta \
  --era Run3_2024 \
  --systematics Central,JERC,Muon,PU,QCDScale,ScaRe \
  --group DiTriBoson,ST,TT
```

`--group` uses the same MC macrogroup vocabulary as histogram production:
`DiTriBoson`, `DY_amcatnlo`, `DY_amcatnlo_105_160`, `EWK`, `signals`,
`SingleH`, `SingleTop`, `TTX`, `TT`, and `W`. Their era-dependent expansion is
filtered against `config/<era>/samples.yaml`. Use `--process` separately when
you explicitly want to expand one entry from `process_names.yaml`.

This command is strictly read-only: it does not submit jobs, query a submission
queue, remove files, or create reports. It exits with status 1 when at least one
expected file is absent or empty, and status 0 when the selection is complete.

To check an entire campaign in one command, pass the campaign root, era,
systematic groups, and the physical datasets expected from that production:

```bash
./hmumu check-hists \
  /eos/user/v/vdamante/H_mumu/campaigns/InputFeatures_VBFEta \
  --era Run3_2024 \
  --systematics Central,JERC,Muon,PU,QCDScale,ScaRe \
  --dataset TTto2L2Nu,TTtoLNu2Q,TTto4Q
```

Campaign mode checks, for every requested systematic:

```text
Hists_<systematic>/<era>/<dataset>.root
Hists_<systematic>_hadded/<era>/<process>.root
Hists_systMerged/<era>/<process>.root
```

The expected process names are derived from the selected datasets through
`config/<era>/process_names.yaml`. The report also lists selected
legacy `<dataset>_tmp` directories and `.failed_chunks.txt` markers. Current
histogram jobs write one dataset ROOT directly. These conditions make the
command exit with status 1. `--datasets-file` and `--json` work in campaign
mode as well.

## 12. Dataset-to-process hadd

Wait for all histogram jobs to finish and check their outputs. Then inspect the
hadd plan:

```bash
campaigns/run3_region_routed_backgrounds.sh hadd-plan --era Run3_2024
```

Run the hadd:

```bash
campaigns/run3_region_routed_backgrounds.sh hadd --era Run3_2024
```

This produces:

```text
<OUTPUT_BASE>/Signal_Fit_hadded
<OUTPUT_BASE>/Sidebands_hadded
<OUTPUT_BASE>/DY012J_hadded
```

In `Signal_Fit_hadded`, the process
`DYto2Mu_MLL105To160_combined.root` is the actual sum of the complementary
inclusive and VBF-filtered DY inputs for Run3 2024–2026. The DY012J hadded
directory remains separate.

For a generic histogram directory:

```bash
./hmumu hadd-processes \
  /path/to/per-dataset/histograms \
  --era Run3_2024 \
  --output-dir /path/to/hadded \
  --run
```

Omit `--run` to print the plan.

## 13. Merging systematic families

This step is required when Central and shifted families were produced in
separate directory trees. For example:

```bash
./hmumu merge-systematics \
  /path/to/Hists_Central \
  --systematics Central,JERC,Muon,PDF,PU,QCDScale,ScaRe \
  --era Run3_2024 \
  --output-dir /path/to/Hists_merged \
  --run
```

If Central and all requested shifts already coexist in the same per-process
ROOT files, do not merge them a second time.

Inspect each final MC ROOT file for a nominal histogram and the expected
`_<SYSTEMATIC>Up/Down` templates. Data should contain Central only.

## 14. Merging eras

Merge the 2022 and 2023 suberas after dataset-to-process and systematic merging:

```bash
./hmumu merge-eras /path/to/Hists_merged

./hmumu merge-eras \
  /path/to/Hists_merged \
  --run
```

The default output era is `Run3_2022_23`. Use `--eras` and `--output-era` for a
different combination.

## 15. Plotting

Produce one plan first:

```bash
./hmumu plot \
  --input /path/to/hadded/or/merged \
  --output plots/Run3_2024 \
  --era Run3_2024 \
  --region Signal_Fit_VBF \
  --variable DNN_NNOutput \
  --sample data_obs,DYto2Mu_MLL105To160_combined,EWK_2Mu2J_MLL_105to160_herwig
```

Add `--run` to create the plots. Omit `--variable` to use all configured
observables. Sample arguments can be ROOT filenames without `.root`, process
names, or configured plotting groups.

Before interpreting a plot, verify that it points to the region-routed hadded
directory appropriate for that mass region.

## 16. DNN performance: legacy, updated, and direct comparison

Produce the same Central histogram selection twice, changing only the model
set and keeping binning, samples, weights, region, and cuts identical:

```bash
./hmumu hist \
  --era Run3_2024 \
  --datasets skim_cfg \
  --systematics Central \
  --variable DNN_NNOutput \
  --dnn-model-set legacy \
  --output-dir /path/to/DNN_legacy/Hists_Central \
  --run

./hmumu hist \
  --era Run3_2024 \
  --datasets skim_cfg \
  --systematics Central \
  --variable DNN_NNOutput \
  --dnn-model-set updated \
  --output-dir /path/to/DNN_updated/Hists_Central \
  --run
```

Check both directories with `check-hists`, then run:

```bash
python3 dnn_performance/compare_performance.py \
  --campaign old=/path/to/DNN_legacy \
  --campaign new=/path/to/DNN_updated \
  --era Run3_2024 \
  --region Signal_Fit_VBF/incl \
  --variable DNN_NNOutput \
  --signal-pattern '*VBFHto2Mu*' \
  --background-pattern '*' \
  --output results/dnn_Run3_2024
```

The JSON contains separate `old` and `new` results plus a `comparison` block.
For each network it records ROC/AUC, yields after negative-bin handling, the
best `S/sqrt(S+B)` threshold, and background efficiency at fixed signal
efficiencies. The comparison records the AUC and best-significance changes and
the reduction in background efficiency at each working point. The PNG overlays
both ROC and significance curves.

The default signal-efficiency working points are 0.50, 0.70, 0.80, and 0.90.
Override them by repeating, for example, `--working-point 0.70
--working-point 0.85`. Patterns select per-dataset ROOT filenames; data and
alternate `Hto2Mu` samples are excluded from the default background. Always
inspect the `signal_files` and `background_files` recorded in the JSON before
quoting the comparison.

## 17. Datacard inputs

Datacards must use the final per-process ROOT files after:

```text
dataset hadd
→ systematic merge, when needed
→ era merge, when needed
```

For the VBF signal channel, the expected nominal shape path is typically:

```text
Signal_Fit_VBF/DNN_NNOutput
```

Shifted shapes follow:

```text
Signal_Fit_VBF/DNN_NNOutput_<SYSTEMATIC>Up
Signal_Fit_VBF/DNN_NNOutput_<SYSTEMATIC>Down
```

Before writing cards, check:

- `data_obs.root` exists;
- every declared signal/background process ROOT file exists;
- the nominal histogram exists for every process;
- all declared shape nuisances have matching Up/Down histograms;
- DY points to `DYto2Mu_MLL105To160_combined.root` in `Signal_Fit`;
- generic DY is not also included in `Signal_Fit`;
- DY012J files are included only in a deliberately separate model;
- rates are non-negative and finite.

The current writer is:

```bash
python3 combine/CombineCardWriter.py <YEAR>
```

Before using it, review and update its input/output paths, channel list,
signal/background process lists, and luminosity configuration. It is currently
a channel-specific writer rather than a fully generic campaign driver.

Its nuisance inputs are:

```text
combine/datacard_uncertainties.yaml
combine/theory_uncertainties.yaml
config/<ERA>/systematics.yaml
```

After creating a card, validate it in a Combine environment:

```bash
text2workspace.py card.txt -o workspace.root
combine -M FitDiagnostics workspace.root
```

Do not proceed when Combine reports missing shapes, duplicate processes,
non-finite rates, or inconsistent nuisance templates.

## 18. Final campaign checklist

- NanoAOD paths reviewed and file lists regenerated.
- One skim job tested successfully.
- Full skim era completed.
- ROOT/report pairs present.
- Dataset validation manifests passed.
- Central and requested shifted histograms completed.
- Histogram directories passed the read-only completeness check.
- Signal and sideband sample routing checked.
- Reco/gen component outputs enabled only where intended.
- DY012J kept separate.
- Dataset-to-process hadd completed.
- Inclusive and VBF-filtered DY combined only through the orthogonal cuts.
- Systematic and era merges completed where required.
- Final plots inspected.
- Legacy and updated DNN performance compared on identical samples and cuts.
- Datacard shapes and nuisances validated.
- Paths, commit, responsible person, failures, and exclusions recorded.

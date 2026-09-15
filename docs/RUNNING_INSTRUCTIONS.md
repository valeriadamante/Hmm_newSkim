# Detailed Running Guide

This file is the detailed command archive for skims, histogram production, hadd, and plots.
For a shorter quick-start guide, use `readme.md`.

## Setup

Always start from the repository root:

```bash
cd /afs/cern.ch/work/v/vdamante/Hmm_newSkim
source env.sh
```

For EOS/XRootD access, make sure you have a valid CMS proxy:

```bash
voms-proxy-init --rfc --voms cms -valid 192:00
voms-proxy-info
```

For Condor runs, the worker executable sources `env.sh` inside the job. Do not rely on the submit shell environment being propagated.

## Script Interfaces

### `analysis/skim.py`

```bash
python3 analysis/skim.py \
  --era ERA \
  --dataset-name DATASET \
  --input-file INPUT.root \
  --output-file OUTPUT.root \
  --want-variations\
  --n-events 1000
```

Required:

```text
--era
--dataset-name
--input-file
--output-file
```

Use `--want-variations` for MC systematic variations. It has no effect for data.

### `histograms/hist_maker.py`

```bash
python3 histograms/hist_maker.py \
  --era ERA \
  --dataset-name DATASET \
  --input INPUT_DIR_OR_FILE \
  --output-file OUTPUT.root \
  --variables VAR [VAR ...] \
  --mass-regions REGION [REGION ...] \
  --categories CATEGORY [CATEGORY ...] \
  --skip-file-validation
```

Common options:

```text
--systematics central|all
--rdf-threads N
--variables VAR [VAR ...]
--mass-regions REGION [REGION ...]
--categories CATEGORY [CATEGORY ...]
--additional-cuts "CUT"
--dryrun
--shift-z-sideband-dnn-mass
```

Defaults:

```text
--systematics central
--rdf-threads 1
--mass-regions mass_inclusive Z_sideband Signal_Fit
--categories baseline ggF VBF
```

If `--variables` is omitted, variables are read from `config/<ERA>/maincfg.yaml`.

Histogram selections are defined in `common/add_vars.py`. Special
reco/gen jet matching is isolated in `common/jet_component_splitting.py`, while
the sideband dimuon-mass remapping and shifted DNN evaluation are implemented
in `histograms/dnn_histogram_production.py`. `hist_maker.py` only orchestrates
dataframes and histogram booking.

Validation manifests are written, read, and resolved atomically through
`common/utilities.py`.

### `plotting_tools/hist_plotter.py`

```bash
python3 plotting_tools/hist_plotter.py \
  --era ERA \
  --input HaddedHistDirectory \
  --output OUTPUT_DIR \
  --region REGION_CATEGORY \
  --samples SAMPLE_OR_GROUP [SAMPLE_OR_GROUP ...] \
  --vars VAR1,VAR2 \
  --wantData \
  --wantLogY \
  --rebin
```

Common options:

```text
--region REGION_CATEGORY
--samples SAMPLE_OR_GROUP [SAMPLE_OR_GROUP ...]
--vars VAR1,VAR2
--variables VAR1,VAR2
--wantData
--wantLogY
--rebin
--systematics
--stack
--no-stack
--fill-hists
--no-fill-hists
--ratio-reference SAMPLE_OR_GROUP
--normalize-dy-to-data
--normalize-mc-to-data
--dy-normalization-sample SAMPLE_OR_GROUP
```

Sample names can be ROOT filenames without `.root`, process names from `config/<ERA>/process_names.yaml`, or plotting groups from `config/plot/process_groups.yaml`.

## Local Skim Smoke Tests

Use these to test one NanoAOD file before submitting a full skim campaign.

### Run3_2022

DY:

```bash
python3 analysis/skim.py \
  --era Run3_2022 \
  --dataset-name DYto2L_M_50_amcatnloFXFX \
  --input-file root://cms-xrd-global.cern.ch//store/mc/Run3Summer22NanoAODv12/DYto2L-2Jets_MLL-50_TuneCP5_13p6TeV_amcatnloFXFX-pythia8/NANOAODSIM/130X_mcRun3_2022_realistic_v5-v5/120000/0c8aebb5-2c48-4980-97bd-8ebe1f64b649.root \
  --output-file test_skim_Run3_2022_DY.root \
  --want-variations\
  --n-events 1000
```

VBF signal:

```bash
python3 analysis/skim.py \
  --era Run3_2022 \
  --dataset-name VBFHto2Mu_M125_powheg \
  --input-file root://cms-xrd-global.cern.ch//store/mc/Run3Summer22NanoAODv12/VBFHto2Mu_M-125_TuneCP5_withDipoleRecoil_13p6TeV_powheg-pythia8/NANOAODSIM/130X_mcRun3_2022_realistic_v5-v3/50000/513eb3b4-a163-4449-8d36-96eb1b8333d0.root \
  --output-file test_skim_Run3_2022_VBF.root \
  --want-variations\
  --n-events 1000
```

Data:

```bash
python3 analysis/skim.py \
  --era Run3_2022 \
  --dataset-name Muon_Run2022C \
  --input-file root://cms-xrd-global.cern.ch//store/data/Run2022C/Muon/NANOAOD/22Sep2023-v1/30000/246cec4e-0b5f-4946-b4ea-d4286a5ef78c.root \
  --output-file test_skim_Run3_2022_data.root
```

### Run3_2022EE

DY:

```bash
python3 analysis/skim.py \
  --era Run3_2022EE \
  --dataset-name DYto2L_M_50_amcatnloFXFX \
  --input-file root://cms-xrd-global.cern.ch//store/mc/Run3Summer22EENanoAODv12/DYto2L-2Jets_MLL-50_TuneCP5_13p6TeV_amcatnloFXFX-pythia8/NANOAODSIM/130X_mcRun3_2022_realistic_postEE_v6-v5/2560000/aafcad2c-38ed-4a1f-b206-380f9b9ef39c.root \
  --output-file test_skim_Run3_2022EE_DY.root \
  --want-variations\
  --n-events 1000
```

VBF signal:

```bash
python3 analysis/skim.py \
  --era Run3_2022EE \
  --dataset-name VBFHto2Mu_M125_powheg \
  --input-file root://cms-xrd-global.cern.ch//store/mc/Run3Summer22EENanoAODv12/VBFHto2Mu_M-125_TuneCP5_withDipoleRecoil_13p6TeV_powheg-pythia8/NANOAODSIM/130X_mcRun3_2022_realistic_postEE_v6-v3/50000/400d66cf-4f82-4b91-bd14-058551fcbdf0.root \
  --output-file test_skim_Run3_2022EE_VBF.root \
  --want-variations\
  --n-events 1000
```

Data:

```bash
python3 analysis/skim.py \
  --era Run3_2022EE \
  --dataset-name Muon_Run2022E \
  --input-file root://cms-xrd-global.cern.ch//store/data/Run2022E/Muon/NANOAOD/22Sep2023-v1/30000/4b0c8ae0-6947-4cf3-a214-ae279c22d0f3.root \
  --output-file test_skim_Run3_2022EE_data.root
```

### Run3_2023

DY:

```bash
python3 analysis/skim.py \
  --era Run3_2023 \
  --dataset-name DYto2L_M_50_amcatnloFXFX \
  --input-file root://cms-xrd-global.cern.ch//store/mc/Run3Summer23NanoAODv12/DYto2L-2Jets_MLL-50_TuneCP5_13p6TeV_amcatnloFXFX-pythia8/NANOAODSIM/130X_mcRun3_2023_realistic_v14-v2/2560000/217e139b-1edd-407c-a47a-7ccf1f478f21.root \
  --output-file test_skim_Run3_2023_DY.root \
  --want-variations\
  --n-events 1000
```

VBF signal:

```bash
python3 analysis/skim.py \
  --era Run3_2023 \
  --dataset-name VBFHto2Mu_M125_powheg \
  --input-file root://cms-xrd-global.cern.ch//store/mc/Run3Summer23NanoAODv12/VBFHto2Mu_M-125_TuneCP5_13p6TeV_powheg-pythia8/NANOAODSIM/130X_mcRun3_2023_realistic_v15-v2/2820000/9ca3d426-b323-4062-b4f8-83d4febdedc2.root \
  --output-file test_skim_Run3_2023_VBF.root \
  --want-variations\
  --n-events 1000
```

Data:

```bash
python3 analysis/skim.py \
  --era Run3_2023 \
  --dataset-name Muon1_Run2023C_v1 \
  --input-file root://cms-xrd-global.cern.ch//store/data/Run2023C/Muon1/NANOAOD/22Sep2023_v1-v1/30000/d93b0737-8e8a-4276-aae3-338423b4d3d9.root \
  --output-file test_skim_Run3_2023_data.root \
  --n-events 1000
```

### Run3_2023BPix

DY:

```bash
python3 analysis/skim.py \
  --era Run3_2023BPix \
  --dataset-name DYto2L_M_50_amcatnloFXFX \
  --input-file root://cms-xrd-global.cern.ch//store/mc/Run3Summer23BPixNanoAODv12/DYto2L-2Jets_MLL-50_TuneCP5_13p6TeV_amcatnloFXFX-pythia8/NANOAODSIM/130X_mcRun3_2023_realistic_postBPix_v2-v4/130000/382cb2db-a7b7-4189-912f-9507a1369cb0.root \
  --output-file test_skim_Run3_2023BPix_DY.root \
  --want-variations\
  --n-events 1000
```

VBF signal:

```bash
python3 analysis/skim.py \
  --era Run3_2023BPix \
  --dataset-name VBFHto2Mu_M125_powheg \
  --input-file root://cms-xrd-global.cern.ch//store/mc/Run3Summer23BPixNanoAODv12/VBFHto2Mu_M-125_TuneCP5_13p6TeV_powheg-pythia8/NANOAODSIM/130X_mcRun3_2023_realistic_postBPix_v6-v2/2820000/d642783e-b4e1-4de7-a963-f009cce1a5c6.root \
  --output-file test_skim_Run3_2023BPix_VBF.root \
  --want-variations\
  --n-events 1000
```

Data:

```bash
python3 analysis/skim.py \
  --era Run3_2023BPix \
  --dataset-name Muon0_Run2023D_v1 \
  --input-file root://cms-xrd-global.cern.ch//store/data/Run2023D/Muon0/NANOAOD/22Sep2023_v1-v1/2530000/dd9c19c9-84b4-47e1-bc42-34320f55faba.root \
  --output-file test_skim_Run3_2023BPix_data.root \
  --n-events 1000
```

### Run3_2024

DY MLL 105-160 VBF-filtered:

```bash
python3 analysis/skim.py \
  --era Run3_2024 \
  --dataset-name DYto2Mu_MLL_105to160_amcatnloFXFX_Fil_VBF \
  --input-file /eos/cms/store/mc/RunIII2024Summer24NanoAODv15/DYto2Mu-2Jets_Bin-MLL-105to160_Fil-VBF_TuneCP5_13p6TeV_amcatnloFXFX-pythia8/NANOAODSIM/150X_mcRun3_2024_realistic_v2-v2/2550000/1fd2212e-9830-4f43-b30c-85d553bae434.root \
  --output-file test_skim_Run3_2024_DY_VBFFil.root \
  --want-variations\
  --n-events 1000
```

VBF signal:

```bash
python3 analysis/skim.py \
  --era Run3_2024 \
  --dataset-name VBFHto2Mu_M125_powheg \
  --input-file root://cms-xrd-global.cern.ch//store/mc/RunIII2024Summer24NanoAODv15/VBFH-Hto2Mu_Par-M-125_TuneCP5_13p6TeV_powheg-pythia8/NANOAODSIM/150X_mcRun3_2024_realistic_v2-v2/100000/f05fbcb1-50b6-4d4e-9923-19678675ee4a.root \
  --output-file test_skim_Run3_2024_VBF.root \
  --want-variations\
  --n-events 1000
```

Data:

```bash
python3 analysis/skim.py \
  --era Run3_2024 \
  --dataset-name Muon1_Run2024F \
  --input-file root://cms-xrd-global.cern.ch//store/data/Run2024F/Muon1/NANOAOD/MINIv6NANOv15-v1/2530000/c3aef71c-8e37-4fe5-8e38-d06a80a3a242.root \
  --output-file test_skim_Run3_2024_data.root \
  --n-events 1000
```

### Run3_2025


DY MiNNLO:

```bash
python3 analysis/skim.py \
  --era Run3_2025 \
  --dataset-name DYto2Mu_MLL_130to200_powheg_minnlo \
  --input-file /eos/cms/store/mc/RunIII2024Summer24NanoAODv15/DYto2Mu_Bin-MLL-130to200_TuneCP5_13p6TeV_powhegMINNLO-pythia8-photos/NANOAODSIM/150X_mcRun3_2024_realistic_v2-v2/2550000/0b38634f-b9db-4e85-b992-1035e1250b1c.root \
  --output-file test_skim_Run3_2025_DY_minnlo.root \
  --want-variations\
  --n-events 1000
```

VBF signal:

```bash
python3 analysis/skim.py \
  --era Run3_2025 \
  --dataset-name VBFHto2Mu_M125_amcatnlo \
  --input-file /eos/cms/store/mc/RunIII2024Summer24NanoAODv15/VBF-Hto2Mu_Par-M-125_TuneCP5_13p6TeV_amcatnlo-pythia8/NANOAODSIM/150X_mcRun3_2024_realistic_v2-v2/2560000/003ede9b-bb5c-485e-9080-e73badd1530a.root \
  --output-file test_skim_Run3_2025_VBF.root \
  --want-variations\
  --n-events 1000
```

Data:

```bash
python3 analysis/skim.py \
  --era Run3_2025 \
  --dataset-name Muon0_Run2025C_v2 \
  --input-file root://cms-xrd-global.cern.ch//store/data/Run2025C/Muon0/NANOAOD/PromptReco-v2/000/393/461/00000/9b293a67-d80f-40e3-a4d3-dd1348ed082b.root \
  --output-file test_skim_Run3_2025_data.root \
  --n-events 1000
```

### Run3_2026

DY MLL 105-160 VBF-filtered:

```bash
python3 analysis/skim.py \
  --era Run3_2026 \
  --dataset-name DYto2Mu_MLL_105to160_amcatnloFXFX_Fil_VBF \
  --input-file root://cms-xrd-global.cern.ch//store/mc/RunIII2024Summer24NanoAODv15/DYto2Mu-2Jets_Bin-MLL-105to160_Fil-VBF_TuneCP5_13p6TeV_amcatnloFXFX-pythia8/NANOAODSIM/150X_mcRun3_2024_realistic_v2-v2/2550000/1fd2212e-9830-4f43-b30c-85d553bae434.root \
  --output-file test_skim_Run3_2026_DY_VBFFil.root \
  --want-variations\
  --n-events 1000
```

VBF signal:

```bash
python3 analysis/skim.py \
  --era Run3_2026 \
  --dataset-name VBFHto2Mu_M125_powheg \
  --input-file root://cms-xrd-global.cern.ch//store/mc/RunIII2024Summer24NanoAODv15/VBFH-Hto2Mu_Par-M-125_TuneCP5_13p6TeV_powheg-pythia8/NANOAODSIM/150X_mcRun3_2024_realistic_v2-v2/100000/f05fbcb1-50b6-4d4e-9923-19678675ee4a.root \
  --output-file test_skim_Run3_2026_VBF.root \
  --want-variations\
  --n-events 1000
```

Data:

```bash
python3 analysis/skim.py \
  --era Run3_2026 \
  --dataset-name Muon3_Run2026C_v1 \
  --input-file root://cms-xrd-global.cern.ch//store/data/Run2026C/Muon3/NANOAOD/PromptReco-v1/000/403/244/00000/d0a9a784-fa70-4ed9-b630-59d5b6703bbf.root \
  --output-file test_skim_Run3_2026_data.root
```

## Skim Campaigns

Check missing skim outputs for one era:

```bash
python3 htcondor/check_missing_files.py -e Run3_2024 --only-missing
```

Write missing-file lists:

```bash
python3 htcondor/check_missing_files.py -e Run3_2024 --only-missing --write-missing
```

Check all eras:

```bash
for era in Run3_2022 Run3_2022EE Run3_2023 Run3_2023BPix Run3_2024 Run3_2025 Run3_2026; do
  python3 htcondor/check_missing_files.py -e ${era} --only-missing
done
```

Dry-run skim submission:

```bash
python3 htcondor/condorsubmit.py -e Run3_2024 --no-submit
```

Submit one era:

```bash
python3 htcondor/condorsubmit.py -e Run3_2024
```

Submit one era with queue limit:

```bash
python3 htcondor/condorsubmit.py \
  -e Run3_2024 \
  --max-parallel-jobs 5000 \
  --poll-interval 120
```

Submit at most a few skim jobs for testing:

```bash
python3 htcondor/condorsubmit.py -e Run3_2024 --max-submit-jobs 10
```

Main skim output:

```text
/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v3/<ERA>/<DATASET>/
```

Condor skim logs:

```text
htcondor/output/<ERA>/<DATASET>/
htcondor/error/<ERA>/<DATASET>/
htcondor/log/<ERA>/<DATASET>/
```

### skim_v4 productions

`htcondor/condorsubmit.py` above is the skim_v3 entry point. skim_v4 is driven by
`campaigns/run3_skim_v4.sh`, which resolves the missing chunks per era and
variant before queueing anything:

```bash
bash campaigns/run3_skim_v4.sh plan      # print the commands only
bash campaigns/run3_skim_v4.sh dry-run   # resolve the missing chunks
bash campaigns/run3_skim_v4.sh submit --era Run3_2024
```

Default output base is
`/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4`; 2025 and 2026 also
produce the `noHornVeto`/`noJetHornVeto` variants. Condor logs and the per-era
bookkeeping (`skim_chunks.json`, `completed_files.txt`, `failed_jobs_report.txt`,
`missing_files_dryrun.txt`) land under `htcondor/skim_v4*/` and are not tracked.

### Validating a skim production

The existence check used by the submitter is not sufficient: a job killed after
the `Snapshot` leaves a full `.root` with no `report_*.json`, and a truncated
file still opens but holds fewer events than its report declares.
`tools/validate_skim.py` catches both:

```bash
python3 tools/validate_skim.py \
  --era Run3_2024 \
  --input /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4 \
  --state-dir htcondor/skim_v4 \
  --output validation_2024.json \
  --jobs 16
```

Restrict it with `--datasets NAME [NAME ...]` while iterating.

### Patching a production you cannot overwrite

When the base production belongs to another user and the EOS ACL
(`egroup:...:rw!d`) forbids overwriting it, reproduce the broken chunks into a
separate patch directory and build a view that substitutes them:

```bash
python3 tools/build_skim_overlay.py \
  --era Run3_2024 \
  --base /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4 \
  --patch /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4_patch \
  --output /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4_overlay \
  --state-dir htcondor/skim_v4 \
  --run
```

Without `--run` the tool only prints what it would link. `--blacklist FILE` is
repeatable and drops known-bad chunks from the view.

## Local Histogram Smoke Tests

`hist_maker.py` accepts either one skim ROOT file or a directory of skim ROOT files.

### Per-era template commands

Run3_2022:

```bash
python3 histograms/hist_maker.py \
  --era Run3_2022 \
  --dataset-name DYto2L_M_50_amcatnloFXFX \
  --input /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v3/Run3_2022/DYto2L_M_50_amcatnloFXFX/FILE_skim.root \
  --output-file test_hists_Run3_2022.root \
  --skip-file-validation
```

Run3_2022EE:

```bash
python3 histograms/hist_maker.py \
  --era Run3_2022EE \
  --dataset-name DYto2L_M_50_amcatnloFXFX \
  --input /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v3/Run3_2022EE/DYto2L_M_50_amcatnloFXFX/FILE_skim.root \
  --output-file test_hists_Run3_2022EE.root \
  --skip-file-validation
```

Run3_2023:

```bash
python3 histograms/hist_maker.py \
  --era Run3_2023 \
  --dataset-name DYto2L_M_50_amcatnloFXFX \
  --input /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v3/Run3_2023/DYto2L_M_50_amcatnloFXFX/FILE_skim.root \
  --output-file test_hists_Run3_2023.root \
  --skip-file-validation
```

Run3_2023BPix:

```bash
python3 histograms/hist_maker.py \
  --era Run3_2023BPix \
  --dataset-name DYto2L_M_50_amcatnloFXFX \
  --input /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v3/Run3_2023BPix/DYto2L_M_50_amcatnloFXFX/FILE_skim.root \
  --output-file test_hists_Run3_2023BPix.root \
  --skip-file-validation
```

Run3_2024:

```bash
python3 histograms/hist_maker.py \
  --era Run3_2024 \
  --dataset-name DYto2Mu_M_50_amcatnloFXFX \
  --input /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v3/Run3_2024/DYto2Mu_M_50_amcatnloFXFX/FILE_skim.root \
  --output-file test_hists_Run3_2024.root \
  --skip-file-validation
```

Run3_2025:

```bash
python3 histograms/hist_maker.py \
  --era Run3_2025 \
  --dataset-name DYto2Mu_M_50_amcatnloFXFX \
  --input /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v3/Run3_2025/DYto2Mu_M_50_amcatnloFXFX/FILE_skim.root \
  --output-file test_hists_Run3_2025.root \
  --skip-file-validation
```

Run3_2026:

```bash
python3 histograms/hist_maker.py \
  --era Run3_2026 \
  --dataset-name DYto2Mu_M_50_amcatnloFXFX \
  --input /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v3/Run3_2026/DYto2Mu_M_50_amcatnloFXFX/FILE_skim.root \
  --output-file test_hists_Run3_2026.root \
  --skip-file-validation
```

### Single-variable/category tests

Only `DNN_NNOutput` in Signal Fit VBF:

```bash
dataset_name=VBFHto2Mu_M125_powheg

python3 histograms/hist_maker.py \
  --era Run3_2024 \
  --dataset-name ${dataset_name} \
  --input /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v3/Run3_2024/${dataset_name}/ \
  --output-file test_DNN_${dataset_name}_SignalFit_VBF.root \
  --variables DNN_NNOutput \
  --mass-regions Signal_Fit \
  --categories VBF \
  --skip-file-validation
```

Only `DNN_NNOutput` in Z sideband categories:

```bash
dataset_name=GluGluHto2Mu

python3 histograms/hist_maker.py \
  --era Run3_2022 \
  --dataset-name ${dataset_name} \
  --input /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v3/Run3_2022/${dataset_name}/ \
  --output-file prova_DNN_NNOutput_${dataset_name}.root \
  --variables DNN_NNOutput \
  --mass-regions Z_sideband \
  --categories baseline ggF VBF \
  --skip-file-validation
```

## Histogram Campaigns with Condor

### Standard variable, DNN, and jet-multiplicity campaigns

The dedicated launcher covers the three common productions:

```bash
bash campaigns/run3_variables_dnn_jetmultiplicity.sh PROFILE MODE ACTION
```

Profiles:

```text
variables          all variables from config/<ERA>/maincfg.yaml
dnn                only DNN_NNOutput
jet-multiplicity   maincfg variables in ggF_0J, ggF_1J, ggF_ge2J,
                   and VBF_ge2J for DY, EWK, ggH->mumu, and VBFH->mumu
all                all three profiles
```

Always inspect the plan before submission:

```bash
bash campaigns/run3_variables_dnn_jetmultiplicity.sh all condor plan
```

Submit a single profile and then monitor its completeness:

```bash
bash campaigns/run3_variables_dnn_jetmultiplicity.sh dnn condor run
bash campaigns/run3_variables_dnn_jetmultiplicity.sh dnn condor check
```

Jet-multiplicity production:

```bash
bash campaigns/run3_variables_dnn_jetmultiplicity.sh \
  jet-multiplicity condor run
```

The `signals` campaign group used by the last profile contains the configured
ggH-to-mumu and VBFH-to-mumu datasets. The other requested groups are
`DY_amcatnlo`, `DY_amcatnlo_105_160`, and `EWK`.

Input, manifest, and output locations can be overridden without editing the
script:

```bash
INPUT_DIR=/eos/... \
MANIFESTS=/eos/... \
OUTPUT_BASE=/eos/user/... \
bash campaigns/run3_variables_dnn_jetmultiplicity.sh variables condor plan
```

The preferred histogram submitter is:

```bash
python3 htcondor/condorsubmit.py histograms
```

It writes a jobs table and Condor submit file under:

```text
htcondor/hists/<ERA>_<SUFFIX>_<GROUP>_<TIMESTAMP>/
```

### Groups

Main groups:

```text
data
DiTriBoson
DY_amcatnlo
DY_amcatnlo_105_160
DY_amcatnlo_105_160_stitched
DY_amcatnlo_105_160_VBFFil
DY_minnlo
EWK
signals
other_signals
SingleH
SingleTop
TTX
W
```

Default groups for 2024, 2025, and 2026:

```text
DiTriBoson
data
DY_amcatnlo
DY_amcatnlo_105_160_VBFFil
DY_minnlo
signals
SingleH
SingleTop
TTX
W
DY_amcatnlo_105_160
DY_amcatnlo_105_160_stitched
other_signals
EWK
```

Default groups for 2022, 2022EE, 2023, and 2023BPix:

```text
DiTriBoson
data
EWK
DY_amcatnlo
DY_amcatnlo_105_160
signals
SingleH
SingleTop
TTX
W
other_signals
```

### Submit examples

One era, one group:

```bash
python3 htcondor/condorsubmit.py histograms \
  --era Run3_2024 \
  --datasets DY_amcatnlo \
  --condor \
  --missing-only \
  --max-parallel-jobs 5000 \
  -- --skip-file-validation
```

One explicit dataset:

```bash
python3 htcondor/condorsubmit.py histograms \
  --era Run3_2024 \
  --dataset-name TTto2L2Nu \
  --chunk-size 10 \
  --condor \
  --missing-only \
  --max-parallel-jobs 5000 \
  -- --skip-file-validation
```

All Run 3 eras:

```bash
python3 htcondor/condorsubmit.py histograms \
  --era all \
  --condor \
  --missing-only \
  --max-parallel-jobs 5000 \
  -- --skip-file-validation
```

2024, 2025, 2026:

```bash
python3 htcondor/condorsubmit.py histograms \
  --era Run3_2024,Run3_2025,Run3_2026 \
  --condor \
  --missing-only \
  --max-parallel-jobs 5000 \
  -- --skip-file-validation
```

Dry-run:

```bash
python3 htcondor/condorsubmit.py histograms \
  --era Run3_2024 \
  --datasets EWK \
  --condor \
  --dry-run \
  -- --skip-file-validation
```

Monitor only:

```bash
python3 htcondor/condorsubmit.py histograms \
  --era Run3_2024 \
  --datasets EWK \
  --monitor \
  -- --skip-file-validation
```

Continuous monitor plus refill:

```bash
python3 htcondor/condorsubmit.py histograms \
  --era Run3_2024 \
  --watch \
  --missing-only \
  --max-parallel-jobs 5000 \
  --poll-interval 120 \
  -- --skip-file-validation
```

Submit at most one job for testing:

```bash
python3 htcondor/condorsubmit.py histograms \
  --era Run3_2024 \
  --datasets EWK \
  --condor \
  --missing-only \
  --max-submit-jobs 1 \
  --output-suffix _test \
  -- --skip-file-validation
```

### Passing options to `hist_maker.py`

Put `hist_maker.py` options after a standalone `--`:

```bash
python3 htcondor/condorsubmit.py histograms \
  --era Run3_2024 \
  --datasets signals \
  --condor \
  --dry-run \
  -- \
  --variables DNN_NNOutput \
  --mass-regions Z_sideband \
  --categories ggF_0J ggF_1J ggF_ge2J VBF_ge2J \
  --skip-file-validation
```

Do not use:

```bash
--hist_opts "--categories ggF_0J ggF_1J"
```

There is no `--hist_opts` parser option in the histogram submitter.

Also make sure the line-continuation backslash has no trailing space:

```bash
--dry-run \
```

not:

```bash
--dry-run \
```

## Hadd Histograms

One era:

```bash
era=Run3_2024

python3 histograms/hadd_hists_to_processes.py \
  --input-dir /eos/user/v/vdamante/H_mumu/newHists_${era}/ \
  --output-dir /eos/user/v/vdamante/H_mumu/newHists_${era}_hadded/ \
  --era ${era}
```

All eras:

```bash
for era in Run3_2022 Run3_2022EE Run3_2023 Run3_2023BPix Run3_2024 Run3_2025 Run3_2026; do
  python3 histograms/hadd_hists_to_processes.py \
    --input-dir /eos/user/v/vdamante/H_mumu/newHists_${era}/ \
    --output-dir /eos/user/v/vdamante/H_mumu/newHists_${era}_hadded/ \
    --era ${era}
done
```

With suffix:

```bash
era=Run3_2024
suffix=TT

python3 histograms/hadd_hists_to_processes.py \
  --input-dir /eos/user/v/vdamante/H_mumu/newHists_${era}${suffix}/ \
  --output-dir /eos/user/v/vdamante/H_mumu/newHists_${era}${suffix}_hadded/ \
  --era ${era}
```

Dry-run:

```bash
python3 histograms/hadd_hists_to_processes.py \
  --input-dir /eos/user/v/vdamante/H_mumu/newHists_Run3_2024/ \
  --output-dir /eos/user/v/vdamante/H_mumu/newHists_Run3_2024_hadded/ \
  --era Run3_2024 \
  --dryRun
```

## DY pt(ll) And NJets Reweighting JSON

There are two independent DY reweights:

- `pt(ll)`: evaluated with `isVBF`, `N_selectedJets`, and `ptll`
- `NJets`: evaluated with `isVBF` and `nSelectedJets`

The intended nominal workflow is sequential:

1. derive the `pt(ll)` JSON from un-reweighted histograms;
2. produce the `N_SelectedJets` histograms with the `pt(ll)` JSON already
   applied to DY;
3. derive the `NJets` JSON from those pt(ll)-reweighted histograms;
4. produce the final histograms with both the `pt(ll)` and `NJets` JSONs
   applied to DY.

If both JSON arguments are passed to `hist_maker.py`, the two factors are
multiplied into the DY event weights. The implementation applies these weights
to DY datasets only. EWK is not reweighted by these options; applying the same
factors to EWK would be a separate physics choice and would require a dedicated
code/config change.

The JSON files are correctionlib-style `CorrectionSet`s. Use `isVBF=1` for VBF
and `isVBF=0` for ggF when evaluating them directly with correctionlib.

### Where the payloads come from

Every payload location lives in `config/<era>/process_names.yaml`, under the
`reweight_jsons` block of the DY process entry:

```yaml
  reweight_jsons: &dy_reweight_jsons
    ptll_njets: reweights/dy_ptll_reweight_skim_v4/Run3_2022/dy_ptll_reweight_smart.json
    njets: reweights/dy_njets_reweight_skim_v4/Run3_2022/dy_njets_reweight.json
    jet_component: reweights/dy_012j_reweight_skim_v4/Run3_2022/dy_012j_reweight.json
```

There is no hard-coded fallback in the code. `prepare_rdf` forwards
`reweight_jsons` to `apply_custom_weights`; when a caller leaves it `None`,
`reweight_json_paths` reads the block back from that YAML (entry of the process
owning the dataset, falling back to `DY`) and prints where it took it from. A
key that is not configured raises `KeyError` and a configured file that is
missing raises `FileNotFoundError`, both naming the config file. Payload
locations therefore only ever change by editing the era configuration.

`--no-custom-weights` still applies the DY amcatnlo normalization
(`ApplyDYAmcatnloNormalization`) and only skips the three reweights.

### One payload per era

Each era points at its own payload. `campaigns/workflow.py:fit_groups` derives
the fit grouping from those paths rather than from a hard-coded era pairing:
eras configured to share one JSON are fitted together from their combined
inputs, eras with their own JSON are fitted alone. Selecting only part of a
shared group is rejected, because that would fit a shared payload from partial
inputs.

The per-era fits are not a cosmetic split. For the 012j weights the pile-up
components differ substantially between 2022 and 2022EE, and the combined fit
was dominated by the larger era:

| component | Run3_2022 | Run3_2022EE | combined |
|---|---:|---:|---:|
| 1JPU / 2JPU | 0.8159 | 0.5082 | 0.5511 |
| VBFPU1 | 0.7211 | 0.2917 | 0.3867 |
| VBFHard | 0.7760 | 0.7088 | 0.7561 |
| 0J | 1.0372 | 1.0552 | 1.0511 |

### Selecting the stage

`--dy-weights` enables exactly the listed reweights and disables the others,
so intermediate stages are requested explicitly instead of editing a campaign:

```bash
bash campaigns/<campaign>.sh submit --dy-weights jet-component
bash campaigns/<campaign>.sh submit --dy-weights jet-component,ptll
bash campaigns/<campaign>.sh submit --dy-weights ''      # disable all three
```

The DY-weight workflow itself takes `--weight-stage {all,jet,ptll,njets}` and
the extra actions `run`, `fit` and `check-weights`.

### PU1 and PU2 in the 012j fit

`tools/derive_dy_012j_reweight.py` ties PU1 and PU2 to one scale factor in 2J
(`2JPU`) and in VBF (`VBFPU`); the equality is in the parameterisation, not
applied afterwards, and the payload repeats the fitted value under both
component keys. Fitting them independently was tried and rejected: it lowers the
2J chi2 (713.8 to 261.9 in Run3_2023) but splits the scales in a way no pile-up
mismodelling produces, 2JPU1 = 2.34 against 2JPU2 = 0.26, with the total PU
yield dropping 25% and the Hard scale rising to compensate through a -0.84
correlation. The untied fit is still run as a diagnostic and reported.

### pt(ll)

This workflow derives DY pt(ll) weights from the hadded process files. It reads
one ROOT file per contribution, as `hist_plotter.py` does, and expects this
structure:

```text
Data_Muon.root:/Z_sideband_ggF_0J/pt_mumu
Data_Muon.root:/Z_sideband_ggF_1J/pt_mumu
Data_Muon.root:/Z_sideband_ggF_ge2J/pt_mumu
Data_Muon.root:/Z_sideband_VBF_ge2J/pt_mumu
```

The same directories must exist in `DY.root` and in the other MC contribution
files to subtract.

Produce the input histograms:

```bash
python3 htcondor/condorsubmit.py histograms \
  --era Run3_2024 \
  --datasets data,DY_amcatnlo,EWK,SingleTop,TTX,W,DiTriBoson,SingleH,signals,other_signals \
  --condor \
  --missing-only \
  --output-suffix _ptllRW \
  -- \
  --variables pt_mumu \
  --mass-regions Z_sideband \
  --categories ggF_0J ggF_1J ggF_ge2J VBF_ge2J \
  --skip-file-validation
```

These histograms should be produced without any DY reweighting applied. They
are used only to derive the first, `pt(ll)`, correction.

Hadd them to process files:

```bash
era=Run3_2024
suffix=_ptllRW

python3 histograms/hadd_hists_to_processes.py \
  --input-dir /eos/user/v/vdamante/H_mumu/newHists_${era}${suffix}/ \
  --output-dir /eos/user/v/vdamante/H_mumu/newHists_${era}${suffix}_hadded/ \
  --era ${era}
```

Derive the JSON. By default the script uses the same `x_rebin` entry for
`pt_mumu` from `config/plot/histograms.yaml` that `hist_plotter.py --rebin`
uses, via the same `RebinHisto(..., wantOverflow=False)` helper. The DY
histogram is scaled by `--dy-scale`, whose default is `0.9393839712918659`.
To override the config binning, pass
`--rebin-edges 0,10,20,30,50,80,120,200,350`.
For each category it writes only the fit/ratio plot
(`*_ptll_ratio_fit.*`) and the before/after diagnostic plot
(`*_ptll_reweight_diagnostic.*`). Both plots include CMS-style labels with
era and `region/category`.

```bash
era=Run3_2024
suffix=_ptllRW

python3 tools/derive_dy_ptll_njets_reweight.py \
  --era ${era} \
  --input-dir /eos/user/v/vdamante/H_mumu/newHists_${era}${suffix}_hadded/ \
  --output-dir reweights/dy_ptll_reweight/${era}/plots \
  --output-json reweights/dy_ptll_reweight/${era}/dy_ptll_reweight.json \
  --output-root reweights/dy_ptll_reweight/${era}/dy_ptll_reweight.root \
  --dy-scale 0.9393839712918659
```

To disable the histogram-config rebinning and use a simple integer factor:

```bash
--no-config-rebin --rebin 2
```

To enable and tune an extra statistical merging on top of the histogram-config
binning:

```bash
--smart-rebin --smart-min-dy 100 --smart-min-target 20 --smart-max-rel-unc 0.15
```

The non-DY samples to subtract are defined in `NON_DY_SUBTRACT_SAMPLES` at the
top of `tools/derive_dy_ptll_njets_reweight.py`. Edit that Python list to
change the subtraction.

### NJets

The NJets-only JSON reads hadded process histograms in the normal inclusive
analysis categories:

```text
Data_Muon.root:/Z_sideband_ggF/N_SelectedJets
Data_Muon.root:/Z_sideband_VBF/N_SelectedJets
```

The same directories must exist in `DY.root` and in the other MC contribution
files to subtract.

Histogram production selects all DY reweight payloads from the requested era;
there are no JSON path options on `hist_maker.py`. Data and non-DY MC remain
unchanged.

```bash
python3 htcondor/condorsubmit.py histograms \
  --era Run3_2024 \
  --datasets data,DY_amcatnlo,EWK,SingleTop,TTX,W,DiTriBoson,SingleH,signals,other_signals \
  --condor \
  --missing-only \
  --output-suffix _njetsRW \
  -- \
  --variables N_SelectedJets \
  --mass-regions Z_sideband \
  --categories ggF VBF \
  --skip-file-validation
```

Hadd them to process files:

```bash
era=Run3_2024
suffix=_njetsRW

python3 histograms/hadd_hists_to_processes.py \
  --input-dir /eos/user/v/vdamante/H_mumu/newHists_${era}${suffix}/ \
  --output-dir /eos/user/v/vdamante/H_mumu/newHists_${era}${suffix}_hadded/ \
  --era ${era}
```

Derive the NJets JSON. The DY histogram is scaled by `--dy-scale`, whose
default is `0.9393839712918659`, before computing the bin-by-bin
`(Data - nonDY) / DY` factors.

```bash
era=Run3_2024
suffix=_njetsRW

python3 tools/derive_dy_njets_reweight.py \
  --era ${era} \
  --input-dir /eos/user/v/vdamante/H_mumu/newHists_${era}${suffix}_hadded/ \
  --output-dir reweights/dy_njets_reweight/${era}/plots \
  --output-json reweights/dy_njets_reweight/${era}/dy_njets_reweight.json \
  --output-root reweights/dy_njets_reweight/${era}/dy_njets_reweight.root \
  --dy-scale 0.9393839712918659
```

The NJets correction has no fitted function: every output value is the bin
content of the `(Data - nonDY) / DY` ratio for that `N_SelectedJets` bin.
The non-DY samples to subtract are defined in `NON_DY_SUBTRACT_SAMPLES` at the
top of `tools/derive_dy_njets_reweight.py`. Edit that Python list to
change the subtraction.
The script also writes stacked Data/MC plots named
`ggF_njets_data_mc.*` and `VBF_njets_data_mc.*`, with `Data/all MC` in the
ratio pad. It writes diagnostic plots named
`ggF_njets_reweight_diagnostic.*` and `VBF_njets_reweight_diagnostic.*`,
with the bin-by-bin factor in the upper pad and before/after closure in the
lower pad.

### Apply

The final nominal DY histogram production automatically applies the pT(ll),
N(jets), and jet-component JSONs selected from `--era`. Non-DY datasets are
left unchanged.

```bash
python3 histograms/hist_maker.py \
  --era Run3_2024 \
  --dataset-name DYto2Mu_M_50_amcatnloFXFX \
  --input /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v3/Run3_2024/DYto2Mu_M_50_amcatnloFXFX/ \
  --output-file test_dy_rw.root \
  --skip-file-validation
```

The pt(ll) JSON is also evaluable with correctionlib:

```python
import correctionlib

cset = correctionlib.CorrectionSet.from_file(
    "reweights/dy_ptll_reweight/Run3_2024/dy_ptll_reweight.json"
)
rw = cset["dy_ptll_reweight"]

weight = rw.evaluate(0, 1.0, 42.0)  # isVBF, N_selectedJets, ptll
```

The NJets JSON is evaluable with only `isVBF` and `nSelectedJets`:

```python
import correctionlib

cset = correctionlib.CorrectionSet.from_file(
    "reweights/dy_njets_reweight/Run3_2024/dy_njets_reweight.json"
)
rw = cset["dy_njets_reweight"]

weight = rw.evaluate(1, 3.0)  # isVBF, nSelectedJets
```

## Merge Hadded Eras

After running `hadd_hists_to_processes.py` for each era, you can merge already-hadded process files across eras with ROOT `hadd`.

The usual flow is:

```text
per-dataset histograms -> per-era hadded process files -> multi-era hadded process files
```

For example:

```text
newHists_Run3_2022_hadded/Data_Muon.root
newHists_Run3_2022EE_hadded/Data_Muon.root
newHists_Run3_2023_hadded/Data_Muon.root
newHists_Run3_2023BPix_hadded/Data_Muon.root
  -> newHists_Run3_2022_23_hadded/Data_Muon.root
```

### Merge Run3_2022 + Run3_2022EE + Run3_2023 + Run3_2023BPix

Use this for combined 2022/2023 plotting with `--era Run3_2022_23`.

```bash
out_dir=/eos/user/v/vdamante/H_mumu/newHists_Run3_2022_23_hadded
mkdir -p ${out_dir}

for sample_file in /eos/user/v/vdamante/H_mumu/newHists_Run3_2022_hadded/*.root; do
  sample=$(basename ${sample_file})
  inputs=()

  for era in Run3_2022 Run3_2022EE Run3_2023 Run3_2023BPix; do
    f=/eos/user/v/vdamante/H_mumu/newHists_${era}_hadded/${sample}
    if [ -s ${f} ]; then
      inputs+=(${f})
    fi
  done

  if [ ${#inputs[@]} -gt 0 ]; then
    hadd -f ${out_dir}/${sample} ${inputs[@]}
  fi
done
```

With a suffix, for example `TT`:

```bash
suffix=TT
out_dir=/eos/user/v/vdamante/H_mumu/newHists_Run3_2022_23${suffix}_hadded
mkdir -p ${out_dir}

for sample_file in /eos/user/v/vdamante/H_mumu/newHists_Run3_2022${suffix}_hadded/*.root; do
  sample=$(basename ${sample_file})
  inputs=()

  for era in Run3_2022 Run3_2022EE Run3_2023 Run3_2023BPix; do
    f=/eos/user/v/vdamante/H_mumu/newHists_${era}${suffix}_hadded/${sample}
    if [ -s ${f} ]; then
      inputs+=(${f})
    fi
  done

  if [ ${#inputs[@]} -gt 0 ]; then
    hadd -f ${out_dir}/${sample} ${inputs[@]}
  fi
done
```

Plot the merged 2022/2023 output:

```bash
python3 plotting_tools/hist_plotter.py \
  --era Run3_2022_23 \
  --input /eos/user/v/vdamante/H_mumu/newHists_Run3_2022_23_hadded/ \
  --output plots_Run3_2022_23/ \
  --region Z_sideband_ggF \
  --samples Data_Muon DY_amcatnlo EWK SingleTop TTX W DiTriBoson GluGluHto2Mu VBFHto2Mu_M125_powheg \
  --wantData \
  --wantLogY \
  --rebin
```

### Merge Run3_2024 + Run3_2025

Use the same pattern for 2024/2025. The output convention below is `Run3_2024_25`.

```bash
out_dir=/eos/user/v/vdamante/H_mumu/newHists_Run3_2024_25_hadded
mkdir -p ${out_dir}

for sample_file in /eos/user/v/vdamante/H_mumu/newHists_Run3_2024_hadded/*.root; do
  sample=$(basename ${sample_file})
  inputs=()

  for era in Run3_2024 Run3_2025; do
    f=/eos/user/v/vdamante/H_mumu/newHists_${era}_hadded/${sample}
    if [ -s ${f} ]; then
      inputs+=(${f})
    fi
  done

  if [ ${#inputs[@]} -gt 0 ]; then
    hadd -f ${out_dir}/${sample} ${inputs[@]}
  fi
done
```

With a suffix, for example `TT`:

```bash
suffix=TT
out_dir=/eos/user/v/vdamante/H_mumu/newHists_Run3_2024_25${suffix}_hadded
mkdir -p ${out_dir}

for sample_file in /eos/user/v/vdamante/H_mumu/newHists_Run3_2024${suffix}_hadded/*.root; do
  sample=$(basename ${sample_file})
  inputs=()

  for era in Run3_2024 Run3_2025; do
    f=/eos/user/v/vdamante/H_mumu/newHists_${era}${suffix}_hadded/${sample}
    if [ -s ${f} ]; then
      inputs+=(${f})
    fi
  done

  if [ ${#inputs[@]} -gt 0 ]; then
    hadd -f ${out_dir}/${sample} ${inputs[@]}
  fi
done
```

If you plot `Run3_2024_25`, make sure the plotting config exists or use the closest era config intentionally.

## DY MLL 105-160 Stitched and NonStitched

For Run3_2024, Run3_2025, and Run3_2026:

```text
DY_amcatnlo_105_160
  DYto2Mu_MLL_105to160_amcatnloFXFX_nonStitched.root
  DYto2Mu_MLL_105to160_amcatnloFXFX_Fil_VBF_nonStitched.root
  DYto2Mu_MLL_105to160_amcatnloFXFX_Flashsim_nonStitched.root

DY_amcatnlo_105_160_stitched
  DYto2Mu_MLL_105to160_amcatnloFXFX_stitched.root
  with --additional-cuts "GenVBFFilter==0"

DY_amcatnlo_105_160_VBFFil
  DYto2Mu_MLL_105to160_amcatnloFXFX_Fil_VBF_stitched.root
  with --additional-cuts "GenVBFFilter==1"
```

Produce all pieces:

```bash
python3 htcondor/condorsubmit.py histograms \
  --era Run3_2024 \
  --datasets DY_amcatnlo_105_160,DY_amcatnlo_105_160_stitched,DY_amcatnlo_105_160_VBFFil \
  --condor \
  --missing-only \
  --max-parallel-jobs 5000 \
  --output-suffix TT \
  -- --skip-file-validation
```

Copy into the hadded directory with plotter-friendly names:

```bash
era=Run3_2024
suffix=TT
input_dir=/eos/user/v/vdamante/H_mumu/newHists_${era}${suffix}
hadded_dir=/eos/user/v/vdamante/H_mumu/newHists_${era}${suffix}_hadded

cp ${input_dir}/DYto2Mu_MLL_105to160_amcatnloFXFX_stitched.root \
   ${hadded_dir}/DYto2Mu_MLL105To160.root

cp ${input_dir}/DYto2Mu_MLL_105to160_amcatnloFXFX_nonStitched.root \
   ${hadded_dir}/DYto2Mu_MLL105To160_nonStitched.root

cp ${input_dir}/DYto2Mu_MLL_105to160_amcatnloFXFX_Flashsim_nonStitched.root \
   ${hadded_dir}/DYto2Mu_MLL105To160_Flashsim.root

cp ${input_dir}/DYto2Mu_MLL_105to160_amcatnloFXFX_Fil_VBF_nonStitched.root \
   ${hadded_dir}/DYto2Mu_MLL105To160_VBFFiltered_nonStitched.root

cp ${input_dir}/DYto2Mu_MLL_105to160_amcatnloFXFX_Fil_VBF_stitched.root \
   ${hadded_dir}/DYto2Mu_MLL105To160_VBFFiltered.root
```

For an unsuffixed production use:

```bash
input_dir=/eos/user/v/vdamante/H_mumu/newHists_${era}
hadded_dir=/eos/user/v/vdamante/H_mumu/newHists_${era}_hadded
```

Useful plotting groups:

```text
DYto2Mu_MLL105_160
DYto2Mu_MLL105_160_Flashsim
DYto2Mu_MLL105_160_VBFFiltered
DYto2Mu_MLL105_160_combined
```

## Plotting

Single plot command:

```bash
python3 plotting_tools/hist_plotter.py \
  --era Run3_2024 \
  --input /eos/user/v/vdamante/H_mumu/newHists_Run3_2024_hadded/ \
  --output plots_DYamcatnlo/ \
  --region Z_sideband_ggF \
  --samples Data_Muon DY_amcatnlo EWK SingleTop TTX W DiTriBoson GluGluHto2Mu VBFHto2Mu_M125_powheg \
  --vars m_mumu,DNN_NNOutput \
  --wantData \
  --wantLogY \
  --rebin
```

Plot all standard regions/categories:

```bash
for region in Z_sideband Signal_Fit mass_inclusive; do
  for cat in baseline ggF VBF; do
    python3 plotting_tools/hist_plotter.py \
      --era Run3_2024 \
      --input /eos/user/v/vdamante/H_mumu/newHists_Run3_2024_hadded/ \
      --output plots_all_vars/ \
      --region ${region}_${cat} \
      --samples Data_Muon DY_amcatnlo EWK SingleTop TTX W DiTriBoson GluGluHto2Mu VBFHto2Mu_M125_powheg \
      --wantData \
      --wantLogY \
      --rebin
  done
done
```

Stitched/VBF-filtered Signal Fit example:

```bash
python3 plotting_tools/hist_plotter.py \
  --era Run3_2024 \
  --input /eos/user/v/vdamante/H_mumu/newHists_Run3_2024_hadded/ \
  --output plots_stitchedVBFFiltered_EWKHerwig/ \
  --region Signal_Fit_VBF \
  --samples Data_Muon DYto2Mu_MLL105To160 DYto2Mu_MLL105To160_VBFFiltered W_NJets TT EWK_2Mu2J_MLL_105to160_herwig VV VVV VBFHto2Mu_M125_powheg GluGluHto2Mu \
  --wantLogY \
  --wantData \
  --rebin
```

Comparison without stack:

```bash
python3 plotting_tools/hist_plotter.py \
  --era Run3_2024 \
  --input /eos/user/v/vdamante/H_mumu/newHists_Run3_2024_hadded/ \
  --output plots_EWKPythiaVSHerwig/ \
  --region Signal_Fit_VBF \
  --samples EWK_2Mu2J_MLL_105to160_pythia EWK_2Mu2J_MLL_105to160_herwig \
  --ratio-reference EWK_2Mu2J_MLL_105to160_herwig \
  --no-stack \
  --no-fill-hists \
  --wantLogY \
  --rebin
```

DY amcatnlo vs MiNNLO:

```bash
for region in mass_inclusive Z_sideband; do
  for category in baseline ggF VBF; do
    python3 plotting_tools/hist_plotter.py \
      --era Run3_2024 \
      --input /eos/user/v/vdamante/H_mumu/newHists_Run3_2024_hadded/ \
      --output plots_amcatnloVSMinnlo/ \
      --region ${region}_${category} \
      --samples DY_amcatnlo DY_minnlo \
      --wantLogY \
      --no-stack \
      --no-fill-hists \
      --ratio-reference DY_amcatnlo \
      --rebin
  done
done
```

Plot runner:

```bash
bash histograms/scripts/run_plotter.sh --dryrun
bash histograms/scripts/run_plotter.sh
bash histograms/scripts/run_plotter.sh --era "Run3_2024" --mode 2024_all
```

Use a suffixed hadded directory:

```bash
bash histograms/scripts/run_plotter.sh \
  --era "Run3_2024" \
  --mode 2024_all \
  --input-tag-template newHists_ERA_TT_hadded
```

Copy plots to the web area:

```bash
cp -r plots_DYamcatnlo /eos/user/v/vdamante/www/H_mumu/
cp /eos/user/v/vdamante/www/H_mumu/index.php /eos/user/v/vdamante/www/H_mumu/plots_DYamcatnlo/
```

## Useful Campaign Recipes

### Z-sideband mass-shifted DNN

One group:

```bash
python3 htcondor/condorsubmit.py histograms \
  --era Run3_2022EE \
  --datasets signals \
  --condor \
  --missing-only \
  --output-suffix _ZSideband_mass_shifted \
  -- \
  --variables DNN_NNOutput \
  --mass-regions Z_sideband \
  --shift-z-sideband-dnn-mass \
  --skip-file-validation
```

All usual 2022EE groups:

```bash
for group in signals data DiTriBoson DY_amcatnlo EWK SingleH SingleTop TTX W DY_amcatnlo_105_160; do
python3 htcondor/condorsubmit.py histograms \
    --era Run3_2022EE \
    --datasets ${group} \
    --condor \
    --missing-only \
    --output-suffix _ZSideband_mass_shifted \
    -- \
    --variables DNN_NNOutput \
    --mass-regions Z_sideband \
    --shift-z-sideband-dnn-mass \
    --skip-file-validation
done
```

### Low-pT/TT categories

```bash
tt_vars="DNN_NNOutput m_mumu pt_mumu eta_mumu mu1_pt mu2_pt mu1_eta mu2_eta leadingjet_pt leadingjet_eta subleadingjet_pt subleadingjet_eta delta_eta_jj_ls m_jj_ls m_jj delta_eta_jj vbfjet1_pt vbfjet2_pt vbfjet1_eta vbfjet2_eta vbfjet1_phi vbfjet2_phi"

for group in data DiTriBoson DY_amcatnlo DY_amcatnlo_105_160 DY_amcatnlo_105_160_stitched DY_amcatnlo_105_160_VBFFil DY_minnlo EWK signals SingleH SingleTop TTX W other_signals; do
python3 htcondor/condorsubmit.py histograms \
    --era Run3_2024 \
    --datasets ${group} \
    --condor \
    --missing-only \
    --max-parallel-jobs 5000 \
    --output-suffix TT \
    -- \
    --categories baseline_lowPtTT ggF_lowPtTT VBF_lowPtTT \
    --variables ${tt_vars} \
    --skip-file-validation
done
```

For 2025 change `--era Run3_2024` to `--era Run3_2025`.

### One group only

```bash
python3 htcondor/condorsubmit.py histograms \
  --era Run3_2025 \
  --datasets data \
  --condor \
  --missing-only \
  --max-parallel-jobs 5000 \
  -- --skip-file-validation
```

### One dataset only

```bash
python3 htcondor/condorsubmit.py histograms \
  --era Run3_2025 \
  --dataset-name TTto2L2Nu \
  --chunk-size 10 \
  --condor \
  --missing-only \
  --max-parallel-jobs 5000 \
  -- --skip-file-validation
```

## Debug Commands

Condor:

```bash
condor_q
condor_q -hold
```

Inspect histogram job logs:

```bash
ls htcondor/hists/
ls htcondor/hists/<RUN_DIR>/error/
less htcondor/hists/<RUN_DIR>/error/<JOB>.err
```

Check outputs:

```bash
ls /eos/user/v/vdamante/H_mumu/newHists_Run3_2024/
ls /eos/user/v/vdamante/H_mumu/newHists_Run3_2024_hadded/
```

If the plotter cannot find a sample, check the exact ROOT filename in the hadded directory and pass that name without `.root`.

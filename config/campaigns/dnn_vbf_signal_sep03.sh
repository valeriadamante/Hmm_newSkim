#!/usr/bin/env bash

# DNN output regenerated after the FullEventId inference fix.
# CAMPAIGN_OPTIONS preserves the existing bundled all/ layout.
CAMPAIGN_ROOT="/eos/user/v/vdamante/H_mumu/Sep_03/DNN_VBF_Signal_AllWeights"
CAMPAIGN_LABEL="Sep03_DNN_VBF_Signal_AllWeights"
HIST_DIR_PREFIX=""
ERAS=(2022 2022EE 2023 2023BPix 2024 2025)
MERGED_ERA="Run3_2022_25"
SYSTEMATICS=(
  Central
  JEReta0pt0 JEReta1pt0 JEReta2pt0 JEReta2pt1 JEReta3pt0 JEReta3pt1
  JES_Total Muon PDF PU QCDScale ScaRe
)

# Include DY in the generic campaign; submit skips existing outputs.
DATASETS="data,region_auto,signals,flash_backgrounds,SingleH,SingleTop,TTX,TT,W,DiTriBoson"
CHUNK_SIZE=1
REQUEST_CPUS=8
REQUEST_MEMORY=20GB
RDF_THREADS=8
VARIABLE_BATCH_SIZE=1

HIST_ARGS=(
  --variables DNN_NNOutput
  --mass-regions Signal_Fit
  --categories VBF
  --pu-hard-jet-components
  --dy-jet-component-reweight
  --dy-ptll-reweight
  --dy-njets-reweight
)

ROOT_INPUT="/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v3"
JSON_INPUT="$ROOT_INPUT"
MANIFEST_INPUT="/eos/user/v/vdamante/H_mumu/manifests_skim_v3"

# Continue the existing Sep_03 production; CLI options can override these defaults.
# Default dal 16/09/2026: JES nelle 11 famiglie regrouped, come all_variables.
# Il precedente --jes total collassava il JES in una sola nuisance
# CMS_scale_j_total, incompatibile con il modello di correlazione usato dal
# resto dell'analisi. Il layout storico Sep_03 resta ottenibile passando
# esplicitamente --systematics-layout together --jes total.
CAMPAIGN_OPTIONS=(--mode both --systematics-layout split --jes regrouped)

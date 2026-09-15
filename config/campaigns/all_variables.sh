#!/usr/bin/env bash
# All stored regions/categories and all maincfg variables.
CAMPAIGN_ROOT="/eos/user/v/vdamante/H_mumu/campaigns/AllVariables_AllWeights"
CAMPAIGN_LABEL="AllVariables_AllWeights"
HIST_DIR_PREFIX=""
ERAS=(2022 2022EE 2023 2023BPix 2024 2025)
DATASETS="data,region_auto,signals,flash_backgrounds,SingleH,SingleTop,TTX,TT,W,DiTriBoson"
CHUNK_SIZE=1
REQUEST_CPUS=4
REQUEST_MEMORY=20GB
RDF_THREADS=4
VARIABLE_BATCH_SIZE=8
SYSTEMATICS=(Central JEReta0pt0 JEReta1pt0 JEReta2pt0 JEReta2pt1 JEReta3pt0 JEReta3pt1 JES_Total Muon PDF PU QCDScale ScaRe)
ROOT_INPUT="/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v3"
JSON_INPUT="$ROOT_INPUT"
MANIFEST_INPUT="/eos/user/v/vdamante/H_mumu/manifests_skim_v3"
HIST_ARGS=(--mass-regions all --categories all --pu-hard-jet-components
           --dy-jet-component-reweight --dy-ptll-reweight --dy-njets-reweight)

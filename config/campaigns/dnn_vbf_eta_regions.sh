#!/usr/bin/env bash
# Output del DNN con la VBF divisa per eta dei due jet VBF, solo Central.
#
# Gemella di vbf_eta_regions.sh: stessa suddivisione incl/CC/CF/FF in
# sottocartelle, ma la sola variabile DNN_NNOutput, che nei maincfg e'
# commentata e va quindi chiesta esplicitamente.
#
# Come l'altra, non convive con --pu-hard-jet-components: hist_maker abilita le
# eta region solo se quel flag e' assente (hist_maker.py:1245) e sovrascrive
# --categories con le quattro VBF_eta_*.
CAMPAIGN_ROOT="/eos/user/v/vdamante/H_mumu/skim_v4/post_dy/dnn_vbf_eta_regions"
CAMPAIGN_LABEL="DNNVBFEtaRegions"
HIST_DIR_PREFIX=""
ERAS=(2022 2022EE 2023 2023BPix 2024 2025 2026)
DATASETS="data,region_auto,signals,flash_backgrounds,SingleH,SingleTop,TTX,TT,W,DiTriBoson"
CHUNK_SIZE=1
REQUEST_CPUS=8
REQUEST_MEMORY=20GB
RDF_THREADS=8
VARIABLE_BATCH_SIZE=1
# Solo Central: e' uno studio di categorizzazione.
SYSTEMATICS=(Central)
ROOT_INPUT="/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4"
JSON_INPUT="$ROOT_INPUT"
MANIFEST_INPUT="/eos/user/v/vdamante/H_mumu/manifests_skim_v4"
HIST_ARGS=(--variables DNN_NNOutput
           --mass-regions Z_sideband Signal_Fit H_sideband Signal_ext mass_inclusive
           --categories VBF
           # Come nell'altra campagna: senza --categories esplicito workflow.py
           # passa l'opzione vuota e il produttore si rifiuta di partire.
           --vbf-eta-regions
           --dy-jet-component-reweight --dy-ptll-reweight --dy-njets-reweight)

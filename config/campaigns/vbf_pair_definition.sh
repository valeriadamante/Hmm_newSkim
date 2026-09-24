#!/usr/bin/env bash
# Confronto fra definizioni della coppia VBF: Data/MC e peso del DY con jet PU.
#
# VBF_PAIR_DEF sceglie la definizione (common/vbf_pair_definition.py):
#   maxmjj   produzione, coppia a m(jj) massima fra quelle che passano i tagli
#   hardest  fra le coppie che passano i tagli, la piu' dura in pT dei singoli jet
#   leading  i due jet leading, tutti e due devono passare la preselezione
# Tutte con m(jj) >= 400, |Delta eta| >= 2.5, pT >= 35/25.
#
# Il DY e' senza i tre reweight: sono stati fittati con la coppia maxmjj e
# darebbero un vantaggio alla definizione di produzione.  Le componenti Hard/PU
# (--pu-hard-jet-components) dicono quanta parte del DY in VBF ha uno o due jet
# VBF da pile-up, cioe' il DY 0J/1J "vero".
VBF_PAIR_DEF="${VBF_PAIR_DEF:-maxmjj}"
CAMPAIGN_ROOT="/eos/user/v/vdamante/H_mumu/skim_v4/post_dy/vbf_pair_definition/${VBF_PAIR_DEF}"
CAMPAIGN_LABEL="VBFPair_${VBF_PAIR_DEF}"
HIST_DIR_PREFIX=""
ERAS=(2022 2022EE 2023 2023BPix 2024 2025 2026)
DATASETS="data,region_auto,signals,SingleH,SingleTop,TTX,TT,W,DiTriBoson"
CHUNK_SIZE=1
REQUEST_CPUS=4
REQUEST_MEMORY=20GB
RDF_THREADS=4
VARIABLE_BATCH_SIZE=100
SYSTEMATICS=(Central)
ROOT_INPUT="/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4"
JSON_INPUT="$ROOT_INPUT"
MANIFEST_INPUT="/eos/user/v/vdamante/H_mumu/manifests_skim_v4"
HIST_ARGS=(--vbf-pair-definition "${VBF_PAIR_DEF}"
           --mass-regions Z_sideband H_sideband Signal_Fit
           --categories VBF ggF
           --variables m_mumu m_jj delta_eta_jj vbfjet1_pt vbfjet2_pt vbfjet1_eta vbfjet2_eta
                       N_SelectedJets Zeppenfeld_Var DNN_NNOutput
           --pu-hard-jet-components
           --custom-weights --no-dy-jet-component-reweight --no-dy-ptll-reweight --no-dy-njets-reweight)

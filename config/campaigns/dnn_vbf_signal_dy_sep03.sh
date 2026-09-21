#!/usr/bin/env bash

# Fill the existing Sep03 campaign with DY only, keeping all weights and shifts.
source "$(dirname "${BASH_SOURCE[0]}")/dnn_vbf_signal_sep03.sh"
DATASETS="DY_amcatnlo,DY_amcatnlo_105_160"
CAMPAIGN_LABEL="Sep03_DNN_VBF_Signal_DYOnly_AllWeights"

ROOT_INPUT="/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4"
JSON_INPUT="$ROOT_INPUT"
MANIFEST_INPUT="/eos/user/v/vdamante/H_mumu/manifests_skim_v4"

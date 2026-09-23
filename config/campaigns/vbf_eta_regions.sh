#!/usr/bin/env bash
# Tutte le variabili, solo Central, con la VBF divisa per eta dei due jet VBF.
#
# --vbf-eta-regions taglia a |eta| = 2.5 sulla coppia VBF selezionata e produce
# quattro categorie: VBF_eta_incl, VBF_eta_CC, VBF_eta_CF, VBF_eta_FF. Le
# directory risultano <regione>_VBF_eta_CC e simili, cioe' le sottocartelle
# volute.
#
# Nota importante: hist_maker abilita quel percorso solo se --pu-hard-jet-components
# NON e' attivo (hist_maker.py:1245), e sovrascrive --categories con le quattro
# eta region. Per questo qui la scomposizione in componenti di jet e' assente:
# le due cose si escludono, e questa campagna serve allo studio in eta.
CAMPAIGN_ROOT="/eos/user/v/vdamante/H_mumu/skim_v4/post_dy/vbf_eta_regions"
CAMPAIGN_LABEL="VBFEtaRegions"
HIST_DIR_PREFIX=""
ERAS=(2022 2022EE 2023 2023BPix 2024 2025 2026)
DATASETS="data,region_auto,signals,flash_backgrounds,SingleH,SingleTop,TTX,TT,W,DiTriBoson"
CHUNK_SIZE=1
REQUEST_CPUS=4
REQUEST_MEMORY=20GB
RDF_THREADS=4
# Tutte le variabili in un solo event loop, come all_variables.
VARIABLE_BATCH_SIZE=100
# Solo Central: e' uno studio di categorizzazione, le sistematiche non servono.
SYSTEMATICS=(Central)
ROOT_INPUT="/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4"
JSON_INPUT="$ROOT_INPUT"
MANIFEST_INPUT="/eos/user/v/vdamante/H_mumu/manifests_skim_v4"
# --categories serve comunque: workflow.py emette l'opzione anche con lista
# vuota e hist_maker muore con "expected at least one argument". Il valore e'
# irrilevante, perche' --vbf-eta-regions lo sovrascrive con le quattro
# VBF_eta_*, ma deve esserci ed e' onesto che sia VBF: e' quella che si divide.
HIST_ARGS=(--mass-regions all --categories VBF --vbf-eta-regions
           --dy-jet-component-reweight --dy-ptll-reweight --dy-njets-reweight)

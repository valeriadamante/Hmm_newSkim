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
# Tutte le variabili (39) in un solo event loop: ogni loop rilegge gli input,
# e su DYto2L_M_50 i 4 loop in piu' costavano ~35 min su 2h16.
VARIABLE_BATCH_SIZE=100
SYSTEMATICS=(Central JEReta0pt0 JEReta1pt0 JEReta2pt0 JEReta2pt1 JEReta3pt0 JEReta3pt1 JES_Total Muon PDF PU QCDScale ScaRe)
ROOT_INPUT="/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4"
JSON_INPUT="$ROOT_INPUT"
MANIFEST_INPUT="/eos/user/v/vdamante/H_mumu/manifests_skim_v4"
# Tutte le mass region, ma solo le categorie che servono all'analisi.
# '--categories all' prendeva ogni voce store:true della selections.yaml
# dell'era, quindi un insieme diverso da un'era all'altra: 13 nel 2024, 17 nel
# 2025, 19 nel 2026, con dentro base_sel, i same-sign, le _Z_ e le lowPtTT che
# non entrano in nessun plot. Qui l'elenco e' esplicito e identico ovunque:
# baseline, ggF, VBF piu' le molteplicita' di jet che servono alla scomposizione
# in componenti. VBF_def resta definita come colonna perche' VBF e ggF la
# usano, ma non produce piu' istogrammi per conto suo.
HIST_ARGS=(--mass-regions all
           --categories baseline ggF VBF ggF_0J ggF_1J ggF_2J ggF_ge2J VBF_ge2J
           --pu-hard-jet-components
           --dy-jet-component-reweight --dy-ptll-reweight --dy-njets-reweight)

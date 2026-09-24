#!/usr/bin/env bash
#
# Chiude il 2025 del DNN VBF e rifa' le card Signal Extended con tutte e sei le ere.
#
# Attende i job di riparazione in coda (gli istogrammi 2025 che erano vuoti o
# illeggibili, vedi la memoria histogrammi-file-vuoti-invisibili), poi:
#   hadd delle famiglie sistematiche -> merge-syst -> plot -> card a 6 ere.
#
#     nohup bash campaigns/finish_dnn_2025_and_cards.sh > finish_dnn_2025.log 2>&1 &
#
# Ogni passo e' idempotente: si puo' rilanciare.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
repo="$PWD"
# shellcheck disable=SC1091
source env.sh >/dev/null 2>&1

V4_IN=/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4
V4_MAN=/eos/user/v/vdamante/H_mumu/manifests_skim_v4
OUT=/eos/user/v/vdamante/H_mumu/skim_v4/post_dy/dnn_vbf_weighted
REG=Z_sideband,Signal_Fit,H_sideband,Signal_ext,mass_inclusive
POLL="${V4_POLL:-300}"
ERAS_ALL="${SE_ERAS:-2022,2022EE,2023,2023BPix,2024,2025}"

log() { echo "[$(date '+%F %T')] $*"; }

opts=(--regions "$REG" --categories VBF --threads 1 --check-level files
      --input-dir "$V4_IN" --manifest-root "$V4_MAN" --output-dir "$OUT")

log "attendo i job Sep03_DNN in coda"
while condor_q -af JobBatchName 2>/dev/null | grep -q "Sep03_DNN"; do sleep "$POLL"; done
log "coda vuota"

# Il job intero su DYto2Mu_M_50_amcatnloFXFX in ScaRe e' stato rimosso una volta
# per wall time; in parallelo girano 8 shard come riserva. Se il job intero ce
# l'ha fatta il file c'e' gia' e gli shard si ignorano, altrimenti si uniscono.
scare_nominal="$OUT/ScaRe/Run3_2025/DYto2Mu_M_50_amcatnloFXFX.root"
if python3 -c "import sys,uproot; sys.exit(0 if len(uproot.open('$scare_nominal').keys()) else 1)" 2>/dev/null; then
    log "ScaRe/Run3_2025/DYto2Mu_M_50: il job intero ha prodotto il file, shard non necessari"
else
    log "=== unisco gli 8 shard di ScaRe/Run3_2025/DYto2Mu_M_50_amcatnloFXFX"
    python3 tools/shard_hists.py merge --config dnn_vbf_signal_sep03 --era Run3_2025 \
        --dataset DYto2Mu_M_50_amcatnloFXFX --shards 8 --family ScaRe \
        --regions "$REG" --categories VBF \
        --input-root "$V4_IN" --manifest-root "$V4_MAN" --output-root "$OUT" \
        || { log "merge degli shard fallito: qualche shard non ha prodotto output"; exit 1; }
fi

log "=== hadd delle famiglie sistematiche 2025"
python3 campaigns/hadd_parallel.py --campaign dnn_vbf_weighted --eras 2025 --jobs 12 \
    || log "hadd parallelo ha segnalato problemi"

log "=== merge-syst 2025"
bash campaigns/dnn_vbf_signal.sh merge-syst --mode both --eras 2025 "${opts[@]}" \
    || { log "merge-syst 2025 fallito: controlla quale file hadd e' rotto"; exit 1; }

log "=== plot con le bande di sistematica, 2025"
bash campaigns/dnn_vbf_signal.sh plot --mode both --eras 2025 "${opts[@]}" \
    --plot-regions Signal_Fit,Z_sideband,H_sideband,mass_inclusive \
    --plot-categories VBF --component-composition \
    --plot-output plots_Sep18/systematics || log "plot 2025 ha segnalato problemi"

log "=== plot sample-by-sample e syst-by-syst, 2025"
# La lista di default del tool non contiene le componenti di jet del DY, che
# sono proprio i template che entrano nella card: vanno chieste esplicitamente.
SAMPLES=DYto2Mu_MLL105To160,DYto2Mu_MLL105To160_2J_Hard,DYto2Mu_MLL105To160_2J_PU1,DYto2Mu_MLL105To160_2J_PU2,EWK_2Mu2J_MLL_105to160_herwig,ST,VV,TT,TTX,VVV,W_NJets,W,TW,SingleH,GluGluHto2Mu,VBFHto2Mu_M125_powheg
for region in Z_sideband Signal_Fit H_sideband Signal_ext mass_inclusive; do
    python3 tools/plot_systematics_campaign.py \
        --input-base "$OUT/Hists_systMerged" --era Run3_2025 \
        --region "${region}_VBF" --variable DNN_NNOutput --mode both --run \
        --sample "$SAMPLES" \
        --output "results/skim_v4/dnn_vbf/systematics/2025/$region" \
        || log "sample-by-sample 2025 $region non riuscito"
done

log "=== card Signal Extended a sei ere"
for model in lnn rateparam-pu rateparam-both; do
    out="$repo/combine/results_signal_extended/$model"
    mkdir -p "$out"
    python3 combine/build_signal_extended_datacards.py \
        --input "$OUT/Hists_systMerged" --eras "$ERAS_ALL" --dy-model "$model" \
        --output "$out/datacard_signal_extended_$model.txt" > "$out/build.log" 2>&1 \
        && log "card $model: $(tail -1 "$out/build.log")" \
        || log "card $model fallita, vedi $out/build.log"
done

log "fatto. Ora: bash combine/run_signal_extended_fits.sh"

#!/usr/bin/env bash
#
# Chiude le riparazioni di all_variables partite il 22-23/09.
#
# Il job Muon 2024 su DYto2Mu_M_50_amcatnloFXFX era stato rimosso da Condor per
# wall time (workday = 8 h, 4 CPU): e' stato rilanciato in 10 shard con
# tools/shard_hists.py. Qui si aspettano gli shard, si uniscono nel file che la
# campagna si aspetta, poi hadd e merge-syst delle ere che ne avevano bisogno.
#
#     nohup bash campaigns/finish_all_variables_repairs.sh > finish_av.log 2>&1 &
#
# Idempotente: si puo' rilanciare.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# shellcheck disable=SC1091
source env.sh >/dev/null 2>&1

V4_IN=/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4
V4_MAN=/eos/user/v/vdamante/H_mumu/manifests_skim_v4
OUT=/eos/user/v/vdamante/H_mumu/skim_v4/post_dy/all_variables
POLL="${V4_POLL:-300}"
ERAS="${AV_ERAS:-2023BPix 2024 2025 2026}"

log() { echo "[$(date '+%F %T')] $*"; }

log "attendo gli shard AllVariables in coda"
while condor_q -af JobBatchName 2>/dev/null | grep -q "AllVariables"; do sleep "$POLL"; done
log "coda vuota"

log "=== unisco gli shard di Muon/Run3_2024/DYto2Mu_M_50_amcatnloFXFX"
python3 tools/shard_hists.py merge --config all_variables --era Run3_2024 \
    --dataset DYto2Mu_M_50_amcatnloFXFX --shards 10 --family Muon \
    --input-root "$V4_IN" --manifest-root "$V4_MAN" --output-root "$OUT" \
    || { log "merge degli shard fallito: qualche shard non ha prodotto output"; exit 1; }

log "=== hadd 2024 (Muon era l'unica famiglia che mancava)"
python3 campaigns/hadd_parallel.py --campaign all_variables --eras 2024 --jobs 6 \
    || log "hadd ha segnalato problemi"

for era in $ERAS; do
    log "=== merge-syst $era"
    bash campaigns/all_variables.sh merge-syst --mode both --eras "$era" --check-level root \
        --input-dir "$V4_IN" --manifest-root "$V4_MAN" --output-dir "$OUT" \
        || log "merge-syst $era fallito: cerca il file hadd rotto nel log"
done

log "=== plot con le bande di sistematica, era per era"
nohup bash campaigns/plot_syst_when_ready.sh > plot_syst.log 2>&1 &
log "plot_syst_when_ready avviato in background (plot_syst.log)"
log "fatto"

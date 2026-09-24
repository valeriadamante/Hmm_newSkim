#!/usr/bin/env bash
#
# Catena completa dopo la correzione degli skim: pesi DY, tutte le variabili,
# DNN VBF, studi DNN e confronto FullSim/FlashSim.
#
# Gli stadi hanno dipendenze reali: i pesi DY vanno derivati nell'ordine
# jet -> pTmumu -> N(jet), e tutto il resto legge i JSON prodotti da quello
# stadio.  Questo script attende Condor fra uno stadio e il successivo, quindi
# va lanciato in background:
#
#     nohup bash campaigns/run3_post_skim_chain.sh all > chain.log 2>&1 &
#
# Ogni azione e' anche invocabile da sola, per riprendere da dove si era fermi.

set -uo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"

# shellcheck disable=SC1091
source env.sh >/dev/null 2>&1

ERAS="${V4_ERAS:-2022,2022EE,2023,2023BPix,2024,2025,2026}"
INPUT="${V4_INPUT:-/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4}"
MANIFEST="${V4_MANIFEST:-/eos/user/v/vdamante/H_mumu/manifests_skim_v4}"
OUTPUT="${V4_OUTPUT:-/eos/user/v/vdamante/H_mumu/skim_v4/post_dy}"
DNN_REGIONS="${V4_DNN_REGIONS:-Z_sideband,Signal_Fit,H_sideband,Signal_ext,mass_inclusive}"
POLL="${V4_POLL:-300}"

log() { echo "[$(date '+%F %T')] $*"; }

# Attende che non restino job in coda il cui JobBatchName contiene il pattern.
wait_condor() {
    local pattern="$1" n
    log "attendo i job che matchano '$pattern'"
    while true; do
        n=$(condor_q -af JobBatchName 2>/dev/null | grep -c "$pattern")
        [[ "$n" -eq 0 ]] && break
        sleep "$POLL"
    done
    log "nessun job '$pattern' in coda"
}

dy_weights() {
    log "=== pesi DY: manifest di validazione"
    bash campaigns/run3_dy_weights_skim_v4.sh manifests \
        --eras "$ERAS" --input-dir "$INPUT" --manifest-root "$MANIFEST"
    wait_condor "DYWeights_skim_v4"

    # run avanza uno stadio per volta (jet -> ptll -> njets) e ritorna 3
    # quando ha sottomesso e deve attendere Condor.
    local stage
    for stage in jet ptll njets; do
        log "=== pesi DY: stadio $stage"
        bash campaigns/run3_dy_weights_skim_v4.sh run \
            --eras "$ERAS" --input-dir "$INPUT" \
            --manifest-root "$MANIFEST" --output-root "$OUTPUT/DY_weights"
        local rc=$?
        if [[ "$rc" -eq 3 ]]; then
            wait_condor "DYWeights\|DYPTLL\|DYNJETS\|DY012J"
        elif [[ "$rc" -ne 0 ]]; then
            log "ATTENZIONE: stadio $stage uscito con $rc, mi fermo"
            return "$rc"
        fi
    done
    log "=== pesi DY completati"
}

all_variables() {
    local mode
    for mode in central syst; do
        log "=== all_variables: submit $mode"
        # Nota: DYto2Mu_M_50_amcatnloFXFX (595 file nel 2024) non sta nelle 8 ore
        # di JobFlavour workday nemmeno a 4 CPU. Va prodotto a parte con
        # tools/shard_hists.py --shards 10; vedi campaigns/STATO_2026-09-22.md.
        bash campaigns/all_variables.sh submit --mode "$mode" --eras "$ERAS" --memory 20GB \
            --input-dir "$INPUT" --manifest-root "$MANIFEST" \
            --output-dir "$OUTPUT/all_variables" --plot-output results/skim_v4/all_variables
        wait_condor "AllVariables"
        log "=== all_variables: check $mode"
        bash campaigns/all_variables.sh check --stage histograms --mode "$mode" --eras "$ERAS" \
            --input-dir "$INPUT" --manifest-root "$MANIFEST" \
            --output-dir "$OUTPUT/all_variables" || log "check $mode ha segnalato problemi"
    done
    for action in hadd merge-syst plot; do
        log "=== all_variables: $action"
        bash campaigns/all_variables.sh "$action" --mode both --eras "$ERAS" \
            --input-dir "$INPUT" --manifest-root "$MANIFEST" \
            --output-dir "$OUTPUT/all_variables" --plot-output results/skim_v4/all_variables \
            || log "$action ha segnalato problemi"
    done
}

dnn_vbf() {
    local mode
    for mode in central syst; do
        log "=== DNN VBF: submit $mode"
        bash campaigns/dnn_vbf_signal.sh submit --mode "$mode" --eras "$ERAS" \
            --regions "$DNN_REGIONS" --categories VBF \
            --input-dir "$INPUT" --manifest-root "$MANIFEST" \
            --output-dir "$OUTPUT/dnn_vbf_weighted"
        wait_condor "DNN_VBF\|Sep03_DNN"
        log "=== DNN VBF: check $mode"
        bash campaigns/dnn_vbf_signal.sh check --stage histograms --mode "$mode" --eras "$ERAS" \
            --regions "$DNN_REGIONS" --categories VBF \
            --input-dir "$INPUT" --manifest-root "$MANIFEST" \
            --output-dir "$OUTPUT/dnn_vbf_weighted" || log "check $mode ha segnalato problemi"
    done
    for action in hadd merge-syst plot; do
        log "=== DNN VBF: $action"
        bash campaigns/dnn_vbf_signal.sh "$action" --mode both --eras "$ERAS" \
            --regions "$DNN_REGIONS" --categories VBF \
            --input-dir "$INPUT" --manifest-root "$MANIFEST" \
            --output-dir "$OUTPUT/dnn_vbf_weighted" \
            --plot-output results/skim_v4/dnn_vbf/data_mc || log "$action ha segnalato problemi"
    done
}

# VBF divisa per eta dei due jet VBF in incl/CC/CF/FF, solo Central.
# Non convive con --pu-hard-jet-components, quindi e' una campagna a se'.
vbf_eta_regions() {
    log "=== VBF eta regions: submit central"
    bash campaigns/vbf_eta_regions.sh submit --mode central --eras "$ERAS" --memory 8GB \
        --input-dir "$INPUT" --manifest-root "$MANIFEST" \
        --output-dir "$OUTPUT/vbf_eta_regions"
    wait_condor "VBFEtaRegions"
    log "=== DNN VBF eta regions: submit central"
    bash campaigns/dnn_vbf_eta_regions.sh submit --mode central --eras "$ERAS" --memory 8GB \
        --input-dir "$INPUT" --manifest-root "$MANIFEST" \
        --output-dir "$OUTPUT/dnn_vbf_eta_regions"
    wait_condor "DNNVBFEtaRegions"
    log "=== VBF eta regions: hadd"
    bash campaigns/vbf_eta_regions.sh hadd --mode central --eras "$ERAS" --check-level files \
        --input-dir "$INPUT" --manifest-root "$MANIFEST" \
        --output-dir "$OUTPUT/vbf_eta_regions" || log "hadd ha segnalato problemi"
    bash campaigns/dnn_vbf_eta_regions.sh hadd --mode central --eras "$ERAS" --check-level files \
        --input-dir "$INPUT" --manifest-root "$MANIFEST" \
        --output-dir "$OUTPUT/dnn_vbf_eta_regions" || log "hadd ha segnalato problemi"
}

dnn_studies() {
    log "=== studi DNN: submit"
    bash campaigns/dnn_studies_skim_v4.sh submit \
        --eras "$ERAS" --input-dir "$INPUT" --manifest-root "$MANIFEST"
    wait_condor "DNNStud\|dnn_vbf_dy_unweighted\|dnn_vbf_weighted"
    log "=== studi DNN: hadd + studies"
    bash campaigns/dnn_studies_skim_v4.sh hadd \
        --eras "$ERAS" --input-dir "$INPUT" --manifest-root "$MANIFEST" \
        || log "hadd ha segnalato problemi"
    bash campaigns/dnn_studies_skim_v4.sh studies \
        --eras "$ERAS" --input-dir "$INPUT" --manifest-root "$MANIFEST" \
        || log "studies ha segnalato problemi"
}

# Confronto FullSim/FlashSim: gli istogrammi delle stesse variabili escono gia'
# da all_variables, che include entrambe le varianti dei sample.
flashsim_comparison() {
    log "=== confronto FullSim/FlashSim"
    local era
    IFS=',' read -r -a selected <<< "$ERAS"
    for era in "${selected[@]}"; do
        python3 tools/compare_flashsim.py \
            --era "Run3_${era}" \
            --input-base "$OUTPUT/all_variables/Central_hadded" \
            --output results/skim_v4/flashsim_comparison --run \
            || log "confronto FlashSim per Run3_${era} non riuscito"
    done
}

action="${1:-all}"
case "$action" in
    dy-weights)  dy_weights ;;
    all-variables) all_variables ;;
    dnn-vbf)     dnn_vbf ;;
    dnn-studies) dnn_studies ;;
    vbf-eta)     vbf_eta_regions ;;
    flashsim)    flashsim_comparison ;;
    all)
        dy_weights || exit $?
        all_variables
        dnn_vbf
        vbf_eta_regions
        dnn_studies
        flashsim_comparison
        ;;
    *)
        echo "Usage: $0 {all|dy-weights|all-variables|dnn-vbf|vbf-eta|dnn-studies|flashsim}" >&2
        exit 2
        ;;
esac

log "catena terminata: $action"

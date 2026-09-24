#!/usr/bin/env bash
#
# Attende che la coda Condor si svuoti, aggrega tutto quello che e' aggregabile
# e rifa' tutti i plot e tutti gli studi.
#
#     nohup bash campaigns/finish_and_plot_skim_v4.sh > finish_and_plot.log 2>&1 &
#
# I job in hold non contano: sono le skim 2025 noJetHornVeto, deprioritizzate.
# Ogni stadio prosegue anche se un'era fallisce: un'era incompleta non deve
# impedire di aggregare e plottare le altre.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source env.sh >/dev/null 2>&1

V4_IN="${V4_INPUT:-/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4}"
V4_MAN="${V4_MANIFEST:-/eos/user/v/vdamante/H_mumu/manifests_skim_v4}"
V4_OUT="${V4_OUTPUT:-/eos/user/v/vdamante/H_mumu/skim_v4/post_dy}"
PLOTS="${V4_PLOTS:-plots_Sep16}"
LOGS="${V4_LOGS:-logs_plots_Sep16}"
POLL="${V4_POLL:-300}"
DNN_REGIONS=Z_sideband,Signal_Fit,H_sideband,Signal_ext,mass_inclusive
PLOT_REGIONS=Signal_Fit,Z_sideband,H_sideband,mass_inclusive
ERAS_ALL="${V4_ERAS:-2022 2022EE 2023 2023BPix 2024 2025 2026}"

mkdir -p "$LOGS"
log() { echo "[$(date '+%F %T')] $*"; }

wait_queue() {
    local n
    log "attendo che la coda si svuoti (gli hold non contano)"
    while true; do
        n=$(condor_q -constraint 'JobStatus =!= 5' -af ClusterId 2>/dev/null | wc -l)
        [[ "$n" -eq 0 ]] && break
        log "  ancora $n job"
        sleep "$POLL"
    done
    log "coda vuota"
}

# hadd di un'era per una campagna. Le campagne DNN vogliono regioni e categorie
# esplicite perche' la loro configurazione nasce con la sola Signal_Fit.
hadd_one() {
    local script="$1" outdir="$2" era="$3" mode="$4"; shift 4
    bash "campaigns/$script" hadd --mode "$mode" --eras "$era" --check-level files \
        --input-dir "$V4_IN" --manifest-root "$V4_MAN" --output-dir "$outdir" "$@" \
        > "$LOGS/hadd_${script%%.*}_${era}_${mode}.log" 2>&1
}

stage_hadd() {
    local era
    log "=== hadd, tutte le ere in parallelo"
    for era in $ERAS_ALL; do
        {
            hadd_one all_variables.sh "$V4_OUT/all_variables" "$era" both
            hadd_one dnn_vbf_signal.sh "$V4_OUT/dnn_vbf_weighted" "$era" both \
                --regions "$DNN_REGIONS" --categories VBF --threads 1
            hadd_one dnn_vbf_signal.sh "$V4_OUT/dnn_vbf_dy_unweighted" "$era" central \
                --regions "$DNN_REGIONS" --categories VBF --threads 1
            # VBF divisa per eta dei jet: solo Central, niente sistematiche.
            hadd_one vbf_eta_regions.sh "$V4_OUT/vbf_eta_regions" "$era" central
            hadd_one dnn_vbf_eta_regions.sh "$V4_OUT/dnn_vbf_eta_regions" "$era" central
        } &
    done
    wait
    log "=== hadd finito"
}

stage_merge_syst() {
    local era
    log "=== merge-syst"
    for era in $ERAS_ALL; do
        {
            bash campaigns/all_variables.sh merge-syst --mode both --eras "$era" --check-level files \
                --input-dir "$V4_IN" --manifest-root "$V4_MAN" --output-dir "$V4_OUT/all_variables" \
                > "$LOGS/mergesyst_av_$era.log" 2>&1
            bash campaigns/dnn_vbf_signal.sh merge-syst --mode both --eras "$era" --check-level files \
                --regions "$DNN_REGIONS" --categories VBF --threads 1 \
                --input-dir "$V4_IN" --manifest-root "$V4_MAN" --output-dir "$V4_OUT/dnn_vbf_weighted" \
                > "$LOGS/mergesyst_dnn_$era.log" 2>&1
        } &
    done
    wait
    log "=== merge-syst finito"
}

# Solo le categorie principali, con la scomposizione in componenti di jet e il
# blinding che viene da config/plot/histograms.yaml.
stage_plot() {
    local era
    log "=== plot"
    for era in $ERAS_ALL; do
        {
            bash campaigns/dnn_vbf_signal.sh plot --mode central --eras "$era" --check-level files \
                --regions "$DNN_REGIONS" --categories VBF \
                --plot-regions "$PLOT_REGIONS" --plot-categories VBF --component-composition \
                --input-dir "$V4_IN" --manifest-root "$V4_MAN" \
                --output-dir "$V4_OUT/dnn_vbf_weighted" --plot-output "$PLOTS" \
                > "$LOGS/plot_dnn_$era.log" 2>&1
            bash campaigns/all_variables.sh plot --mode central --eras "$era" --check-level files \
                --plot-regions "$PLOT_REGIONS" --plot-categories VBF,ggF,baseline --component-composition \
                --input-dir "$V4_IN" --manifest-root "$V4_MAN" \
                --output-dir "$V4_OUT/all_variables" --plot-output "$PLOTS" \
                > "$LOGS/plot_av_$era.log" 2>&1
        } &
    done
    wait
    log "=== plot finito"
    grep -h BLIND "$LOGS"/plot_*.log 2>/dev/null | sed 's/^ *//' | sort -u
}

stage_studies() {
    local csv
    csv=$(echo $ERAS_ALL | tr ' ' ',')
    log "=== studi DNN su $csv"
    for action in binning performance sensitivity; do
        bash campaigns/dnn_studies_skim_v4.sh "$action" --eras "$csv" --results-dir "$PLOTS/studies" \
            > "$LOGS/studies_$action.log" 2>&1
    done
    # La ROC rilegge gli skim: da sola, e su un sottoinsieme di file per dataset.
    bash campaigns/dnn_studies_skim_v4.sh roc --eras "$csv" --results-dir "$PLOTS/studies" \
        --roc-max-files "${V4_ROC_MAX_FILES:-30}" > "$LOGS/studies_roc.log" 2>&1
    log "=== studi finiti"
}

stage_flashsim() {
    local era region
    log "=== confronto FullSim/FlashSim"
    for era in $ERAS_ALL; do
        [[ -d "$V4_OUT/all_variables/Central_hadded/Run3_$era" ]] || continue
        for region in Signal_Fit_VBF Z_sideband_VBF H_sideband_VBF mass_inclusive_VBF \
                      Signal_Fit_ggF Z_sideband_ggF H_sideband_ggF mass_inclusive_ggF \
                      mass_inclusive_baseline; do
            python3 tools/compare_flashsim.py --era "Run3_$era" \
                --input-base "$V4_OUT/all_variables/Central_hadded" \
                --output "$PLOTS/flashsim_comparison" --regions "$region" --run \
                > "$LOGS/flashsim_${era}_$region.log" 2>&1 &
        done
        wait
    done
    log "=== FlashSim finito"
}

# Rilancia quello che manca ancora dopo che la coda si e' svuotata: un job
# fallito o un dataset saltato lascia buchi che solo un nuovo submit riempie.
# Al massimo tre giri, poi si prosegue con quello che c'e': se dopo tre
# tentativi manca ancora qualcosa non e' un problema di coda.
stage_fill_gaps() {
    local round era
    for round in 1 2 3; do
        wait_queue
        log "=== giro $round: risottometto quello che manca"
        local before after
        before=$(condor_q -constraint 'JobStatus =!= 5' -af ClusterId 2>/dev/null | wc -l)
        for era in $ERAS_ALL; do
            bash campaigns/all_variables.sh submit --mode both --eras "$era" --memory 8GB \
                --input-dir "$V4_IN" --manifest-root "$V4_MAN" --output-dir "$V4_OUT/all_variables" \
                > "$LOGS/refill_av_$era.log" 2>&1
            bash campaigns/dnn_vbf_signal.sh submit --mode both --eras "$era" --memory 8GB \
                --regions "$DNN_REGIONS" --categories VBF --threads 1 \
                --input-dir "$V4_IN" --manifest-root "$V4_MAN" --output-dir "$V4_OUT/dnn_vbf_weighted" \
                > "$LOGS/refill_dnn_$era.log" 2>&1
        done
        # Variante senza pesi DY: il non-DY si rispecchia, solo il DY e' vero lavoro.
        bash campaigns/dnn_studies_skim_v4.sh submit-nondy --eras "$(echo $ERAS_ALL | tr ' ' ',')" \
            > "$LOGS/refill_unw_nondy.log" 2>&1
        bash campaigns/dnn_studies_skim_v4.sh mirror-nondy --eras "$(echo $ERAS_ALL | tr ' ' ',')" \
            > "$LOGS/refill_unw_mirror.log" 2>&1
        bash campaigns/dnn_studies_skim_v4.sh submit-dy --eras "$(echo $ERAS_ALL | tr ' ' ',')" \
            > "$LOGS/refill_unw_dy.log" 2>&1
        after=$(condor_q -constraint 'JobStatus =!= 5' -af ClusterId 2>/dev/null | wc -l)
        log "  giro $round: $((after - before)) job aggiunti"
        [[ "$after" -eq "$before" ]] && { log "niente da riempire, proseguo"; return 0; }
    done
    wait_queue
    log "tre giri fatti, proseguo con quello che c'e'"
}

action="${1:-all}"
case "$action" in
    wait)       wait_queue ;;
    fill-gaps)  stage_fill_gaps ;;
    hadd)       stage_hadd ;;
    merge-syst) stage_merge_syst ;;
    plot)       stage_plot ;;
    studies)    stage_studies ;;
    flashsim)   stage_flashsim ;;
    all)
        stage_fill_gaps
        stage_hadd
        stage_merge_syst
        stage_plot
        stage_studies
        stage_flashsim
        log "TUTTO COMPLETATO"
        ;;
    *) echo "Usage: $0 {all|wait|fill-gaps|hadd|merge-syst|plot|studies|flashsim}" >&2; exit 2 ;;
esac

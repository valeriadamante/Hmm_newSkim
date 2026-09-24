#!/usr/bin/env bash
#
# Varianti di plot per la produzione skim_v4: con e senza componenti di jet,
# con e senza bande di sistematica, e le combinazioni fra ere.
#
# Vive accanto a finish_and_plot_skim_v4.sh e non lo duplica: quella catena
# produce i plot Central di ogni era, questo aggiunge le varianti.
#
#     bash campaigns/plot_variants_skim_v4.sh all
#     bash campaigns/plot_variants_skim_v4.sh syst --eras 2022,2025
#     bash campaigns/plot_variants_skim_v4.sh merged
#
# Ogni variante scrive in una sua sottocartella di plots_Sep16, cosi' non si
# sovrascrivono a vicenda e si capisce dal percorso cosa si sta guardando.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source env.sh >/dev/null 2>&1

V4_IN="${V4_INPUT:-/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4}"
V4_MAN="${V4_MANIFEST:-/eos/user/v/vdamante/H_mumu/manifests_skim_v4}"
V4_OUT="${V4_OUTPUT:-/eos/user/v/vdamante/H_mumu/skim_v4/post_dy}"
PLOTS="${V4_PLOTS:-plots_Sep16}"
LOGS="${V4_LOGS:-logs_plots_Sep16}"

eras="2022,2022EE,2023,2023BPix,2024,2025,2026"
PLOT_REGIONS=Signal_Fit,Z_sideband,H_sideband,mass_inclusive
PLOT_CATEGORIES=VBF,ggF,baseline

# Le combinazioni richieste. Il nome della pseudo-era non puo' coincidere con
# un'era fisica, altrimenti workflow.py si rifiuta di partire.
COMBOS=(
  "2022,2023=Run3_2022_2023"
  "2022,2025=Run3_2022_2025"
  "2022,2026=Run3_2022_2026"
)

while (($#)); do
    case "$1" in
        --eras)  eras="$2"; shift 2 ;;
        --plots) PLOTS="${2%/}"; shift 2 ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) break ;;
    esac
done
action="${1:-all}"

mkdir -p "$LOGS"
log() { echo "[$(date '+%F %T')] $*"; }
era_list() { echo "$eras" | tr ',' ' '; }

# $1 sottocartella di output, poi le opzioni che distinguono la variante.
plot_av() {
    local tag="$1" era="$2"; shift 2
    bash campaigns/all_variables.sh plot --eras "$era" --check-level files \
        --plot-regions "$PLOT_REGIONS" --plot-categories "$PLOT_CATEGORIES" \
        --input-dir "$V4_IN" --manifest-root "$V4_MAN" \
        --output-dir "$V4_OUT/all_variables" --plot-output "$PLOTS/$tag" "$@" \
        > "$LOGS/plotvar_${tag}_${era}.log" 2>&1
}

# Central, con la scomposizione in componenti di jet sotto ogni distribuzione.
action_components() {
    local era
    log "=== Central CON componenti di jet -> $PLOTS/central_components"
    for era in $(era_list); do
        plot_av central_components "$era" --mode central --component-composition &
    done
    wait
}

# Central, solo processi aggregati: piu' leggibile per un talk.
action_no_components() {
    local era
    log "=== Central SENZA componenti -> $PLOTS/central_plain"
    for era in $(era_list); do
        plot_av central_plain "$era" --mode central &
    done
    wait
}

# Bande di sistematica: richiede Hists_systMerged, quindi merge-syst completo.
action_syst() {
    local era ok=0
    log "=== con bande di sistematica -> $PLOTS/systematics"
    for era in $(era_list); do
        if [[ ! -d "$V4_OUT/all_variables/Hists_systMerged/Run3_$era" ]]; then
            log "  Run3_$era: manca Hists_systMerged, salto (serve merge-syst)"
            continue
        fi
        ok=1
        plot_av systematics "$era" --mode both --component-composition &
    done
    wait
    [[ "$ok" -eq 0 ]] && log "  nessuna era pronta: lancia prima 'merge-syst'"
    return 0
}

action_merge_syst() {
    local era
    log "=== merge-syst"
    for era in $(era_list); do
        bash campaigns/all_variables.sh merge-syst --mode both --eras "$era" --check-level files \
            --input-dir "$V4_IN" --manifest-root "$V4_MAN" --output-dir "$V4_OUT/all_variables" \
            > "$LOGS/plotvar_mergesyst_$era.log" 2>&1 &
    done
    wait
    log "=== merge-syst finito"
}

action_merge_eras() {
    local entry pair name
    log "=== merge-era per le combinazioni richieste"
    for entry in "${COMBOS[@]}"; do
        pair="${entry%%=*}"; name="${entry##*=}"
        log "  $pair -> $name"
        bash campaigns/all_variables.sh merge-era --mode central --eras "$pair" \
            --merged-era "$name" --check-level files \
            --input-dir "$V4_IN" --manifest-root "$V4_MAN" --output-dir "$V4_OUT/all_variables" \
            > "$LOGS/plotvar_mergeera_$name.log" 2>&1 \
            || log "    fallito: serve Central_hadded completo per entrambe le ere"
    done
}

action_merged_plots() {
    local entry pair name
    log "=== plot delle ere combinate -> $PLOTS/merged"
    for entry in "${COMBOS[@]}"; do
        pair="${entry%%=*}"; name="${entry##*=}"
        bash campaigns/all_variables.sh plot --mode central --merged --eras "$pair" \
            --merged-era "$name" --check-level files \
            --plot-regions "$PLOT_REGIONS" --plot-categories "$PLOT_CATEGORIES" \
            --component-composition \
            --input-dir "$V4_IN" --manifest-root "$V4_MAN" \
            --output-dir "$V4_OUT/all_variables" --plot-output "$PLOTS/merged" \
            > "$LOGS/plotvar_merged_$name.log" 2>&1 \
            || log "  $name: plot fallito, manca il merge-era"
    done
}

case "$action" in
    components)     action_components ;;
    no-components)  action_no_components ;;
    syst)           action_syst ;;
    merge-syst)     action_merge_syst ;;
    merge-eras)     action_merge_eras ;;
    merged)         action_merge_eras; action_merged_plots ;;
    merged-plots)   action_merged_plots ;;
    all)
        action_components
        action_no_components
        action_merge_syst
        action_syst
        action_merge_eras
        action_merged_plots
        ;;
    *) echo "Usage: $0 [--eras CSV] {all|components|no-components|merge-syst|syst|merge-eras|merged|merged-plots}" >&2; exit 2 ;;
esac
log "fatto: $action"

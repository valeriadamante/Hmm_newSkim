#!/usr/bin/env bash
#
# Disegna i plot con le bande di sistematica era per era, appena il merge-syst
# di quell'era compare. Non aspetta che finisca tutto: la prima era pronta
# viene plottata mentre le altre sono ancora in aggregazione.
#
#     nohup bash campaigns/plot_syst_when_ready.sh > plot_syst.log 2>&1 &
#
# Si ferma quando ha plottato tutto quello che era possibile e il driver degli
# hadd non gira piu'.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source env.sh >/dev/null 2>&1

V4_IN=/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4
V4_MAN=/eos/user/v/vdamante/H_mumu/manifests_skim_v4
V4_OUT=/eos/user/v/vdamante/H_mumu/skim_v4/post_dy
PLOTS="${V4_PLOTS:-plots_Sep16/systematics}"
LOGS="${V4_LOGS:-logs_plots_Sep16}"
POLL="${V4_POLL:-300}"
REG=Signal_Fit,Z_sideband,H_sideband,mass_inclusive
DNNREG=Z_sideband,Signal_Fit,H_sideband,Signal_ext,mass_inclusive
ERAS="${V4_ERAS:-2022 2022EE 2023 2023BPix 2024 2025 2026}"

mkdir -p "$LOGS"
log() { echo "[$(date '+%F %T')] $*"; }

declare -A done_plot=()

plot_one() {
    local camp="$1" era="$2"
    case "$camp" in
      all_variables)
        bash campaigns/all_variables.sh plot --mode both --eras "$era" --check-level files \
          --plot-regions "$REG" --plot-categories VBF,ggF,baseline --component-composition \
          --input-dir $V4_IN --manifest-root $V4_MAN \
          --output-dir $V4_OUT/all_variables --plot-output "$PLOTS" \
          > "$LOGS/plotsyst_av_$era.log" 2>&1 ;;
      dnn_vbf_weighted)
        bash campaigns/dnn_vbf_signal.sh plot --mode both --eras "$era" --check-level files \
          --regions "$DNNREG" --categories VBF \
          --plot-regions "$REG" --plot-categories VBF --component-composition \
          --input-dir $V4_IN --manifest-root $V4_MAN \
          --output-dir $V4_OUT/dnn_vbf_weighted --plot-output "$PLOTS" \
          > "$LOGS/plotsyst_dnn_$era.log" 2>&1 ;;
    esac
}

log "in attesa dei merge-syst; plotto ogni era appena compare"
idle_rounds=0
while true; do
    produced=0
    for camp in all_variables dnn_vbf_weighted; do
        for era in $ERAS; do
            key="$camp/$era"
            [[ -n "${done_plot[$key]:-}" ]] && continue
            merged="$V4_OUT/$camp/Hists_systMerged/Run3_$era"
            # Serve che ci sia, e che contenga qualcosa: una directory creata a
            # meta' dal merge non basta.
            [[ -d "$merged" ]] || continue
            [[ -n "$(ls "$merged"/*.root 2>/dev/null | head -1)" ]] || continue
            log "=== $camp Run3_$era: merge-syst presente, disegno"
            if plot_one "$camp" "$era"; then
                log "    fatto: $PLOTS/<campagna>/Run3_$era"
            else
                log "    plot uscito con errore, vedi $LOGS/plotsyst_*_$era.log"
            fi
            done_plot[$key]=1
            produced=1
        done
    done

    if pgrep -u "$USER" -f "hadd_what_is_ready" >/dev/null; then
        idle_rounds=0
    elif [[ "$produced" -eq 0 ]]; then
        # Il driver degli hadd e' finito e non c'e' piu' niente di nuovo:
        # un paio di giri di grazia, poi si esce.
        idle_rounds=$((idle_rounds + 1))
        [[ "$idle_rounds" -ge 2 ]] && break
    fi
    sleep "$POLL"
done

log "=== plot con sistematiche completati: ${#done_plot[@]} combinazioni"
for key in "${!done_plot[@]}"; do log "    $key"; done
grep -h BLIND "$LOGS"/plotsyst_*.log 2>/dev/null | sed 's/^ *//' | sort -u

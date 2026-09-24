#!/usr/bin/env bash
#
# Catena completa Run 3 da skim_v4: skim -> manifest -> pesi DY -> istogrammi
# -> hadd/merge -> studi. Estende run3_post_skim_chain.sh a monte (produzione
# degli skim e dei manifest) e a valle (horn veto, merge-era).
#
# Attende Condor fra uno stadio e l'altro, quindi va lanciata in background:
#
#     nohup bash campaigns/run3_full_chain.sh all > chain_full.log 2>&1 &
#
# Ogni stadio e' invocabile da solo per riprendere. `status` non scrive nulla.

set -uo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
# shellcheck disable=SC1091
source env.sh >/dev/null 2>&1

ERAS="${V4_ERAS:-2022,2022EE,2023,2023BPix,2024,2025,2026}"
# Ere per cui esiste anche la variante senza jet horn veto.
NOHORN_ERAS="${V4_NOHORN_ERAS:-2025,2026}"
SKIM_BASE="${V4_SKIM_BASE:-/eos/cms/store/group/phys_higgs/cmshmm/vdamante}"
MANIFEST="${V4_MANIFEST:-/eos/user/v/vdamante/H_mumu/manifests_skim_v4}"
OUTPUT="${V4_OUTPUT:-/eos/user/v/vdamante/H_mumu/skim_v4/post_dy}"
# Gli istogrammi dei pesi DY NON stanno sotto post_dy: hanno un albero
# proprio, gia' popolato per cinque ere. Derivarlo da OUTPUT rifarebbe da
# zero quello che esiste e spezzerebbe la produzione su due percorsi.
DY_OUTPUT="${V4_DY_OUTPUT:-/eos/user/v/vdamante/H_mumu/skim_v4/DY_weights}"
DNN_REGIONS="${V4_DNN_REGIONS:-Z_sideband,Signal_Fit,H_sideband,Signal_ext,mass_inclusive}"
POLL="${V4_POLL:-300}"
PRIO="${V4_PRIORITY:-100}"

log() { echo "[$(date '+%F %T')] $*"; }
eras_list() { printf '%s\n' "$ERAS" | tr ',' '\n'; }
full_era() { case "$1" in Run3_*) printf '%s' "$1" ;; *) printf 'Run3_%s' "$1" ;; esac; }

# Un solo albero di skim: skim_v4. I 42 file che la patch aveva riscritto sono
# stati copiati dentro skim_v4 il 16/09/2026 e skim_v4_fixed non esiste piu'
# come percorso di riferimento.
# Attenzione: `find` senza -L non scende nelle directory collegate e riporta
# zero file dove in realta' ce ne sono migliaia. Ogni conteggio qui usa -L.
input_for_era() {
    printf '%s/skim_v4' "$SKIM_BASE"
}

# Un solo base input per le campagne multi-era: si usa quello della maggioranza
# e le ere che ne vogliono un altro girano separatamente.
group_eras_by_input() {
    local era base
    declare -gA ERAS_BY_INPUT=()
    while read -r era; do
        [[ -n $era ]] || continue
        base="$(input_for_era "$era")"
        ERAS_BY_INPUT["$base"]="${ERAS_BY_INPUT[$base]:+${ERAS_BY_INPUT[$base]},}$era"
    done < <(eras_list)
}

wait_condor() {
    local pattern="$1" n
    log "attendo i job '$pattern'"
    while true; do
        n=$(condor_q -af JobBatchName 2>/dev/null | grep -Ec "$pattern")
        [[ "$n" -eq 0 ]] && break
        sleep "$POLL"
    done
    log "coda '$pattern' vuota"
}

# I job appena sottomessi passano davanti agli altri job dell'utente. Non cambia
# la quota rispetto agli altri utenti del pool, solo l'ordine interno.
bump_priority() {
    local pattern="$1" clusters
    clusters=$(condor_q -constraint "regexp(\"$pattern\", JobBatchName)" -af ClusterId 2>/dev/null | sort -un)
    [[ -n $clusters ]] || return 0
    # shellcheck disable=SC2086
    condor_prio -p "$PRIO" $clusters >/dev/null 2>&1 || true
}

# ----------------------------------------------------------------- 1. skim

skims() {
    local era
    while read -r era; do
        [[ -n $era ]] || continue
        log "=== skim $era"
        if [[ ",$NOHORN_ERAS," == *",$era,"* ]]; then
            bash campaigns/run3_skim_v4.sh submit --era "$era" --variant both
        else
            bash campaigns/run3_skim_v4.sh submit --era "$era"
        fi
    done < <(eras_list)
    bump_priority "Skim"
    wait_condor "Skim"
    log "=== skim completati"
}

# ------------------------------------------------------------- 2. manifest

manifests() {
    log "=== manifest di validazione (con veto)"
    bash campaigns/run3_dy_weights_skim_v4.sh manifests --eras "$ERAS"
    local era base
    while read -r era; do
        [[ -n $era ]] || continue
        [[ ",$NOHORN_ERAS," == *",$era,"* ]] || continue
        base="$(input_for_era "$era")_noJetHornVeto"
        [[ -d "$base/$(full_era "$era")" ]] || { log "salto $era: niente skim senza veto"; continue; }
        log "=== manifest senza veto $era"
        bash analysis/scripts/validate.sh --era "$(full_era "$era")" --datasets skim_cfg \
            --root-input-folder "$base" --json-input-folder "$base" \
            --output-dir "${MANIFEST}_noJetHornVeto" --condor --missing-only \
            --condor-label "Validate_noHorn_${era}"
    done < <(eras_list)
    bump_priority "DYWeights_skim_v4|Validate_noHorn"
    wait_condor "DYWeights_skim_v4|Validate_noHorn"
    log "=== manifest completati"
    bash campaigns/run3_dy_weights_skim_v4.sh status --eras "$ERAS" || true
}

# ------------------------------------------------------------ 3. pesi DY

dy_weights() {
    group_eras_by_input
    local base eras stage rc
    for base in "${!ERAS_BY_INPUT[@]}"; do
        eras="${ERAS_BY_INPUT[$base]}"
        # jet -> pTll -> N(jet): ogni stadio legge il JSON scritto dal precedente,
        # quindi l'ordine non e' parallelizzabile. run ritorna 3 quando attende.
        for stage in jet ptll njets; do
            log "=== pesi DY [$eras] stadio $stage"
            bash campaigns/dy_weights.sh run --eras "$eras" --mode central \
                --input-root "$base" --json-root "$base" \
                --manifest-root "$MANIFEST" --output-root "$DY_OUTPUT"
            rc=$?
            if [[ "$rc" -eq 3 ]]; then
                bump_priority "DY012J|DYPTLL|DYNJETS"
                wait_condor "DY012J|DYPTLL|DYNJETS"
                # Ripeti lo stesso stadio: ora fa hadd e fit e passa al successivo.
                bash campaigns/dy_weights.sh run --eras "$eras" --mode central \
                    --input-root "$base" --json-root "$base" \
                    --manifest-root "$MANIFEST" --output-root "$DY_OUTPUT"
                rc=$?
                [[ "$rc" -eq 3 ]] && { bump_priority "DY012J|DYPTLL|DYNJETS"; wait_condor "DY012J|DYPTLL|DYNJETS"; }
            elif [[ "$rc" -ne 0 ]]; then
                log "ATTENZIONE: stadio $stage uscito con $rc"
            fi
        done
        log "=== verifica payload [$eras]"
        bash campaigns/dy_weights.sh check-weights --weight-stage all --eras "$eras" \
            --mode central --input-root "$base" --json-root "$base" \
            --manifest-root "$MANIFEST" --output-root "$DY_OUTPUT" \
            || log "check-weights ha segnalato problemi per $eras"
    done
}

# ------------------------------------------------- 4. istogrammi finali

histograms() {
    group_eras_by_input
    local base eras mode
    for base in "${!ERAS_BY_INPUT[@]}"; do
        eras="${ERAS_BY_INPUT[$base]}"
        for mode in central syst; do
            log "=== all_variables [$eras] $mode"
            bash campaigns/all_variables.sh submit --mode "$mode" --eras "$eras" \
                --input-dir "$base" --manifest-root "$MANIFEST" \
                --output-dir "$OUTPUT/all_variables" \
                --plot-output results/skim_v4/all_variables || true
            log "=== DNN VBF [$eras] $mode"
            # --jes regrouped: senza questo la config Sep03 produce una sola
            # nuisance JES Total invece delle 11 famiglie regrouped.
            bash campaigns/dnn_vbf_signal.sh submit --mode "$mode" --eras "$eras" \
                --regions "$DNN_REGIONS" --categories VBF \
                --systematics-layout split --jes regrouped \
                --input-dir "$base" --manifest-root "$MANIFEST" \
                --output-dir "$OUTPUT/dnn_vbf_weighted" || true
        done
        # Variante senza pesi DY: serve solo il DY, il resto e' identico e viene
        # rispecchiato da mirror-nondy.
        log "=== DNN VBF senza pesi DY [$eras]"
        bash campaigns/dnn_studies_skim_v4.sh submit-nondy --eras "$eras" \
            --input-dir "$base" --manifest-root "$MANIFEST" || true
        bash campaigns/dnn_studies_skim_v4.sh submit-dy --eras "$eras" \
            --input-dir "$base" --manifest-root "$MANIFEST" || true
    done
    bump_priority "AllVariables|Sep03_DNN"
    wait_condor "AllVariables|Sep03_DNN"
    log "=== mirror dei raw non DY nella variante senza pesi"
    bash campaigns/dnn_studies_skim_v4.sh mirror-nondy --eras "$ERAS" || true

    # Horn veto: default --weights none, quindi non dipende dai payload DY.
    local era
    while read -r era; do
        [[ -n $era ]] || continue
        [[ ",$NOHORN_ERAS," == *",$era,"* ]] || continue
        base="$(input_for_era "$era")"
        [[ -d "${base}_noJetHornVeto/$(full_era "$era")" ]] || { log "salto horn $era"; continue; }
        log "=== horn veto $era (con/senza)"
        bash campaigns/jet_horn_veto.sh submit --eras "$era" --variant both \
            --input-root "$base" --manifest-root "$MANIFEST" \
            --output-dir "$OUTPUT/horn_veto" || true
    done < <(eras_list)
    bump_priority "JetHornVeto"
    wait_condor "JetHornVeto"
}

# ------------------------------------------------- 5. hadd e merge-syst

hadd_merge() {
    group_eras_by_input
    local base eras action
    for base in "${!ERAS_BY_INPUT[@]}"; do
        eras="${ERAS_BY_INPUT[$base]}"
        for action in hadd merge-syst merge-era; do
            log "=== all_variables [$eras] $action"
            bash campaigns/all_variables.sh "$action" --mode both --eras "$eras" \
                --input-dir "$base" --manifest-root "$MANIFEST" \
                --output-dir "$OUTPUT/all_variables" || log "all_variables $action: problemi"
            log "=== DNN VBF [$eras] $action"
            bash campaigns/dnn_vbf_signal.sh "$action" --mode both --eras "$eras" \
                --regions "$DNN_REGIONS" --categories VBF \
                --systematics-layout split --jes regrouped \
                --input-dir "$base" --manifest-root "$MANIFEST" \
                --output-dir "$OUTPUT/dnn_vbf_weighted" || log "DNN $action: problemi"
        done
        log "=== hadd variante senza pesi DY [$eras]"
        bash campaigns/dnn_studies_skim_v4.sh hadd --eras "$eras" \
            --input-dir "$base" --manifest-root "$MANIFEST" || log "hadd studi: problemi"
    done
    log "=== hadd horn veto"
    bash campaigns/jet_horn_veto.sh hadd --eras "$NOHORN_ERAS" --variant both \
        --output-dir "$OUTPUT/horn_veto" || log "horn hadd: problemi"
    deep_check
}

# Il check di campagna apre i ROOT ma non decomprime gli istogrammi: file
# corrotti o con chiavi mancanti passano. Questa scansione li trova.
deep_check() {
    log "=== scansione profonda degli hadd"
    python3 - "$OUTPUT" <<'PY'
import sys, pathlib
try:
    import uproot
except ImportError:
    print("uproot non disponibile: scansione saltata"); sys.exit(0)
bad = total = 0
for f in sorted(pathlib.Path(sys.argv[1]).glob("**/*hadded*/**/*.root")):
    total += 1
    try:
        h = uproot.open(f)
        for k in h.keys():
            o = h[k]
            if hasattr(o, "values"):
                o.values()
    except Exception as exc:
        bad += 1
        print(f"CORROTTO {f}: {type(exc).__name__}: {str(exc)[:80]}")
print(f"{total} hadd controllati, {bad} da rigenerare")
PY
}

# ------------------------------------------------------------- 6. studi

studies() {
    log "=== studi DNN (binning-opt, performance, ROC, sensitivita')"
    bash campaigns/dnn_studies_skim_v4.sh studies --eras "$ERAS" || log "studies: problemi"
    log "=== confronto FlashSim"
    local era
    while read -r era; do
        [[ -n $era ]] || continue
        python3 tools/compare_flashsim.py --era "$(full_era "$era")" \
            --input-base "$OUTPUT/all_variables/Hists_hadded" \
            --output results/skim_v4/flashsim_comparison --run \
            || log "FlashSim $era: non riuscito"
    done < <(eras_list)
}

# ------------------------------------------------------------ status

status() {
    group_eras_by_input
    echo "Ere:      $ERAS"
    echo "Output:   $OUTPUT"
    for base in "${!ERAS_BY_INPUT[@]}"; do echo "Input:    $base  ->  ${ERAS_BY_INPUT[$base]}"; done
    echo
    printf '%-14s %8s %8s %10s %12s %12s %10s\n' ERA SKIM MANIF PAYLOAD ALLVARS DNN_VBF DNN_UNW
    local era fe n
    while read -r era; do
        [[ -n $era ]] || continue
        fe="$(full_era "$era")"
        printf '%-14s' "$fe"
        n=$(find -L "$(input_for_era "$era")/$fe" -name '*.root' 2>/dev/null | wc -l); printf '%9s' "$n"
        n=$(ls "$MANIFEST/$fe"/*.json 2>/dev/null | wc -l);                        printf '%9s' "$n"
        printf '%11s' "$(python3 - "$fe" <<'PY'
import sys, pathlib, yaml
cfg = yaml.safe_load(open(f"config/{sys.argv[1]}/process_names.yaml"))
rj = next((i["reweight_jsons"] for i in cfg.values()
           if isinstance(i, dict) and isinstance(i.get("reweight_jsons"), dict)), {})
print(sum(pathlib.Path(p).is_file() for p in rj.values()), "/3", sep="")
PY
)"
        for prod in all_variables dnn_vbf_weighted dnn_vbf_dy_unweighted; do
            n=$(find -L "$OUTPUT/$prod" -path "*Central/$fe/*.root" -size +0 2>/dev/null | wc -l)
            h=$(find -L "$OUTPUT/$prod" -path "*Central_hadded/$fe/*.root" -size +0 2>/dev/null | wc -l)
            printf '%13s' "$n/$h"
        done
        echo
    done < <(eras_list)
    echo
    echo "raw/hadd per produzione. Coda:"
    condor_q -totals 2>/dev/null | grep "Total for $USER" || true
}

case "${1:-status}" in
    skims)      skims ;;
    manifests)  manifests ;;
    dy-weights) dy_weights ;;
    histograms) histograms ;;
    hadd)       hadd_merge ;;
    deep-check) deep_check ;;
    studies)    studies ;;
    status)     status ;;
    all)
        skims
        manifests
        dy_weights
        histograms
        hadd_merge
        studies
        ;;
    *)
        echo "Usage: $0 {all|skims|manifests|dy-weights|histograms|hadd|deep-check|studies|status}" >&2
        exit 2
        ;;
esac
log "run3_full_chain: ${1:-status} terminato"

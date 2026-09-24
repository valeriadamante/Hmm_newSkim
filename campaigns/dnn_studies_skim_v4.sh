#!/usr/bin/env bash
#
# Binning-opt del DNN output e performance con/senza pesi, da skim_v4.
#
# Due produzioni Central della stessa regione/categoria:
#   dnn_vbf_weighted     reweight DY jet-component + ptll + njets attivi
#   dnn_vbf_dy_unweighted  --dy-weights '' (pesi MC nominali mantenuti)
# piu' le ROC pesata/non pesata calcolate direttamente dagli skim, dove
# l'unica differenza fra le due curve e' l'uso di weight__Central.
#
# Tutti gli output finiscono sotto results/skim_v4/, una cartella per studio,
# variante ed era. La composizione dei processi e' in config/dnn_studies.yaml.

set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"

usage() {
cat <<'EOF'
Usage: bash campaigns/dnn_studies_skim_v4.sh ACTION [options]

Actions:
  paths      Mostra percorsi, ere e disponibilita' degli input.
  submit-nondy  Sottomette i dataset non DY: non serve alcun payload DY.
  submit-dy     Sottomette i soli dataset DY nelle due varianti.
  mirror-nondy  Collega i raw non DY dalla campagna pesata a quella senza pesi.
  submit     submit-nondy + submit-dy.
  check      Controlla lo stadio histograms delle due produzioni.
  hadd       Esegue l'hadd delle due produzioni.
  binning    Ottimizzazione del binning DNN, per era e per variante.
  performance Confronto pesata/senza-pesi-DY dagli istogrammi, per era.
  roc        ROC pesata vs non pesata dagli skim, per era e combinata.
  sensitivity Scan sensibilita' vs numero di bin, powheg e amcatnlo.
  studies    binning + performance + roc + sensitivity.

Options:
  --eras CSV        Default: $V4_STUDY_ERAS (tutte tranne il 2026).
  --input-dir PATH  Skim base. Default: $V4_INPUT.
  --manifest-root PATH  Default: $V4_MANIFEST.
  --output-dir PATH Base istogrammi. Default: $V4_OUTPUT.
  --results-dir PATH Base risultati. Default: results/skim_v4.
  --regions CSV     Regioni prodotte. Default: le cinque memorizzate.
  --memory VALUE    Memoria Condor. Default: quella della configurazione
                    di campagna (20GB con 8 CPU).
  --roc-max-files N File ROOT per dataset letti dalla ROC. 0 = tutti.
  --dy-weights CSV  Reweight DY della variante pesata, fra jet-component,
                    ptll e njets. Default: tutti e tre. Ogni combinazione ha
                    la sua directory istogrammi e la sua cartella risultati,
                    cosi' gli stage si confrontano senza sovrascriversi.
  --dry-run         Stampa i comandi senza eseguirli.

Dal 17/09/2026 anche il 2024 e' nel default: ha skim, manifest e payload DY
come le altre, e prima ne restava fuori per un commento non piu' vero.

Il 2026 e' escluso di proposito, non per mancanza di input: il DNN per quell'era
non va prodotto. Per includerlo serve passarlo esplicitamente con --eras.

Gli stadi che leggono gli istogrammi (binning, performance, sensitivity) saltano
con un avviso le ere il cui hadd non c'e' ancora e proseguono con le altre;
'roc' legge gli skim e non ha questo vincolo.
EOF
}

action="${1:-paths}"
[[ $# -eq 0 ]] || shift
case "$action" in
    paths|submit|submit-nondy|submit-dy|mirror-nondy|check|hadd|binning|performance|roc|sensitivity|studies) ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown action: $action" >&2; usage >&2; exit 2 ;;
esac

: "${V4_INPUT:=/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4}"
: "${V4_MANIFEST:=/eos/user/v/vdamante/H_mumu/manifests_skim_v4}"
: "${V4_OUTPUT:=/eos/user/v/vdamante/H_mumu/skim_v4/post_dy}"
: "${V4_STUDY_ERAS:=2022,2022EE,2023,2023BPix,2024,2025}"

eras="$V4_STUDY_ERAS"
input_dir="$V4_INPUT"
manifest_root="$V4_MANIFEST"
output_dir="$V4_OUTPUT"
results_dir="results/skim_v4"
# Le cinque regioni memorizzate, come la produzione gia' presente su EOS.
# Gli studi leggono solo Signal_Fit_VBF, ma i file ne contengono di piu'.
regions="Z_sideband,Signal_Fit,H_sideband,Signal_ext,mass_inclusive"
memory=""
dy_weights="jet-component,ptll,njets"
# La ROC rilegge gli skim con AsNumpy: su un'era grande arriva a ~23 GB di RSS.
# Con un sottoinsieme di file per dataset scende in proporzione, i pesi vengono
# riscalati e la curva resta la stessa, solo meno precisa.
roc_max_files=0
dry_run=0

while (($#)); do
    case "$1" in
        --eras)          eras="$2";          shift 2 ;;
        --input-dir|--input-root) input_dir="${2%/}"; shift 2 ;;
        --manifest-root) manifest_root="${2%/}"; shift 2 ;;
        --output-dir|--output-root) output_dir="${2%/}"; shift 2 ;;
        --results-dir)   results_dir="${2%/}"; shift 2 ;;
        --regions)       regions="$2";       shift 2 ;;
        --memory)        memory="$2";        shift 2 ;;
        --dy-weights)    dy_weights="$2";    shift 2 ;;
        --roc-max-files) roc_max_files="$2"; shift 2 ;;
        --dry-run)       dry_run=1;          shift ;;
        -h|--help)       usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

# Vuoto significa: usa la memoria della configurazione di campagna.
memory_opt=()
[[ -n $memory ]] && memory_opt=(--memory "$memory")

# Etichetta canonica della combinazione di pesi: stessa combinazione ->
# stessa directory, a prescindere dall'ordine in cui e' stata scritta.
variant_label="$(python3 - "$dy_weights" <<'PYLABEL'
import sys
known = ["jet-component", "ptll", "njets"]
requested = [x for x in sys.argv[1].replace(",", " ").split() if x]
unknown = [x for x in requested if x not in known]
if unknown:
    sys.exit("Unknown DY weight: " + ",".join(unknown))
if not requested:
    sys.exit("--dy-weights vuoto: la variante senza pesi e' gia' dy_unweighted")
ordered = [x for x in known if x in requested]
print("weighted" if ordered == known else
      "dy" + "_".join(x.replace("jet-component", "012j") for x in ordered))
PYLABEL
)" || exit 1

# I non DY sono identici in ogni variante: si producono una volta sola qui e
# si rispecchiano nelle directory delle varianti.
nondy_dir="$output_dir/dnn_vbf_weighted"
weighted_dir="$output_dir/dnn_vbf_$variant_label"
unweighted_dir="$output_dir/dnn_vbf_dy_unweighted"

# Le due produzioni condividono regione, categoria e input: solo i pesi DY
# cambiano, altrimenti il confronto non isolerebbe il reweighting.
# I thread restano quelli della configurazione di campagna (8 CPU / 8 thread).
# --jes regrouped e --systematics-layout split sono obbligatori: la config
# Sep03 impone --jes total --systematics-layout together, che collassa il JES
# in una sola nuisance CMS_scale_j_total invece delle 11 famiglie regrouped
# usate da all_variables. Gli argomenti della riga di comando prevalgono su
# CAMPAIGN_OPTIONS, quindi vanno passati qui a ogni invocazione.
common_opts=(--eras "$eras" --regions "$regions" --categories VBF
             --systematics-layout split --jes regrouped
             --input-dir "$input_dir" --manifest-root "$manifest_root")

# I reweight DY custom si applicano solo ai dataset che common.apply_custom_weights
# riconosce come DY (nome che inizia per "dy" o contiene "dyto"). Tutto il resto
# produce istogrammi identici nelle due varianti, quindi va prodotto una volta
# sola nella campagna pesata e poi rispecchiato in quella senza pesi.
NONDY_GROUPS=data,EWK_105_160,signals,flash_backgrounds,SingleH,SingleTop,TTX,TT,W,DiTriBoson
DY_GROUPS=region_auto

run() {
    printf '+'
    printf ' %q' "$@"
    printf '\n'
    ((dry_run)) || "$@"
}

era_list() {
    printf '%s\n' "$eras" | tr ',' '\n'
}

full_era() {
    case "$1" in Run3_*) printf '%s' "$1" ;; *) printf 'Run3_%s' "$1" ;; esac
}

campaign() {
    local variant="$1"; shift
    case "$variant" in
        weighted)
            run bash campaigns/dnn_vbf_signal.sh "$@" "${common_opts[@]}" \
                --dy-weights "$dy_weights" --output-dir "$weighted_dir"
            ;;
        nondy)
            run bash campaigns/dnn_vbf_signal.sh "$@" "${common_opts[@]}" \
                --dy-weights '' --output-dir "$nondy_dir"
            ;;
        dy_unweighted)
            run bash campaigns/dnn_vbf_signal.sh "$@" "${common_opts[@]}" \
                --dy-weights '' --output-dir "$unweighted_dir"
            ;;
    esac
}

hadded() {
    case "$1" in
        weighted) printf '%s/Central_hadded' "$weighted_dir" ;;
        dy_unweighted) printf '%s/Central_hadded' "$unweighted_dir" ;;
    esac
}

require_hadded() {
    local variant="$1" era="$2" directory
    directory="$(hadded "$variant")/$(full_era "$era")"
    if [[ ! -d $directory ]]; then
        echo "Missing hadd for $variant $era: $directory" >&2
        # --dry-run must still print the plan, like the other campaign scripts.
        ((dry_run)) || {
            echo "Run 'bash campaigns/dnn_studies_skim_v4.sh hadd' first." >&2
            return 1
        }
    fi
    printf '%s' "$directory"
}

action_paths() {
    cat <<EOF
Repository:       $repo
Eras:             $eras
Skim input:       $input_dir
Manifests:        $manifest_root
Histograms:       $output_dir
  non-DY store:   $nondy_dir
  DY weights:     $dy_weights  (variante: $variant_label)
  weighted:       $weighted_dir
  dy_unweighted:  $unweighted_dir
Results:          $results_dir
Process config:   config/dnn_studies.yaml
EOF
    echo
    printf '%-14s %-8s %-10s %-10s %s\n' ERA SKIM MANIFEST DY_PAYLOAD HADD
    local era full skim manifest payload hadd
    while read -r era; do
        [[ -n $era ]] || continue
        full="$(full_era "$era")"
        [[ -d $input_dir/$full ]] && skim=yes || skim=no
        [[ -d $manifest_root/$full ]] && manifest=yes || manifest=no
        payload="$(python3 - "$full" <<'PY'
import sys, pathlib, yaml
era = sys.argv[1]
cfg = yaml.safe_load(open(f"config/{era}/process_names.yaml"))
paths = []
for info in cfg.values():
    if isinstance(info, dict) and isinstance(info.get("reweight_jsons"), dict):
        paths.extend(info["reweight_jsons"].values())
paths = sorted(set(paths))
print("yes" if paths and all(pathlib.Path(p).is_file() for p in paths) else "no")
PY
)"
        [[ -d $(hadded weighted)/$full ]] && hadd=yes || hadd=no
        printf '%-14s %-8s %-10s %-10s %s\n' "$full" "$skim" "$manifest" "$payload" "$hadd"
    done < <(era_list)
}

action_submit_nondy() {
    # Nessun payload DY serve qui: apply_custom_weights esce prima di leggerlo
    # per i dataset non DY, e raw_products non registra la dipendenza dai JSON.
    # --dy-weights '' toglie anche il controllo di campagna sui payload, che e'
    # globale e bloccherebbe il submit mentre i pesi sono in ri-derivazione.
    # Sugli istogrammi non DY non cambia nulla, per costruzione.
    campaign nondy submit --mode central "${memory_opt[@]}" \
        --datasets "$NONDY_GROUPS"
    echo
    echo "Poi: bash campaigns/dnn_studies_skim_v4.sh mirror-nondy"
}

action_submit_dy() {
    # Il submit ritorna 1 quando alcuni manifest mancano pur avendo sottomesso
    # il resto. Con set -e la seconda variante non partirebbe mai e il confronto
    # con/senza pesi resterebbe senza DY da un lato, che e' esattamente il caso
    # in cui misura il DY mancante invece dell'effetto dei pesi.
    local rc=0
    campaign weighted submit --mode central "${memory_opt[@]}" \
        --datasets "$DY_GROUPS" || rc=$?
    campaign dy_unweighted submit --mode central "${memory_opt[@]}" \
        --datasets "$DY_GROUPS" || rc=$?
    [[ $rc -eq 0 ]] || echo "[WARN] submit DY: input non disponibili (rc=$rc)" >&2
}

action_mirror_nondy() {
    # Symlink invece di copia: gli istogrammi non DY sono identici byte a byte
    # fra le due varianti e la campagna senza pesi ne ha comunque bisogno per
    # avere lo stesso fondo totale della pesata.
    local era full destination
    while read -r era; do
        [[ -n $era ]] || continue
        full="$(full_era "$era")"
        for destination in "$weighted_dir" "$unweighted_dir"; do
            [[ $destination == "$nondy_dir" ]] && continue
            run python3 tools/mirror_nondy_histograms.py \
                --source "$nondy_dir/Central/$full" \
                --destination "$destination/Central/$full" \
                $( ((dry_run)) && printf %s --dry-run )
        done
    done < <(era_list)
}

action_submit() {
    action_submit_nondy
    action_submit_dy
    echo
    echo "Attendere i job Condor, poi: bash campaigns/dnn_studies_skim_v4.sh check"
}

action_check() {
    campaign weighted check --stage histograms --mode central
    campaign dy_unweighted check --stage histograms --mode central
}

action_hadd() {
    campaign weighted hadd --mode central
    campaign dy_unweighted hadd --mode central
}

action_binning() {
    local era full variant directory
    local rc=0
    while read -r era; do
        [[ -n $era ]] || continue
        full="$(full_era "$era")"
        for variant in weighted dy_unweighted; do
            directory="$(require_hadded "$variant" "$era")" || { rc=1; continue; }
            run python3 tools/optimize_dnn_binning.py \
                --input "$directory" --era "$full" \
                --region Signal_Fit_VBF --variable DNN_NNOutput \
                --signal-pattern "$SIGNAL_PATTERNS" \
                --background-pattern "$BACKGROUND_PATTERNS" \
                --max-bins "$MAX_BINS" \
                --min-background "$MIN_BACKGROUND" \
                --max-relative-background-stat "$MAX_REL_STAT" \
                --relative-background-systematic "$REL_SYST" \
                --output "$results_dir/dnn_binning/${variant/weighted/$variant_label}/$full"
        done
    done < <(era_list)
    # Un\'era senza hadd non deve far fallire le altre: si segnala con rc
    # ma il ciclo prosegue.
    return "$rc"
}

action_performance() {
    local era full weighted_era unweighted_era
    local rc=0
    while read -r era; do
        [[ -n $era ]] || continue
        full="$(full_era "$era")"
        weighted_era="$(require_hadded weighted "$era")" || { rc=1; continue; }
        unweighted_era="$(require_hadded dy_unweighted "$era")" || { rc=1; continue; }
        # L'ordine conta: compare_dnn_performance tratta la prima campagna come
        # riferimento, quindi i delta misurano l'effetto dei pesi DY.
        run python3 tools/compare_dnn_performance.py \
            --campaign "dy_unweighted=$(hadded dy_unweighted)" \
            --campaign "weighted=$(hadded weighted)" \
            --era "$full" --region Signal_Fit_VBF --variable DNN_NNOutput \
            --signal-pattern "$SIGNAL_PATTERNS" \
            --background-pattern "$BACKGROUND_PATTERNS" \
            --exclude-pattern "$EXCLUDE_PATTERNS" \
            --output "$results_dir/dnn_performance/dy_weights_$variant_label/$full"
    done < <(era_list)
    # Un\'era senza hadd non deve far fallire le altre: si segnala con rc
    # ma il ciclo prosegue.
    return "$rc"
}

action_roc() {
    # Una sola invocazione: --per-era-output scrive il PNG di ogni era e il JSON
    # porta per_era_summary, quindi non serve rileggere gli skim due volte.
    local era
    local -a all_eras=()
    while read -r era; do
        [[ -n $era ]] || continue
        all_eras+=("$(full_era "$era")")
    done < <(era_list)
    run python3 tools/dnn_roc_from_skims.py \
        --era "${all_eras[@]}" --input-dir "$input_dir" \
        --region Signal_Fit --category VBF --per-era-output \
        --dy-weights "$dy_weights" \
        --max-files-per-dataset "$roc_max_files" \
        --output "$results_dir/dnn_performance/roc_from_skims/$variant_label/all_eras"
}

action_sensitivity() {
    local era full directory generator
    local rc=0
    while read -r era; do
        [[ -n $era ]] || continue
        full="$(full_era "$era")"
        directory="$(require_hadded weighted "$era")" || { rc=1; continue; }
        for generator in powheg amcatnlo; do
            run python3 studies/sensitivity_vs_nbins.py \
                --input-dir "$directory" \
                --signal-generator "$generator" \
                --minimum-background "$MIN_BACKGROUND" \
                --output "$results_dir/sensitivity/${full}_${generator}"
        done
    done < <(era_list)
    # Un\'era senza hadd non deve far fallire le altre: si segnala con rc
    # ma il ciclo prosegue.
    return "$rc"
}

# Letture da config/dnn_studies.yaml, cosi' i tre studi non divergono.
read -r SIGNAL_PATTERNS BACKGROUND_PATTERNS EXCLUDE_PATTERNS \
        MAX_BINS MIN_BACKGROUND MAX_REL_STAT REL_SYST < <(
    python3 - "$repo" <<'PYCFG'
import sys
sys.path.insert(0, sys.argv[1])
from common.dnn_studies import (
    background_processes, binning_constraints, exclude_patterns, signal_processes,
)
constraints = binning_constraints()
print(
    ",".join(signal_processes("powheg")),
    ",".join(background_processes()),
    ",".join(exclude_patterns()),
    constraints["max_bins"],
    constraints["min_background"],
    constraints["max_relative_background_stat"],
    constraints["relative_background_systematic"],
)
PYCFG
)

case "$action" in
    paths)        action_paths ;;
    submit)       action_submit ;;
    submit-nondy) action_submit_nondy ;;
    submit-dy)    action_submit_dy ;;
    mirror-nondy) action_mirror_nondy ;;
    check)       action_check ;;
    hadd)        action_hadd ;;
    binning)     action_binning ;;
    performance) action_performance ;;
    roc)         action_roc ;;
    sensitivity) action_sensitivity ;;
    studies)
        action_binning
        action_performance
        action_roc
        action_sensitivity
        ;;
esac

#!/usr/bin/env bash

set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$repo"

usage() {
cat <<'EOF'
Usage: bash campaigns/run3_skim_v4.sh {plan|dry-run|submit} [options]

  --era ERA                   Repeatable; default: all seven Run3 eras.
  --variant both|with|without Default: both for 2025/2026.
  --output-base PATH          Default: /eos/cms/store/group/phys_higgs/cmshmm/vdamante
  --dataset NAME              Exact dataset, repeatable.
  --max-submit-jobs N         Per era/variant.
  --max-parallel-jobs N       Per submitter.
  --n-events N                Test events per job; uses isolated skim_v4_testN paths.
  --proxy PATH                Forward a VOMS proxy.
  --overwrite                 Re-submit chunks even if output files already exist.

plan prints commands only.
dry-run resolves missing chunks.
submit queues missing chunks.

2022–2024 use skim_v4.
2025 uses skim_v4_withHornVeto and skim_v4_noHornVeto.
2026 uses skim_v4 and skim_v4_noJetHornVeto.
EOF
}

mode="${1:-plan}"
[[ $# -eq 0 ]] || shift

case "$mode" in
    plan|dry-run|submit)
        ;;
    -h|--help)
        usage
        exit 0
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac


eras=()
variant=both
extra=()
n_events=-1
overwrite=0

output_base=/eos/cms/store/group/phys_higgs/cmshmm/vdamante


while (($#)); do
    case "$1" in

        --overwrite)
            overwrite=1
            shift
            ;;

        --era)
            [[ $# -ge 2 ]] || {
                usage >&2
                exit 2
            }
            eras+=("${2#Run3_}")
            shift 2
            ;;

        --variant)
            [[ $# -ge 2 ]] || {
                usage >&2
                exit 2
            }
            variant="$2"
            shift 2
            ;;

        --output-base)
            [[ $# -ge 2 ]] || {
                usage >&2
                exit 2
            }
            output_base="${2%/}"
            shift 2
            ;;

        --n-events)
            [[ $# -ge 2 ]] || {
                usage >&2
                exit 2
            }
            n_events="$2"
            shift 2
            ;;

        --dataset|--max-submit-jobs|--max-parallel-jobs|--proxy)
            [[ $# -ge 2 ]] || {
                usage >&2
                exit 2
            }
            extra+=("$1" "$2")
            shift 2
            ;;

        -h|--help)
            usage
            exit 0
            ;;

        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done


case "$variant" in
    both|with|without)
        ;;
    *)
        echo "Invalid variant: $variant" >&2
        usage >&2
        exit 2
        ;;
esac


[[ "$n_events" == -1 || "$n_events" =~ ^[1-9][0-9]*$ ]] || {
    echo 'Invalid --n-events' >&2
    exit 2
}


((${#eras[@]})) || eras=(
    2022
    2022EE
    2023
    2023BPix
    2024
    2025
    2026
)


for era in "${eras[@]}"; do

    case "$era" in
        2022|2022EE|2023|2023BPix|2024|2025|2026)
            ;;
        *)
            echo "Invalid era: $era" >&2
            exit 2
            ;;
    esac


    variants=(configured)

    if [[ "$era" == 2025 || "$era" == 2026 ]]; then
        variants=(with without)

        if [[ "$variant" != both ]]; then
            variants=("$variant")
        fi
    fi


    for horn in "${variants[@]}"; do

        label=skim_v4

        if [[ "$n_events" != -1 ]]; then
            label+="_test${n_events}"
        fi


        if [[ "$horn" == without ]]; then
            label+=_noJetHornVeto
        fi


        cmd=(
            python3
            htcondor/condorsubmit.py
            skim
            --era "Run3_${era}"
            --output-dir "${output_base}/${label}"
            --state-dir "${repo}/htcondor/${label}"
            --jet-horn-veto "$horn"
            --n-events "$n_events"
            "${extra[@]}"
        )


        if ((overwrite)); then
            cmd+=(--overwrite)
        fi


        if [[ "$mode" == submit ]]; then
            cmd+=(--submit)
        else
            cmd+=(--no-submit)
        fi


        printf '%q ' "${cmd[@]}"
        printf '\n'


        if [[ "$mode" != plan ]]; then
            "${cmd[@]}"
        fi

    done
done
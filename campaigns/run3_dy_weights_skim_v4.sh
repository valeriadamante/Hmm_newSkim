#!/usr/bin/env bash
# Generate validation manifests, then advance the ordered DY fit campaign.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"

action="${1:-status}"
if (($#)); then shift; fi
case "$action" in manifests|status|run) ;; *) echo "Usage: $0 {manifests|status|run} [--eras CSV]" >&2; exit 2 ;; esac

eras=2022,2022EE,2023,2023BPix,2024,2025,2026
input=/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4
manifests=/eos/user/v/vdamante/H_mumu/manifests_skim_v4
output=/eos/user/v/vdamante/H_mumu/skim_v4/DY_weights

while (($#)); do
  case "$1" in
    --eras) eras="${2:?Missing era list}"; shift 2 ;;
    --input-dir) input="${2:?Missing input dir}"; shift 2 ;;
    --manifest-root) manifests="${2:?Missing manifest root}"; shift 2 ;;
    --output-root) output="${2:?Missing output root}"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

IFS=, read -r -a selected <<< "$eras"
for era in "${selected[@]}"; do
  [[ -d "config/Run3_${era}" ]] || { echo "Unknown era: $era" >&2; exit 2; }
done

if [[ "$action" == manifests ]]; then
  for era in "${selected[@]}"; do
    bash analysis/scripts/validate.sh \
      --era "Run3_${era}" --datasets skim_cfg \
      --root-input-folder "$input" --json-input-folder "$input" \
      --output-dir "$manifests" --condor --missing-only \
      --condor-label "DYWeights_skim_v4_${era}"
  done
  exit 0
fi

python3 - "$manifests" "$eras" <<'PY'
import sys
from pathlib import Path
from campaigns.workflow import WEIGHT_STAGES, datasets, load_campaign

root = Path(sys.argv[1])
missing = []
for era in sys.argv[2].split(','):
    needed = set()
    for _, campaign, _ in WEIGHT_STAGES:
        needed.update(datasets('Run3_' + era, load_campaign(campaign).groups))
    absent = [name for name in sorted(needed) if not (root / ('Run3_' + era) / (name + '.json')).is_file()]
    print(f'Run3_{era}: {len(needed) - len(absent)}/{len(needed)} DY-campaign manifests')
    missing.extend(('Run3_' + era, name) for name in absent)
if missing:
    print(f'{len(missing)} manifests still missing; run manifests and wait for validation jobs.', file=sys.stderr)
    sys.exit(3)
PY

if [[ "$action" == run ]]; then
  bash campaigns/dy_weights.sh run \
    --eras "$eras" --mode central --weight-stage all \
    --input-root "$input" --json-root "$input" \
    --manifest-root "$manifests" --output-root "$output"
fi

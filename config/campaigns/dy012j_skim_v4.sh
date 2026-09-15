#!/usr/bin/env bash

CAMPAIGN_ROOT="/eos/user/v/vdamante/H_mumu/skim_v4/DY_weights/jet"
CAMPAIGN_LABEL="DY012J_skim_v4"
HIST_DIR_PREFIX=""
ERAS=(2022 2022EE 2023 2023BPix 2024 2025 2026)
SYSTEMATICS=(Central)
# The 105-160 DY sample is routed only to Signal_Fit/H_sideband; this fit uses Z_sideband.
DATASETS="data,DY_amcatnlo,EWK,SingleH,SingleTop,TTX,TT,W,DiTriBoson"
CHUNK_SIZE=1
REQUEST_CPUS=4
REQUEST_MEMORY=8GB
RDF_THREADS=4
VARIABLE_BATCH_SIZE=4

HIST_ARGS=(
  --variables m_mumu eta_signed_vs_pt_leadingjet
              eta_signed_vs_pt_subleadingjet eta_signed_vs_pt_vbfjet1
  --mass-regions Z_sideband
  # Exclusive reco-jet multiplicity regions are produced for every dataset,
  # data included: each stage of the fit needs its own disjoint data sample.
  --categories ggF VBF ggF_0J ggF_1J ggF_ge2J
  --pu-hard-jet-components
  --all-mc-jet-components
  --no-dy-jet-component-reweight
  --no-dy-ptll-reweight
  --no-dy-njets-reweight
)

campaign_fit() {
  local hadded="${CAMPAIGN_ROOT}/Central_hadded"
  local output_base="reweights/dy_012j_reweight_skim_v4"
  local requested_era="${1:-}"

  derive_012j() {
    local era="$1"
    shift
    python3 tools/derive_dy_012j_reweight.py \
      --era "${era}" \
      --input-dir "$@" \
      --output-dir "${output_base}/${era}" \
      --output-json "${output_base}/${era}/dy_012j_reweight.json" \
      --output-root "${output_base}/${era}/dy_012j_reweight.root"
  }

  case "${requested_era}" in
    2022|2022EE|Run3_2022|Run3_2022EE|2022_2022EE|Run3_2022_2022EE)
      derive_012j Run3_2022_2022EE \
        "${hadded}/Run3_2022" "${hadded}/Run3_2022EE"
      ;;
    2023|2023BPix|Run3_2023|Run3_2023BPix|2023_2023BPix|Run3_2023_2023BPix)
      derive_012j Run3_2023_2023BPix \
        "${hadded}/Run3_2023" "${hadded}/Run3_2023BPix"
      ;;
    2024|Run3_2024)
      derive_012j Run3_2024 "${hadded}/Run3_2024"
      ;;
    2025|Run3_2025|2026|Run3_2026)
      local fit_era="$(normalize_era "${requested_era}")"
      derive_012j "$fit_era" "${hadded}/$fit_era"
      ;;
    "")
      derive_012j Run3_2022_2022EE \
        "${hadded}/Run3_2022" "${hadded}/Run3_2022EE"
      derive_012j Run3_2023_2023BPix \
        "${hadded}/Run3_2023" "${hadded}/Run3_2023BPix"
      derive_012j Run3_2024 "${hadded}/Run3_2024"
      derive_012j Run3_2025 "${hadded}/Run3_2025"
      ;;
    *)
      echo "[ERROR] Unsupported DY012J fit era: ${requested_era}" >&2
      return 2
      ;;
  esac
}

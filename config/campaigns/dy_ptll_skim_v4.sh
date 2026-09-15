#!/usr/bin/env bash

# Derive the DY pT(ll) correction after applying the skim_v4 0/1/2J weights.
CAMPAIGN_ROOT="/eos/user/v/vdamante/H_mumu/skim_v4/DY_weights/ptll"
CAMPAIGN_LABEL="DYPTLL_skim_v4"
HIST_DIR_PREFIX=""
ERAS=(2022 2022EE 2023 2023BPix 2024 2025 2026)
SYSTEMATICS=(Central)
DATASETS="data,DY_amcatnlo,EWK,SingleH,SingleTop,TTX,TT,W,DiTriBoson"
CHUNK_SIZE=1
REQUEST_CPUS=4
REQUEST_MEMORY=8GB
RDF_THREADS=4

HIST_ARGS=(
  --variables pt_mumu
  --mass-regions Z_sideband
  --categories ggF_0J ggF_1J ggF_ge2J VBF_ge2J
  # Apply the fitted component correction to the inclusive DY output.  Do not
  # request --pu-hard-jet-components: this campaign must not split ROOT files.
  --dy-jet-component-reweight
  --no-dy-ptll-reweight
  --no-dy-njets-reweight
)

campaign_fit() {
  local hadded="${CAMPAIGN_ROOT}/Central_hadded"
  local output_base="reweights/dy_ptll_reweight_skim_v4"
  local combined_2022="Run3_2022_2022EE"
  local combined_2023="Run3_2023_2023BPix"
  local requested_era="${1:-}"

  derive_ptll() {
    local era="$1"
    python3 tools/derive_dy_ptll_njets_reweight.py \
      --era "${era}" \
      --input-dir "${hadded}/${era}" \
      --output-dir "${output_base}/${era}" \
      --output-json "${output_base}/${era}/dy_ptll_reweight_smart.json" \
      --output-root "${output_base}/${era}/dy_ptll_reweight.root" \
      --smart-rebin
  }

  if [[ -n "${requested_era}" ]]; then
    derive_ptll "$(normalize_era "${requested_era}")"
    return
  fi

  python3 tools/hmumu.py merge-eras "${hadded}" \
    --eras Run3_2022,Run3_2022EE --output-era "${combined_2022}" \
    --missing-only --run
  python3 tools/hmumu.py merge-eras "${hadded}" \
    --eras Run3_2023,Run3_2023BPix --output-era "${combined_2023}" \
    --missing-only --run

  derive_ptll "${combined_2022}"
  derive_ptll "${combined_2023}"
  # derive_ptll Run3_2024
  # derive_ptll Run3_2025
}

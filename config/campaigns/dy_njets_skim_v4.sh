#!/usr/bin/env bash

# Derive the DY N(jet) correction after applying the 0/1/2J and pT(ll)
# corrections.  Start with 2022; add the other eras only after their updated
# pT(ll) payloads have been derived and configured in process_names.yaml.
CAMPAIGN_ROOT="/eos/user/v/vdamante/H_mumu/skim_v4/DY_weights/njets"
CAMPAIGN_LABEL="DYNJETS_skim_v4"
HIST_DIR_PREFIX=""
ERAS=(2022 2022EE 2023 2023BPix 2024 2025 2026)
SYSTEMATICS=(Central)
DATASETS="data,DY_amcatnlo,EWK,SingleH,SingleTop,TTX,TT,W,DiTriBoson"
CHUNK_SIZE=1
REQUEST_CPUS=4
REQUEST_MEMORY=8GB
RDF_THREADS=4

HIST_ARGS=(
  --variables N_SelectedJets
  --mass-regions Z_sideband
  --categories ggF VBF
  # Apply both upstream DY corrections to the inclusive DY output.  Do not
  # split component ROOT files and do not apply the correction being derived.
  --dy-jet-component-reweight
  --dy-ptll-reweight
  --no-dy-njets-reweight
)

campaign_fit() {
  local hadded="${CAMPAIGN_ROOT}/Central_hadded"
  local output_base="reweights/dy_njets_reweight_skim_v4"
  local combined_2022="Run3_2022_2022EE"
  local combined_2023="Run3_2023_2023BPix"
  local requested_era="${1:-}"

  derive_njets() {
    local era="$1"
    local output="${output_base}/${era}"
    python3 tools/derive_dy_njets_reweight.py \
      --era "${era}" \
      --input-dir "${hadded}/${era}" \
      --output-dir "${output}" \
      --output-json "${output}/dy_njets_reweight.json" \
      --output-root "${output}/dy_njets_reweight.root"
  }

  if [[ -n "${requested_era}" ]]; then
    derive_njets "$(normalize_era "${requested_era}")"
    return
  fi

  python3 tools/hmumu.py merge-eras "${hadded}" \
    --eras Run3_2022,Run3_2022EE --output-era "${combined_2022}" \
    --missing-only --run
  python3 tools/hmumu.py merge-eras "${hadded}" \
    --eras Run3_2023,Run3_2023BPix --output-era "${combined_2023}" \
    --missing-only --run

  derive_njets "${combined_2022}"
  derive_njets "${combined_2023}"
}

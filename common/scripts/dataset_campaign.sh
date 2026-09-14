#!/usr/bin/env bash
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANALYSIS_PATH="${ANALYSIS_PATH:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
export ANALYSIS_PATH
cd "${ANALYSIS_PATH}"

usage() {
  cat <<'EOF'
Usage:
  analysis/scripts/validate.sh|histograms/scripts/hists.sh|histograms/scripts/systematics.sh \
    --datasets GROUP[,GROUP...] --era ERA [options] [-- STAGE_OPTS...]

Dataset groups:
  skim_cfg (canonical selection from config/ERA/skim_cfg.yaml)
  data
  DiTriBoson
  DY_amcatnlo
  DY_amcatnlo_105_160
  DY_012J
  DY_minnlo
  EWK
  EWK_105_160
  FlashSim
  signals
  SingleH
  SingleTop
  TTX
  TT
  W
  other_signals
  mc (all configured MC groups for the selected era)

Options:
  --datasets GROUPS       Comma-separated groups, "all", or "skim_cfg".
  --dataset-name NAME     Run one explicit dataset instead of a group.
  --chunk-size N          Override chunk size for selected jobs. Histogram and
                          systematic jobs default to 1; validation defaults to
                          the requested CPU count.
  --era ERA              Era to run, e.g. Run3_2022.
  --input-folder NAME    Backward-compatible stage input base. Validation: skim JSON base;
                         histograms/systematics: validation-manifest base.
  --root-input-folder PATH
                         Skimmed ROOT ntuple base directory/file base.
  --json-input-folder PATH
                         Skim-report JSON base directory/file base. Defaults to ROOT input base.
  --manifest-input-folder PATH
                         Validation manifest base. Defaults to --input-folder.
  --additional-metadata-input PATH
                         Extra metadata JSON base directory/file base. Repeatable.
  --systematics NAME[,NAME...]
                         Systematics/groups passed to hist_maker.py. Repeatable.
                         Defaults: Central for histograms, all for systematics.
  --file-open-retries N  Attempts to open/validate each ROOT/JSON file. Default: 3.
  --file-open-retry-delay SEC
                         Delay between file-open attempts. Default: 2 seconds.
  --output-suffix TEXT   Suffix appended to newHists_${era}.
  --output-dir DIR       Override the complete output directory.
  --extra-opts TEXT      Extra hist_maker.py options as a quoted string.
  --condor               Submit one HTCondor job per selected dataset for this stage.
  --condor-dir DIR       Directory for Condor submit/log files. Defaults by stage:
                          htcondor/validation, htcondor/hists, or htcondor/systematics.
  --condor-label TEXT    Short campaign label used instead of the dataset-group list.
  --job-flavour TEXT     HTCondor JobFlavour. Default: workday.
  --request-cpus N       HTCondor request_cpus. Default: 4.
  --request-memory TEXT  HTCondor request_memory. Default: 8GB.
  --request-disk TEXT    HTCondor request_disk. Default: 4GB.
  --max-jobs N           Submit at most N missing histogram jobs.
  --max-parallel-jobs N  Materialize at most N jobs at a time in this submission.
  --summary-file FILE    Append one TSV monitoring summary line to FILE.
  --queued-registry-file FILE
                          Treat outputs listed in FILE as already submitted.
  --missing-only         In local mode, run only incomplete/missing stage outputs.
  --exclude-dataset CSV  Exclude exact dataset names after group expansion.
                          Condor always skips complete outputs unless --force is used.
  --print-existing       Print each complete output skipped by --missing-only.
                          Existing outputs are silent by default in local mode.
  --deep-output-check    Open and validate every existing ROOT/JSON output.
                         Histogram campaigns otherwise use a fast size check.
  --erase-existing       Remove already produced histogram files before submitting.
  --force                Submit selected jobs even if output files already exist.
  --dry-run              Print commands without running them.
  -h, --help             Show this help.

Examples:
  histograms/scripts/hists.sh --datasets skim_cfg --era Run3_2025
  histograms/scripts/hists.sh --datasets DiTriBoson,data --era Run3_2022
  histograms/scripts/hists.sh --datasets DY_amcatnlo --era Run3_2024 --output-suffix _DNN -- --variables DNN_NNOutput
  histograms/scripts/hists.sh --datasets all --era Run3_2025 --extra-opts "--rdf-threads 8"
  histograms/scripts/hists.sh --datasets signals,EWK --era Run3_2024 --condor -- --variables m_mumu
EOF
}

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

append_words() {
  local target_name="$1"
  shift
  local -n target_ref="${target_name}"
  local word
  for word in "$@"; do
    target_ref+=("${word}")
  done
}

append_extra_opts_string() {
  local opts_string="$1"
  [[ -z "${opts_string}" ]] && return
  # shellcheck disable=SC2206
  local opts_array=(${opts_string})
  append_words extra_opts "${opts_array[@]}"
}

split_csv() {
  local csv="$1"
  local -n out_ref="$2"
  local item
  IFS=',' read -r -a out_ref <<< "${csv}"
  for item in "${out_ref[@]}"; do
    [[ -n "${item}" ]] || die "Empty dataset group in --datasets '${csv}'"
  done
}

strip_condor_arg_quotes() {
  local value="$1"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s' "${value}"
}

short_label() {
  local raw="$1"
  local max_len="${2:-48}"
  local sanitized hash prefix_len

  sanitized="${raw//[^A-Za-z0-9_.-]/_}"
  if [[ ${#sanitized} -le ${max_len} ]]; then
    printf '%s' "${sanitized}"
    return
  fi

  hash="$(printf '%s' "${sanitized}" | cksum | awk '{print $1}')"
  prefix_len=$((max_len - ${#hash} - 3))
  [[ ${prefix_len} -ge 8 ]] || prefix_len=8
  printf '%s_h%s' "${sanitized:0:${prefix_len}}" "${hash}"
}

condor_group_label() {
  local requested_group

  if [[ -n "${single_dataset_name}" ]]; then
    short_label "dataset_${single_dataset_name}" 48
    return
  fi

  for requested_group in "${dataset_groups[@]}"; do
    if [[ "$(normalize_group "${requested_group}")" == "all" ]]; then
      printf 'all'
      return
    fi
  done

  short_label "$(IFS=_; echo "${normalized_groups[*]}")" 48
}

hist_output_exists() {
  local output_file="$1"
  [[ -s "${output_file}" ]] && return 0

  local size
  size="$(stat -c '%s' "${output_file}" 2>/dev/null || true)"
  [[ "${size}" =~ ^[0-9]+$ && "${size}" -gt 0 ]]
}

stage_output_exists() {
  if [[ "$1" != validation && ${deep_output_check:-0} -eq 0 ]]; then
    hist_output_exists "$2"
    return
  fi
  python3 "${ANALYSIS_PATH}/tools/check_stage_output.py" "$1" "$2"
}

component_outputs_exist() {
  local output_file="$1"
  python3 "${ANALYSIS_PATH}/tools/check_vbf_component_outputs.py" \
    "${output_file}" "${required_component_regions}"
}

histogram_output_path() {
  local output_base="$1"
  local era_name="$2"
  local dataset_name="$3"
  local suffix="$4"
  printf '%s/%s/%s%s.root' "${output_base}" "${era_name}" "${dataset_name}" "${suffix}"
}

manifest_path() {
  local manifest_base="$1"
  local era_name="$2"
  local dataset_name="$3"
  local era_manifest="${manifest_base}/${era_name}/${dataset_name}.json"
  local flat_manifest="${manifest_base}/${dataset_name}.json"

  if [[ -f "${era_manifest}" || ! -f "${flat_manifest}" ]]; then
    printf '%s' "${era_manifest}"
  else
    printf '%s' "${flat_manifest}"
  fi
}

declare -A active_histogram_outputs=()
active_histogram_outputs_loaded=0

is_output_already_queued() {
  local wanted_output="$1"
  command -v condor_q >/dev/null 2>&1 || return 1

  if [[ ${active_histogram_outputs_loaded} -eq 1 ]]; then
    [[ -n "${active_histogram_outputs[${wanted_output}]:-}" ]]
    return
  fi
  local owner queue_snapshot
  owner="$(id -un)"
  queue_snapshot="$(condor_q "${owner}" \
    -constraint 'JobStatus == 1 || JobStatus == 2 || JobStatus == 6' \
    -af ProcId Arguments)" || die "Cannot read Condor queue; refusing possible duplicate submissions"
  active_histogram_outputs_loaded=1

  local line _ad_proc _analysis_arg jobs_file_arg queued_proc_id _queued_mode _queued_era _queued_manifest _queued_root _queued_json queued_output_dir rest
  local job_line queued_dataset _queued_chunk queued_suffix _queued_opts queued_output

  while IFS= read -r line; do
    [[ -n "${line}" ]] || continue
    read -r _ad_proc _analysis_arg jobs_file_arg queued_proc_id _queued_mode _queued_era _queued_manifest _queued_root _queued_json queued_output_dir rest <<< "${line}"
    jobs_file_arg="$(strip_condor_arg_quotes "${jobs_file_arg:-}")"
    queued_proc_id="$(strip_condor_arg_quotes "${queued_proc_id:-}")"
    queued_output_dir="$(strip_condor_arg_quotes "${queued_output_dir:-}")"
    [[ -n "${jobs_file_arg:-}" && -n "${queued_proc_id:-}" && -n "${queued_output_dir:-}" ]] || continue
    [[ "${queued_output_dir}" == "${output_dir}" ]] || continue
    [[ -r "${jobs_file_arg}" ]] || continue
    [[ "${queued_proc_id}" =~ ^[0-9]+$ ]] || continue

    job_line="$(sed -n "$((queued_proc_id + 1))p" "${jobs_file_arg}" 2>/dev/null || true)"
    [[ -n "${job_line}" ]] || continue

    IFS=$'\t' read -r queued_dataset _queued_chunk queued_suffix _queued_opts <<< "${job_line}"
    [[ "${queued_suffix}" == "-" ]] && queued_suffix=""
    queued_output="$(histogram_output_path "${queued_output_dir}" "${_queued_era}" "${queued_dataset}" "${queued_suffix}")"

    active_histogram_outputs["${queued_output}"]=1
  done <<< "${queue_snapshot}"

  [[ -n "${active_histogram_outputs[${wanted_output}]:-}" ]]
}

is_output_in_registry() {
  local output_file="$1"
  [[ -n "${queued_registry_file}" && -s "${queued_registry_file}" ]] || return 1
  grep -Fxq "${output_file}" "${queued_registry_file}"
}

require_known_era() {
  local era="$1"
  case "${era}" in
    Run3_2022|Run3_2022EE|Run3_2023|Run3_2023BPix|Run3_2024|Run3_2025|Run3_2026) ;;
    *) die "Unknown era '${era}'" ;;
  esac
}

dataset_is_configured() {
  local era="$1"
  local dataset_name="$2"
  local samples_file="config/${era}/samples.yaml"

  [[ -r "${samples_file}" ]] || return 0
  awk -v dataset="${dataset_name}" '
    $0 ~ "^[A-Za-z0-9_]+:" {
      key = $1
      sub(/:$/, "", key)
      if (key == dataset) {
        found = 1
        exit
      }
    }
    END { exit(found ? 0 : 1) }
  ' "${samples_file}"
}

configured_dataset_key() {
  local era="$1"
  local dataset_name="$2"
  local samples_file="config/${era}/samples.yaml"

  [[ -r "${samples_file}" ]] || return 1
  awk -v dataset="${dataset_name}" '
    $0 ~ "^[A-Za-z0-9_]+:" {
      key = $1
      sub(/:$/, "", key)
      if (tolower(key) == tolower(dataset)) {
        print key
        found = 1
        exit
      }
    }
    END { exit(found ? 0 : 1) }
  ' "${samples_file}"
}

configured_dataset_alias() {
  local era="$1"
  local dataset_name="$2"
  local candidate
  local candidates=()

  case "${dataset_name}" in
    VBFHto2Mu_M120) candidates=(VBFHto2Mu_M120_amcatnlo) ;;
    VBFHto2Mu_M125_amcatnlo) candidates=(VBFHto2Mu_m125_amcatnlo) ;;
    VBFHto2Mu_M130) candidates=(VBFHto2Mu_M130_amcatnlo) ;;
    TBbarQto2Q_t_channel_4FS|TBbarQtoLNu_t_channel_4FS) candidates=(TBbarQ_t_channel_4FS) ;;
    TbarBQto2Q_t_channel_4FS|TbarBQtoLNu_t_channel_4FS) candidates=(TbarBQ_t_channel_4FS) ;;
    TTZH_ZHto4B) candidates=(TTZH) ;;
    DYto2Mu_MLL_105to160_amcatnloFXFX_VBFFiltered) candidates=(DYto2Mu_MLL_105to160_amcatnloFXFX_Fil_VBF) ;;
    DYto2Mu_MLL105To160_FlashSim) candidates=(DYto2Mu_MLL_105to160_amcatnloFXFX_Flashsim) ;;
  esac

  for candidate in "${candidates[@]}"; do
    if configured_dataset_key "${era}" "${candidate}" >/dev/null; then
      configured_dataset_key "${era}" "${candidate}"
      return 0
    fi
  done

  return 1
}

resolve_configured_dataset() {
  local era="$1"
  local dataset_name="$2"
  local resolved

  if resolved="$(configured_dataset_key "${era}" "${dataset_name}")"; then
    printf '%s' "${resolved}"
    return 0
  fi

  if resolved="$(configured_dataset_alias "${era}" "${dataset_name}")"; then
    printf '%s' "${resolved}"
    return 0
  fi

  return 1
}

add_job() {
  local dataset_name="$1"
  local chunk_size="$2"
  local file_suffix="${3:-}"
  local specific_opts=()

  if [[ $# -ge 3 ]]; then
    shift 3
    specific_opts=("$@")
  fi

  job_datasets+=("${dataset_name}")
  job_chunk_sizes+=("${chunk_size}")
  job_file_suffixes+=("${file_suffix}")
  job_specific_opts+=("${specific_opts[*]}")
}

drop_unconfigured_jobs() {
  local era="$1"
  local filtered_datasets=()
  local filtered_chunk_sizes=()
  local filtered_file_suffixes=()
  local filtered_specific_opts=()
  local dataset_name
  local resolved_dataset
  local skipped=0

  for i in "${!job_datasets[@]}"; do
    dataset_name="${job_datasets[$i]}"
    if resolved_dataset="$(resolve_configured_dataset "${era}" "${dataset_name}")"; then
      if [[ "${resolved_dataset}" != "${dataset_name}" ]]; then
        echo "[INFO] Mapping ${dataset_name} -> ${resolved_dataset} for config/${era}/samples.yaml"
      fi
      filtered_datasets+=("${resolved_dataset}")
      filtered_chunk_sizes+=("${job_chunk_sizes[$i]}")
      filtered_file_suffixes+=("${job_file_suffixes[$i]}")
      filtered_specific_opts+=("${job_specific_opts[$i]}")
    else
      echo "[INFO] Skipping ${dataset_name}: not present in config/${era}/samples.yaml"
      skipped=$((skipped + 1))
    fi
  done

  # Always keep the resolved arrays.  Previously they were assigned only when
  # at least one dataset was skipped, so valid aliases (notably
  # DY ... _VBFFiltered -> ... _Fil_VBF) were silently discarded whenever all
  # selected datasets existed in the era configuration.
  job_datasets=("${filtered_datasets[@]}")
  job_chunk_sizes=("${filtered_chunk_sizes[@]}")
  job_file_suffixes=("${filtered_file_suffixes[@]}")
  job_specific_opts=("${filtered_specific_opts[@]}")
}

filter_out_dataset() {
  local excluded_dataset="$1"
  local filtered_datasets=()
  local filtered_chunk_sizes=()
  local filtered_file_suffixes=()
  local filtered_specific_opts=()

  for i in "${!job_datasets[@]}"; do
    if [[ "${job_datasets[$i]}" == "${excluded_dataset}" ]]; then
      echo "[INFO] Excluding ${excluded_dataset} from ${era}"
      continue
    fi
    filtered_datasets+=("${job_datasets[$i]}")
    filtered_chunk_sizes+=("${job_chunk_sizes[$i]}")
    filtered_file_suffixes+=("${job_file_suffixes[$i]}")
    filtered_specific_opts+=("${job_specific_opts[$i]}")
  done

  job_datasets=("${filtered_datasets[@]}")
  job_chunk_sizes=("${filtered_chunk_sizes[@]}")
  job_file_suffixes=("${filtered_file_suffixes[@]}")
  job_specific_opts=("${filtered_specific_opts[@]}")
}

deduplicate_validation_jobs() {
  local unique_datasets=()
  local unique_chunk_sizes=()
  local unique_file_suffixes=()
  local unique_specific_opts=()
  local seen=" "
  local dataset_name

  for i in "${!job_datasets[@]}"; do
    dataset_name="${job_datasets[$i]}"
    if [[ "${seen}" == *" ${dataset_name} "* ]]; then
      echo "[INFO] Validation deduplication: reusing dataset ${dataset_name}"
      continue
    fi
    seen+="${dataset_name} "
    unique_datasets+=("${dataset_name}")
    unique_chunk_sizes+=("${job_chunk_sizes[$i]}")
    # Validation is tied to physical files, not histogram suffixes/cuts.
    unique_file_suffixes+=("")
    unique_specific_opts+=("")
  done

  job_datasets=("${unique_datasets[@]}")
  job_chunk_sizes=("${unique_chunk_sizes[@]}")
  job_file_suffixes=("${unique_file_suffixes[@]}")
  job_specific_opts=("${unique_specific_opts[@]}")
}

deduplicate_output_jobs() {
  local unique_datasets=()
  local unique_chunk_sizes=()
  local unique_file_suffixes=()
  local unique_specific_opts=()
  local seen=$'\n'
  local key
  local skipped=0

  for i in "${!job_datasets[@]}"; do
    key="${job_datasets[$i]}"$'\t'"${job_file_suffixes[$i]}"$'\t'"${job_specific_opts[$i]}"
    if [[ "${seen}" == *$'\n'"${key}"$'\n'* ]]; then
      echo "[INFO] Job deduplication: skipping duplicate ${job_datasets[$i]}${job_file_suffixes[$i]}"
      skipped=$((skipped + 1))
      continue
    fi
    seen+="${key}"$'\n'
    unique_datasets+=("${job_datasets[$i]}")
    unique_chunk_sizes+=("${job_chunk_sizes[$i]}")
    unique_file_suffixes+=("${job_file_suffixes[$i]}")
    unique_specific_opts+=("${job_specific_opts[$i]}")
  done

  if [[ ${skipped} -gt 0 ]]; then
    job_datasets=("${unique_datasets[@]}")
    job_chunk_sizes=("${unique_chunk_sizes[@]}")
    job_file_suffixes=("${unique_file_suffixes[@]}")
    job_specific_opts=("${unique_specific_opts[@]}")
  fi
}

apply_configured_dataset_cuts() {
  local era="$1" cut dataset_name cut_rows
  local -A dataset_cuts=()
  [[ "${campaign_mode}" != "validation" ]] || return 0
  # Parse the era configuration once, rather than starting Python for every job.
  cut_rows="$(python3 - "config/${era}/samples.yaml" <<'PY_CUTS'
import sys
import yaml
with open(sys.argv[1]) as stream:
    samples = yaml.safe_load(stream) or {}
for dataset, entry in samples.items():
    cut = (entry or {}).get("additional_cuts")
    if cut:
        print(dataset + "\t" + str(cut).replace("\n", " "))
PY_CUTS
)" || die "Cannot read configured dataset cuts for ${era}"
  while IFS=$'\t' read -r dataset_name cut; do
    [[ -n "${dataset_name}" ]] && dataset_cuts["${dataset_name}"]="${cut}"
  done <<< "${cut_rows}"
  for i in "${!job_datasets[@]}"; do
    if [[ " ${job_specific_opts[$i]} " == *" --additional-cuts "* ]]; then
      continue
    fi
    cut="${dataset_cuts[${job_datasets[$i]}]:-}"
    if [[ -n "${cut}" ]]; then
      job_specific_opts[$i]="${job_specific_opts[$i]:+${job_specific_opts[$i]} }--additional-cuts ${cut}"
      echo "[INFO] ${job_datasets[$i]}: configured additional cut '${cut}'"
    fi
  done
}

add_data_jobs() {
  local era="$1"
  local datasets=()

  case "${era}" in
    Run3_2022)
      datasets=(Muon_Run2022C Muon_Run2022D SingleMuon_Run2022C)
      ;;
    Run3_2022EE)
      # datasets=(Muon_Run2022G)
      datasets=(Muon_Run2022E Muon_Run2022F Muon_Run2022G)
      ;;
    Run3_2023)
      datasets=(
        Muon0_Run2023C_v1 Muon0_Run2023C_v2 Muon0_Run2023C_v3 Muon0_Run2023C_v4
        Muon1_Run2023C_v1 Muon1_Run2023C_v2 Muon1_Run2023C_v3 Muon1_Run2023C_v4
      )
      ;;
    Run3_2023BPix)
      datasets=(Muon0_Run2023D_v1 Muon0_Run2023D_v2 Muon1_Run2023D_v1 Muon1_Run2023D_v2)
      ;;
    Run3_2024)
      datasets=(
        Muon0_Run2024C Muon0_Run2024D Muon0_Run2024E Muon0_Run2024F
        Muon0_Run2024G Muon0_Run2024H Muon0_Run2024I_v1 Muon0_Run2024I_v2
        Muon1_Run2024C Muon1_Run2024D Muon1_Run2024E Muon1_Run2024F
        Muon1_Run2024G Muon1_Run2024H Muon1_Run2024I_v1 Muon1_Run2024I_v2
      )
      ;;
    Run3_2025)
      datasets=(
        Muon0_Run2025C_v1 Muon0_Run2025C_v2 Muon0_Run2025D_v1 Muon0_Run2025E_v1
        Muon0_Run2025F_v1 Muon0_Run2025F_v2 Muon0_Run2025G_v1
        Muon1_Run2025C_v1 Muon1_Run2025C_v2 Muon1_Run2025D_v1 Muon1_Run2025E_v1
        Muon1_Run2025F_v1 Muon1_Run2025F_v2 Muon1_Run2025G_v1
      )
      ;;
    Run3_2026)
      local selected_data
      selected_data="$(python3 - "${era}" <<'PY_DATA'
import sys
from common.utilities import resolve_dataset_selection

selection = resolve_dataset_selection(".", sys.argv[1])
print("\n".join(selection["process_datasets"].get("Data_Muon", [])))
PY_DATA
)" || die "Could not resolve Data_Muon datasets from skim_cfg for ${era}"
      mapfile -t datasets <<< "${selected_data}"
      ;;
  esac

  [[ ${#datasets[@]} -gt 0 ]] || die "No data datasets configured for era ${era}"

  local dataset_name
  for dataset_name in "${datasets[@]}"; do
    add_job "${dataset_name}" 6 ""
  done
}

add_dy_amcatnlo_jobs() {
  local era="$1"
  local datasets=()

  case "${era}" in
    Run3_2024|Run3_2025|Run3_2026)
      datasets=(DYto2Mu_M_50_amcatnloFXFX DYto2Tau_M_50_amcatnloFXFX DYto2E_M_50_amcatnloFXFX)
      ;;
    Run3_2022|Run3_2022EE|Run3_2023|Run3_2023BPix)
      datasets=(DYto2L_M_50_amcatnloFXFX)
      ;;
  esac

  local dataset_name
  for dataset_name in "${datasets[@]}"; do
    add_job "${dataset_name}" 20
  done
}

add_dy_105_160_jobs() {
  local era="$1"

  case "${era}" in
    Run3_2024|Run3_2025|Run3_2026)
      # For 2024-2026 the nominal DY 105-160 selection is composed of the
      # inclusive sample outside the generator-level VBF phase space and the
      # dedicated VBF-filtered sample inside that phase space.
      add_job DYto2Mu_MLL_105to160_amcatnloFXFX 20
      add_job DYto2Mu_MLL_105to160_amcatnloFXFX_VBFFiltered 20
      ;;
    Run3_2022|Run3_2022EE|Run3_2023|Run3_2023BPix)
      # No VBF-filtered companion sample exists for these eras.
      add_job DYto2Mu_MLL_105to160_amcatnloFXFX 20
      ;;
  esac
}

add_dy_012j_jobs() {
  local era="$1"
  local prefix
  case "${era}" in
    Run3_2024|Run3_2025|Run3_2026) prefix="DYto2Mu" ;;
    Run3_2022|Run3_2022EE|Run3_2023|Run3_2023BPix) prefix="DYto2L" ;;
  esac
  add_job "${prefix}_M_50_0J_amcatnloFXFX" 20
  add_job "${prefix}_M_50_1J_amcatnloFXFX" 20
  add_job "${prefix}_M_50_2J_amcatnloFXFX" 20
}

add_ewk_105_160_jobs() {
  add_job EWK_2Mu2J_MLL_105to160_herwig 15
  add_job EWK_2Mu2J_MLL_105to160_pythia 15
}


add_static_group_jobs() {
  local era="$1"
  local group="$2"
  local datasets=()
  local chunk_size=15

  case "${group}" in
    DiTriBoson)
      chunk_size=30
      datasets=(
        WWW_4F WWZ_4F WWto2L2Nu_powheg WWto4Q_powheg WWtoLNu2Q_powheg
        WZZ WZto2L2Q_powheg  WZtoLNu2Q_powheg #WZto3LNu_powheg
        ZZZ ZZto2L2Nu_powheg ZZto2L2Q_powheg ZZto2Nu2Q_powheg ZZto4L_powheg
      )
      ;;
    DY_minnlo)
      chunk_size=30
      datasets=(  DYto2Mu_MLL_130to200_powheg_minnlo DYto2Mu_MLL_1000to1500_powheg_minnlo  DYto2Mu_MLL_1500to2000_powheg_minnlo DYto2Mu_MLL_2000to4000_powheg_minnlo DYto2Mu_MLL_200to400_powheg_minnlo DYto2Mu_MLL_4000to6000_powheg_minnlo DYto2Mu_MLL_400to600_powheg_minnlo DYto2Mu_MLL_50to130_powheg_minnlo DYto2Mu_MLL_6000to13600_powheg_minnlo DYto2Mu_MLL_600to800_powheg_minnlo )
      ;;
    EWK)
      datasets=(EWK_2L2J_madgraph_herwig)
      ;;
    other_signals)
      datasets=(
      TTH_Hto2Mu ZH_Hto2Mu ggZH_Hto2Mu ggZH_Hto2Mu_ZtoAll_M125 WminusH_Hto2Mu WplusH_Hto2Mu
      )
      ;;
    SingleH)
      datasets=(
        GluGluHto2B_M125 #GluGluHto2Wto2L2Nu_M125
        VBFHto2B_M125 #VBFHto2Wto2L2Nu_M125
        ggZH_Hto2B_Zto2L ggZH_Hto2B_Zto2Q
        ZH_Hto2B_Zto2L ZH_Hto2B_Zto2Q
        WminusH_Hto2B_WtoLNu #WminusHto2Tau_UncorrelatedDecay_UnFiltered GluGluHto2Tau_UncorrelatedDecay_UnFiltered
        WplusH_Hto2B_WtoLNu #WplusHto2Tau_UncorrelatedDecay_UnFiltered VBFHto2Tau_UncorrelatedDecay_UnFiltered
      )
      ;;
    SingleTop)
      datasets=(
        TWminusto2L2Nu TWminusto4Q TWminustoLNu2Q TbarWplusto2L2Nu TbarWplusto4Q TbarWplustoLNu2Q
        TBbarQto2Q_t_channel_4FS TBbarQtoLNu_t_channel_4FS TBbartoLplusNuBbar_s_channel_4FS
        TbarBQto2Q_t_channel_4FS TbarBQtoLNu_t_channel_4FS TbarBtoLminusNuB_s_channel_4FS
      )
      ;;
    TT)
      chunk_size=10
      datasets=(TTto2L2Nu TTto4Q TTtoLNu2Q)
      ;;
    TTX)
      chunk_size=10
      datasets=(TTHto2B_M125 TTHtoNon2B_M125 TTWH TTWW TTZH_ZHto4B TTZ_Zto2Q)
      ;;
    *)
      die "Internal error: unknown static group '${group}'"
      ;;
  esac

  local dataset_name
  for dataset_name in "${datasets[@]}"; do
    if [[ "${era}" == "Run3_2023BPix" ]]; then
      case "${dataset_name}" in
        ggZH_Hto2B_Zto2L|ggZH_Hto2B_Zto2Q|ZH_Hto2B_Zto2L|ZH_Hto2B_Zto2Q|\
        WminusH_Hto2B_WtoLNu|WplusH_Hto2B_WtoLNu|TTHto2B_M125|TTHtoNon2B_M125)
          continue
          ;;
      esac
    fi
    add_job "${dataset_name}" "${chunk_size}"
  done
}

add_w_jobs() {
  local era="$1"
  local datasets=()

  case "${era}" in
    Run3_2024|Run3_2025|Run3_2026)
      datasets=(WtoMuNu_amcatnloFXFX WtoTauNu_amcatnloFXFX) # WtoENu_amcatnloFXFX WtoLNu_1J_madgraphMLM WtoLNu_2J_madgraphMLM WtoLNu_3J_madgraphMLM WtoLNu_4J_madgraphMLM
      ;;
    Run3_2022|Run3_2022EE|Run3_2023|Run3_2023BPix)
      datasets=(WtoLNu_0J_amcatnloFXFX WtoLNu_1J_amcatnloFXFX WtoLNu_2J_amcatnloFXFX ) #WtoLNu_amcatnloFXFX)
      ;;
  esac

  local dataset_name
  for dataset_name in "${datasets[@]}"; do
    add_job "${dataset_name}" 15
  done
}

normalize_group() {
  case "$1" in
    skim_cfg|skim-config|configured) echo "skim_cfg" ;;
    data|Data) echo "data" ;;
    ditriboson|DiTriBoson) echo "DiTriBoson" ;;
    dy_amcatnlo|DY_amcatnlo) echo "DY_amcatnlo" ;;
    dy_amcatnlo_105_160|DY_amcatnlo_105_160) echo "DY_amcatnlo_105_160" ;;
    dy_012j|DY_012J) echo "DY_012J" ;;
    dy_minnlo|DY_minnlo) echo "DY_minnlo" ;;
    ewk|EWK) echo "EWK" ;;
    ewk_105_160|EWK_105_160) echo "EWK_105_160" ;;
    flashsim|FlashSim) echo "FlashSim" ;;
    region_higgs|region_inclusive|flash_backgrounds) echo "$1" ;;
    signals|Signals) echo "signals" ;;
    other_signals) echo "other_signals" ;;
    singleh|SingleH) echo "SingleH" ;;
    singletop|SingleTop) echo "SingleTop" ;;
    ttx|TTX) echo "TTX" ;;
    tt|TT) echo "TT" ;;
    w|W) echo "W" ;;
    mc|MC|all_mc|all-mc) echo "mc" ;;
    all|All) echo "all" ;;
    *) die "Unknown dataset group '$1'. Run with --help for the list." ;;
  esac
}

add_skim_cfg_jobs() {
  local era="$1"
  local default_chunk_size="${chunk_size_override:-20}"
  local dataset_name

  echo "[INFO] Resolving datasets from config/${era}/skim_cfg.yaml"
  while IFS= read -r dataset_name; do
    [[ -n "${dataset_name}" ]] || continue
    add_job "${dataset_name}" "${default_chunk_size}"
  done < <(
    python3 "${ANALYSIS_PATH}/tools/resolve_datasets.py" \
      --era "${era}" --format lines
  )
}

add_skim_cfg_mc_jobs() {
  local era="$1"
  local default_chunk_size="${chunk_size_override:-20}"
  local dataset_name

  echo "[INFO] Resolving all MC datasets from config/${era}/skim_cfg.yaml"
  while IFS= read -r dataset_name; do
    [[ -n "${dataset_name}" ]] || continue
    add_job "${dataset_name}" "${default_chunk_size}"
  done < <(
    python3 "${ANALYSIS_PATH}/tools/resolve_datasets.py" \
      --era "${era}" --format lines --exclude-data
  )
}

groups_for_era() {
  local era="$1"

  case "${era}" in
    Run3_2024|Run3_2025|Run3_2026)
      echo "data DiTriBoson DY_amcatnlo DY_amcatnlo_105_160 DY_012J DY_minnlo EWK EWK_105_160 FlashSim signals other_signals SingleH SingleTop TTX TT W"
      ;;
    Run3_2022|Run3_2022EE|Run3_2023|Run3_2023BPix)
      echo "data DiTriBoson DY_amcatnlo DY_amcatnlo_105_160 DY_012J EWK EWK_105_160 FlashSim signals other_signals SingleH SingleTop TTX TT W"
      ;;
    *)
      die "Unknown era '${era}'"
      ;;
  esac
}

dataset_groups=()
single_dataset_name=""
single_dataset_chunk_size=20
chunk_size_override=""
era=""
input_folder="skim_v3"
root_input_folder=""
json_input_folder=""
manifest_input_folder=""
additional_metadata_inputs=()
requested_systematics=()
file_open_retries=3
file_open_retry_delay=2
output_suffix=""
output_dir_override=""
campaign_mode="histograms"
extra_opts=()
dry_run=0
condor=0
condor_dir=""
condor_label=""
job_flavour="workday"
request_cpus=4
request_memory="8GB"
request_disk="4GB"
max_jobs=""
max_parallel_jobs=""
chunk_retries=1
summary_file=""
queued_registry_file=""
job_count_file=""
erase_existing=0
force_submit=0
missing_only=0
excluded_datasets=()
require_component_outputs=0
required_component_regions=""
print_existing=0
deep_output_check=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --campaign-mode)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      campaign_mode="$2"
      [[ "${campaign_mode}" == "histograms" || "${campaign_mode}" == "systematics" || "${campaign_mode}" == "validation" ]] || die "invalid campaign mode '${campaign_mode}'"
      shift 2
      ;;
    --datasets|--dataset-groups|--groups)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      split_csv "$2" dataset_groups
      shift 2
      ;;
    --dataset-name|--dataset)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      single_dataset_name="$2"
      shift 2
      ;;
    --chunk-size)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      single_dataset_chunk_size="$2"
      [[ "${single_dataset_chunk_size}" =~ ^[0-9]+$ ]] || die "$1 must be a positive integer"
      [[ "${single_dataset_chunk_size}" -ge 1 ]] || die "$1 must be >= 1"
      chunk_size_override="${single_dataset_chunk_size}"
      shift 2
      ;;
    --retries|--retry-delay|--progress-every)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      extra_opts+=("$1" "$2")
      shift 2
      ;;
    --era)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      era="$2"
      shift 2
      ;;
    --input-folder)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      input_folder="$2"
      shift 2
      ;;
    --root-input-folder|--root-input)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      root_input_folder="$2"
      shift 2
      ;;
    --json-input-folder|--json-input)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      json_input_folder="$2"
      shift 2
      ;;
    --manifest-input-folder|--manifest-input)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      manifest_input_folder="$2"
      shift 2
      ;;
    --additional-metadata-input|--extra-metadata-input)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      additional_metadata_inputs+=("$2")
      shift 2
      ;;
    --systematics)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      IFS=',' read -r -a _systematics_part <<< "$2"
      requested_systematics+=("${_systematics_part[@]}")
      shift 2
      ;;
    --file-open-retries|--validation-retries)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      file_open_retries="$2"
      [[ "${file_open_retries}" =~ ^[0-9]+$ && "${file_open_retries}" -ge 1 ]] || die "$1 must be >= 1"
      shift 2
      ;;
    --file-open-retry-delay)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      file_open_retry_delay="$2"
      [[ "${file_open_retry_delay}" =~ ^[0-9]+([.][0-9]+)?$ ]] || die "$1 must be a non-negative number"
      shift 2
      ;;
    --output-suffix)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      output_suffix="$2"
      shift 2
      ;;
    --output-dir)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      [[ -n "$2" ]] || die "$1 requires a non-empty value"
      output_dir_override="$2"
      shift 2
      ;;
    --extra-opts|--extra-options)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      append_extra_opts_string "$2"
      shift 2
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    --deep-output-check)
      deep_output_check=1
      shift
      ;;
    --condor)
      condor=1
      shift
      ;;
    --condor-dir)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      condor_dir="$2"
      shift 2
      ;;
    --condor-label)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      [[ -n "$2" ]] || die "$1 requires a non-empty value"
      condor_label="$2"
      shift 2
      ;;
    --job-flavour)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      job_flavour="$2"
      shift 2
      ;;
    --request-cpus)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      request_cpus="$2"
      shift 2
      ;;
    --request-memory)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      request_memory="$2"
      shift 2
      ;;
    --request-disk)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      request_disk="$2"
      shift 2
      ;;
    --max-jobs|--max-submit-jobs)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      max_jobs="$2"
      [[ "${max_jobs}" =~ ^[0-9]+$ ]] || die "$1 must be a non-negative integer"
      shift 2
      ;;
    --max-parallel-jobs)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      max_parallel_jobs="$2"
      [[ "${max_parallel_jobs}" =~ ^[0-9]+$ ]] || die "$1 must be a non-negative integer"
      [[ "${max_parallel_jobs}" -ge 1 ]] || die "$1 must be >= 1"
      shift 2
      ;;
    --chunk-retries)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      chunk_retries="$2"
      [[ "${chunk_retries}" =~ ^[0-9]+$ ]] || die "$1 must be a non-negative integer"
      shift 2
      ;;
    --summary-file)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      summary_file="$2"
      shift 2
      ;;
    --queued-registry-file)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      queued_registry_file="$2"
      shift 2
      ;;
    --missing-only|--run-missing-only)
      missing_only=1
      shift
      ;;
    --exclude-dataset)
      IFS=',' read -r -a excluded_values <<< "$2"
      excluded_datasets+=("${excluded_values[@]}")
      shift 2
      ;;
    --require-component-outputs)
      require_component_outputs=1
      shift
      ;;
    --require-component-regions)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      required_component_regions="$2"
      shift 2
      ;;
    --print-existing)
      print_existing=1
      shift
      ;;
    --job-count-file)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      job_count_file="$2"
      shift 2
      ;;
    --erase-existing|--erase-already-present|--overwrite)
      erase_existing=1
      shift
      ;;
    --force|--submit-existing)
      force_submit=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      append_words extra_opts "$@"
      break
      ;;
    *)
      die "Unknown option '$1'. Run with --help for usage."
      ;;
  esac
done

if [[ -z "${condor_dir}" ]]; then
  case "${campaign_mode}" in
    validation) condor_dir="htcondor/validation" ;;
    histograms) condor_dir="htcondor/hists" ;;
    systematics) condor_dir="htcondor/systematics" ;;
  esac
fi

if [[ "${campaign_mode}" == "validation" ]]; then
  [[ -n "${output_dir_override}" ]] || die "${campaign_mode} stage requires --output-dir DIR"
fi

[[ ${#dataset_groups[@]} -gt 0 || -n "${single_dataset_name}" ]] || die "Missing --datasets or --dataset-name"
[[ -n "${era}" ]] || die "Missing --era"
require_known_era "${era}"

normalized_groups=()
if [[ -n "${single_dataset_name}" ]]; then
  normalized_groups=("dataset_${single_dataset_name}")
else
  for group in "${dataset_groups[@]}"; do
    group="$(normalize_group "${group}")"
    if [[ "${group}" == "all" ]]; then
      read -r -a normalized_groups <<< "$(groups_for_era "${era}")"
      break
    fi
    normalized_groups+=("${group}")
  done
fi

job_datasets=()
job_chunk_sizes=()
job_file_suffixes=()
job_specific_opts=()
expanded_single_dataset=0

if [[ -n "${single_dataset_name}" ]]; then
  if [[ "${single_dataset_name}" == "DYto2Mu_MLL_105to160_amcatnloFXFX" ]]; then
    expanded_single_dataset=1
    add_dy_105_160_jobs "${era}"
    if [[ -n "${chunk_size_override}" ]]; then
      for i in "${!job_chunk_sizes[@]}"; do
        job_chunk_sizes[$i]="${single_dataset_chunk_size}"
      done
    fi
  else
    add_job "${single_dataset_name}" "${single_dataset_chunk_size}"
  fi
else
  for group in "${normalized_groups[@]}"; do
    case "${group}" in
      skim_cfg) add_skim_cfg_jobs "${era}" ;;
      data) add_data_jobs "${era}" ;;
      DY_amcatnlo) add_dy_amcatnlo_jobs "${era}" ;;
      DY_amcatnlo_105_160) add_dy_105_160_jobs "${era}" ;;
      DY_012J) add_dy_012j_jobs "${era}" ;;
      EWK_105_160) add_ewk_105_160_jobs ;;
      signals|region_higgs|region_inclusive|flash_backgrounds|FlashSim)
        resolved_samples="$(python3 tools/resolve_region_sample_routing.py --era "${era}" --selection "${group}")" || exit 1
        while IFS= read -r dataset_name; do
          [[ -n "${dataset_name}" ]] && add_job "${dataset_name}" "${chunk_size_override:-15}"
        done <<< "${resolved_samples}"
        ;;
      W) add_w_jobs "${era}" ;;
      mc) add_skim_cfg_mc_jobs "${era}" ;;
      DiTriBoson|DY_minnlo|EWK|SingleH|SingleTop|TTX|other_signals|TT) add_static_group_jobs "${era}" "${group}" ;;
      *) die "Internal error: unhandled group '${group}'" ;;
    esac
  done
fi

if [[ -z "${single_dataset_name}" || ${expanded_single_dataset} -eq 1 ]]; then
  drop_unconfigured_jobs "${era}"
fi
if [[ ${#excluded_datasets[@]} -gt 0 ]]; then
  for excluded_dataset in "${excluded_datasets[@]}"; do
    filter_out_dataset "${excluded_dataset}"
  done
fi
apply_configured_dataset_cuts "${era}"
if [[ "${campaign_mode}" == "validation" ]]; then
  deduplicate_validation_jobs
else
  deduplicate_output_jobs
fi

[[ ${#job_datasets[@]} -gt 0 ]] || die "No jobs selected"

dataset_input_path() {
  local folder="$1"
  local dataset="$2"
  if [[ "${folder}" = /* ]]; then
    printf '%s/%s/%s/' "${folder}" "${era}" "${dataset}"
  else
    printf '/eos/cms/store/group/phys_higgs/cmshmm/vdamante/%s/%s/%s/' "${folder}" "${era}" "${dataset}"
  fi
}

if [[ -z "${manifest_input_folder}" ]]; then
  manifest_input_folder="${input_folder}"
fi
if [[ -z "${root_input_folder}" && -n "${json_input_folder}" ]]; then
  root_input_folder="${json_input_folder}"
fi
if [[ -z "${root_input_folder}" ]]; then
  root_input_folder="${input_folder}"
fi
if [[ -z "${json_input_folder}" ]]; then
  json_input_folder="${input_folder}"
fi
if [[ ${#requested_systematics[@]} -eq 0 ]]; then
  if [[ "${campaign_mode}" == "systematics" ]]; then
    requested_systematics=(all)
  else
    requested_systematics=(Central)
  fi
fi

if [[ -n "${chunk_size_override}" ]]; then
  for i in "${!job_chunk_sizes[@]}"; do
    job_chunk_sizes[$i]="${chunk_size_override}"
  done
fi
if [[ "${campaign_mode}" != "validation" && -z "${chunk_size_override}" ]]; then
  for i in "${!job_chunk_sizes[@]}"; do
    job_chunk_sizes[$i]=1
  done
fi
if [[ "${campaign_mode}" == "validation" && -z "${chunk_size_override}" ]]; then
  for i in "${!job_chunk_sizes[@]}"; do
    job_chunk_sizes[$i]="${request_cpus}"
  done
fi

output_dir="${output_dir_override:-/eos/user/v/vdamante/H_mumu/newHists_${era}${output_suffix}}"
if [[ ${dry_run} -eq 0 ]]; then
  mkdir -p "${output_dir}"
fi

if [[ ${condor} -eq 1 ]]; then
  analysis_path="${ANALYSIS_PATH:-$(pwd)}"
  timestamp="$(date +%Y%m%d_%H%M%S)"
  full_group_label="$(IFS=_; echo "${normalized_groups[*]}")"
  if [[ -n "${condor_label}" ]]; then
    group_label="$(short_label "${condor_label}" 48)"
    # Keep the user-facing Condor batch name readable. Campaign submitters use
    # labels such as CAMPAIGN/WEIGHTS/Hists_SYSTEMATIC_ERA: the systematic and
    # era are added separately below, so retain only CAMPAIGN/WEIGHTS here.
    batch_campaign_label="${condor_label%/Hists_*}"
    if [[ "${batch_campaign_label}" == "${condor_label}" ]]; then
      batch_campaign_label="${condor_label%_${era#Run3_}}"
    fi
    batch_campaign_label="$(short_label "${batch_campaign_label}" 64)"
  else
    group_label="$(condor_group_label)"
    batch_campaign_label="${group_label}"
  fi
  submit_dir="${condor_dir}/${era}${output_suffix}_${group_label}_${timestamp}"
  condor_output_dir="${submit_dir}/output"
  condor_error_dir="${submit_dir}/error"
  condor_log_dir="${submit_dir}/log"
  jobs_file="${submit_dir}/jobs.tsv"
  extra_opts_file="${submit_dir}/extra_opts.txt"
  monitoring_file="${submit_dir}/monitoring.txt"
  submit_file="${submit_dir}/submit.sub"
  batch_names_file="${submit_dir}/batch_names.txt"
  wrapper="${analysis_path}/htcondor/run_stage_condor.sh"

  if [[ "${jobs_file}" = /* ]]; then
    jobs_file_arg="${jobs_file}"
  else
    jobs_file_arg="${analysis_path}/${jobs_file}"
  fi
  if [[ "${batch_names_file}" = /* ]]; then
    batch_names_file_arg="${batch_names_file}"
  else
    batch_names_file_arg="${analysis_path}/${batch_names_file}"
  fi
  if [[ "${extra_opts_file}" = /* ]]; then
    extra_opts_file_arg="${extra_opts_file}"
  else
    extra_opts_file_arg="${analysis_path}/${extra_opts_file}"
  fi
  if [[ "${condor_output_dir}" = /* ]]; then
    condor_output_dir_arg="${condor_output_dir}"
    condor_error_dir_arg="${condor_error_dir}"
    condor_log_dir_arg="${condor_log_dir}"
  else
    condor_output_dir_arg="${analysis_path}/${condor_output_dir}"
    condor_error_dir_arg="${analysis_path}/${condor_error_dir}"
    condor_log_dir_arg="${analysis_path}/${condor_log_dir}"
  fi

  mkdir -p "${condor_output_dir}" "${condor_error_dir}" "${condor_log_dir}"

  : > "${jobs_file}"
  : > "${batch_names_file}"
  : > "${monitoring_file}"

  total_selected=0
  completed_existing=0
  queued_existing=0
  erased_existing=0
  missing_outputs=0
  missing_output_files=()
  jobs_to_submit=0
  hit_max_jobs=0

  for i in "${!job_datasets[@]}"; do
    dataset_name="${job_datasets[$i]}"
    file_suffix="${job_file_suffixes[$i]}"
    case "${campaign_mode}" in
      validation) output_file="${output_dir}/${era}/${dataset_name}.json" ;;
      histograms|systematics) output_file="$(histogram_output_path "${output_dir}" "${era}" "${dataset_name}" "${file_suffix}")" ;;
    esac
    total_selected=$((total_selected + 1))

    if stage_output_exists "${campaign_mode}" "${output_file}"; then
      if [[ ${erase_existing} -eq 1 ]]; then
        echo "[ERASE] ${output_file}" | tee -a "${monitoring_file}"
        if [[ ${dry_run} -eq 0 ]]; then
          rm -f "${output_file}"
        fi
        erased_existing=$((erased_existing + 1))
      elif [[ ${force_submit} -eq 0 ]]; then
        echo "[DONE]  ${output_file}" >> "${monitoring_file}"
        completed_existing=$((completed_existing + 1))
        continue
      fi
    else
      echo "[MISS]  ${output_file}" >> "${monitoring_file}"
      missing_outputs=$((missing_outputs + 1))
      missing_output_files+=("${output_file}")
    fi

    if [[ ${condor} -eq 1 && ${erase_existing} -eq 0 ]]; then
      if is_output_in_registry "${output_file}" || is_output_already_queued "${output_file}"; then
        echo "[QUEUE] ${output_file}" >> "${monitoring_file}"
        queued_existing=$((queued_existing + 1))
        continue
      fi
    fi

    if [[ -n "${max_jobs}" && ${jobs_to_submit} -ge ${max_jobs} ]]; then
      hit_max_jobs=1
      continue
    fi

    # Keep every TSV field non-empty. Bash `read` treats tabs as whitespace
    # and collapses adjacent delimiters; an empty suffix would otherwise shift
    # job-specific options (for example --additional-cuts) into the filename.
    serialized_file_suffix="${file_suffix:--}"
    serialized_specific_opts="${job_specific_opts[$i]:--}"
    printf '%s\t%s\t%s\t%s\n' \
      "${dataset_name}" \
      "${job_chunk_sizes[$i]}" \
      "${serialized_file_suffix}" \
      "${serialized_specific_opts}" \
      >> "${jobs_file}"
    if [[ "${campaign_mode}" == "validation" ]]; then
      printf 'validation/%s_%s\n' \
        "${era}" \
        "$(short_label "${dataset_name}" 72)" \
        >> "${batch_names_file}"
    else
      systematic_label="$(IFS=_; echo "${requested_systematics[*]}")"
      printf 'hists/%s_%s_%s_%s\n' \
        "${batch_campaign_label}" \
        "$(short_label "${systematic_label}" 32)" \
        "${era}" \
        "$(short_label "${dataset_name}${file_suffix}" 72)" \
        >> "${batch_names_file}"
    fi
    jobs_to_submit=$((jobs_to_submit + 1))
  done

  {
    printf '%s' "${extra_opts[*]}"
    if [[ "${campaign_mode}" != "validation" ]]; then
      printf ' --systematics'
      printf ' %q' "${requested_systematics[@]}"
    fi
    printf '\n'
  } > "${extra_opts_file}"
  if [[ -n "${job_count_file}" ]]; then
    printf '%s\n' "${jobs_to_submit}" > "${job_count_file}"
  fi
  if [[ -n "${summary_file}" ]]; then
    if [[ ! -s "${summary_file}" ]]; then
      printf 'era\tgroup\tselected\tcompleted_existing\tqueued_existing\tmissing_outputs\terased_existing\tjobs_to_submit\toutput_dir\tmonitoring_file\tsubmit_file\n' > "${summary_file}"
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "${era}" \
      "${group_label}" \
      "${total_selected}" \
      "${completed_existing}" \
      "${queued_existing}" \
      "${missing_outputs}" \
      "${erased_existing}" \
      "${jobs_to_submit}" \
      "${output_dir}" \
      "${monitoring_file}" \
      "${submit_file}" \
      >> "${summary_file}"
  fi

  {
    echo
    echo "========== HISTOGRAM CONDOR MONITORING =========="
    echo "era                : ${era}"
    echo "group              : ${group_label}"
    echo "group full         : ${full_group_label}"
    echo "selected datasets  : ${total_selected}"
    echo "completed existing : ${completed_existing}"
    echo "already queued     : ${queued_existing}"
    echo "missing outputs    : ${missing_outputs}"
    echo "erased existing    : ${erased_existing}"
    echo "jobs to submit     : ${jobs_to_submit}"
    if [[ ${#missing_output_files[@]} -gt 0 ]]; then
      echo "missing files      :"
      for missing_file in "${missing_output_files[@]}"; do
        echo "  - ${missing_file}"
      done
    fi
    if [[ -n "${max_jobs}" ]]; then
      echo "max jobs           : ${max_jobs}"
      echo "hit max jobs       : ${hit_max_jobs}"
    fi
    if [[ -n "${max_parallel_jobs}" ]]; then
      echo "max parallel jobs  : ${max_parallel_jobs}"
    fi
    echo "output dir         : ${output_dir}"
    echo "==============================================="
  } | tee -a "${monitoring_file}"

  if [[ ${jobs_to_submit} -eq 0 ]]; then
    echo "[INFO] All selected histogram outputs are already present. No jobs to submit."
    echo "[INFO] Monitoring report: ${monitoring_file}"
    exit 0
  fi

  additional_metadata_bases_csv="$(IFS=,; echo "${additional_metadata_inputs[*]}")"

  cat > "${submit_file}" <<EOF
universe = vanilla
executable = ${wrapper}
# run_stage_condor.sh positional interface:
# analysis jobs.tsv ProcId mode era manifest_base root_base json_base output_dir
# extra_opts_file open_retries retry_delay additional_metadata_bases_csv
arguments = ${analysis_path} ${jobs_file_arg} \$(ProcId) ${campaign_mode} ${era} ${manifest_input_folder} ${root_input_folder} ${json_input_folder} ${output_dir} ${extra_opts_file_arg} ${file_open_retries} ${file_open_retry_delay} ${additional_metadata_bases_csv}

output = ${condor_output_dir_arg}/\$(ProcId).out
error  = ${condor_error_dir_arg}/\$(ProcId).err
log    = ${condor_log_dir_arg}/condor.log

request_cpus = ${request_cpus}
request_memory = ${request_memory}
request_disk = ${request_disk}
+JobFlavour = "${job_flavour}"
+Era = "${era}"
+HistGroup = "${group_label}"
batch_name = \$(hist_batch_name)

max_retries = ${chunk_retries}
getenv = True
EOF

  if [[ -n "${max_parallel_jobs}" ]]; then
    {
      echo "max_materialize = ${max_parallel_jobs}"
      echo
    } >> "${submit_file}"
  fi

  echo "queue hist_batch_name from ${batch_names_file_arg}" >> "${submit_file}"

  echo
  echo "============================================================"
  echo "[INFO] Condor histogram submission prepared"
  echo "[INFO] Era        : ${era}"
  echo "[INFO] Jobs       : ${jobs_to_submit}"
  echo "[INFO] Completed  : ${completed_existing}"
  echo "[INFO] Queued     : ${queued_existing}"
  echo "[INFO] Missing    : ${missing_outputs}"
  if [[ -n "${max_parallel_jobs}" ]]; then
    echo "[INFO] Max parall.: ${max_parallel_jobs}"
  fi
  echo "[INFO] Output dir : ${output_dir}"
  echo "[INFO] Submit file: ${submit_file}"
  echo "[INFO] Jobs table : ${jobs_file}"
  echo "[INFO] Monitoring : ${monitoring_file}"
  echo "[INFO] Stdout     : ${condor_output_dir}"
  echo "[INFO] Stderr     : ${condor_error_dir}"
  echo "[INFO] Event log  : ${condor_log_dir}"
  echo "============================================================"

  if [[ ${dry_run} -eq 1 ]]; then
    echo "[DRY RUN] Not submitting. To submit manually:"
    echo "condor_submit ${submit_file}"
    exit 0
  fi

  condor_submit "${submit_file}"
  if [[ -n "${queued_registry_file}" ]]; then
    mkdir -p "$(dirname "${queued_registry_file}")"
    while IFS=$'\t' read -r submitted_dataset _submitted_chunk submitted_suffix _submitted_opts; do
      [[ -n "${submitted_dataset}" ]] || continue
      [[ "${submitted_suffix}" == "-" ]] && submitted_suffix=""
      printf '%s\n' "$(histogram_output_path "${output_dir}" "${era}" "${submitted_dataset}" "${submitted_suffix}")" >> "${queued_registry_file}"
    done < "${jobs_file}"
    sort -u -o "${queued_registry_file}" "${queued_registry_file}"
  fi
  exit 0
fi

for i in "${!job_datasets[@]}"; do
  dataset_name="${job_datasets[$i]}"
  chunk_size="${job_chunk_sizes[$i]}"
  file_suffix="${job_file_suffixes[$i]}"
  metadata_input_path="$(dataset_input_path "${json_input_folder}" "${dataset_name}")"
  input_path="$(dataset_input_path "${root_input_folder}" "${dataset_name}")"
  additional_metadata_args=()
  for metadata_base in "${additional_metadata_inputs[@]}"; do
    additional_metadata_args+=(
      --additional-metadata-input
      "$(dataset_input_path "${metadata_base}" "${dataset_name}")"
    )
  done
  output_file="$(histogram_output_path "${output_dir}" "${era}" "${dataset_name}" "${file_suffix}")"

  case "${campaign_mode}" in
    validation) expected_output="${output_dir}/${era}/${dataset_name}.json" ;;
    histograms|systematics) expected_output="${output_file}" ;;
  esac

  if [[ ${missing_only} -eq 1 && ${force_submit} -eq 0 && ${erase_existing} -eq 0 ]]; then
    if stage_output_exists "${campaign_mode}" "${expected_output}" \
      && { [[ ${require_component_outputs} -eq 0 ]] \
        || component_outputs_exist "${expected_output}"; }; then
      if [[ ${print_existing} -eq 1 ]]; then
        echo "[DONE]  ${expected_output}"
        echo "[INFO] --missing-only: output already exists, skipping ${dataset_name}."
      fi
      continue
    fi
  fi

  specific_opts=()
  if [[ -n "${job_specific_opts[$i]}" ]]; then
    # shellcheck disable=SC2206
    specific_opts=(${job_specific_opts[$i]})
  fi

  if [[ "${campaign_mode}" == "validation" ]]; then
    output_file="${output_dir}/${era}/${dataset_name}.json"
    command=(
      python3 analysis/validate_dataset.py
      --era "${era}"
      --dataset-name "${dataset_name}"
      --root-input "${input_path}"
      --json-input "${metadata_input_path}"
      --output-manifest "${output_file}"
      --workers "${chunk_size}"
      --retries "${file_open_retries}"
      --retry-delay "${file_open_retry_delay}"
    )
  else
    validation_manifest="$(manifest_path "${manifest_input_folder}" "${era}" "${dataset_name}")"
    command=(
      python3 histograms/hist_maker.py
      --era "${era}"
      --root-input "${input_path}"
      --json-input "${metadata_input_path}"
      "${additional_metadata_args[@]}"
      --dataset-name "${dataset_name}"
      --input-manifest "${validation_manifest}"
      --output-file "${output_file}"
      --systematics "${requested_systematics[@]}"
    )
  fi
  command+=("${specific_opts[@]}")
  command+=("${extra_opts[@]}")

  echo
  echo "============================================================"
  echo "[INFO] Era     : ${era}"
  echo "[INFO] Dataset : ${dataset_name}"
  echo "[INFO] Input   : ${input_path}"
  echo "[INFO] JSON    : ${metadata_input_path}"
  echo "[INFO] Manifest: ${manifest_input_folder}"
  if [[ "${campaign_mode}" != "validation" ]]; then
    echo "[INFO] Systs   : ${requested_systematics[*]}"
  fi
  echo "[INFO] Output  : ${output_file}"
  echo "[INFO] Command : ${command[*]}"
  echo "============================================================"

  if [[ ! -d "${input_path}" ]]; then
    echo "[WARNING] Input directory does not exist:"
    echo "          ${input_path}"
    echo "[WARNING] hist_maker.py will create an empty histogram file."
  fi

  if [[ ${dry_run} -eq 1 ]]; then
    continue
  fi

  "${command[@]}"
done

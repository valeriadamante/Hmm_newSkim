#!/usr/bin/env bash
#
# Signal Extended (Signal_Fit_VBF + H_sideband_VBF) fits on the DNN output,
# in the three DY jet-component models:
#
#   lnn             Hard/PU1/PU2 constrained by the DYVBFZ_fit_* log-normals
#   rateparam-pu    one free rateParam shared by PU1+PU2, Hard keeps its lnN
#   rateparam-both  one rateParam for PU1+PU2 and a second one for Hard
#
# For each model it produces: expected significance, asymptotic limits,
# FitDiagnostics (Asimov), impacts, and the 1D likelihood scan of r with the
# stat-only breakdown.
#
#   bash combine/run_signal_extended_fits.sh                  # all three
#   bash combine/run_signal_extended_fits.sh lnn              # one of them
#   SE_ERAS=2024,2025 bash combine/run_signal_extended_fits.sh
#
# Everything is Asimov (-t -1 --expectSignal 1).  Drop SE_ASIMOV to fit data.

set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
# env.sh legge "$@" come opzioni proprie: i modelli vanno messi da parte prima.
models=("$@")
set --
# shellcheck disable=SC1091
source env.sh >/dev/null

SE_INPUT="${SE_INPUT:-/eos/user/v/vdamante/H_mumu/skim_v4/post_dy/dnn_vbf_weighted/Hists_systMerged}"
# Default: le ere il cui merge-syst ha lasciato la ricevuta. Una directory
# Hists_systMerged esiste anche quando il merge e' morto a meta', e in quel caso
# la card perderebbe in silenzio ggH, VBFH e i fondi piccoli di quell'era.
if [ -z "${SE_ERAS:-}" ]; then
    SE_ERAS=""
    for era in 2022 2022EE 2023 2023BPix 2024 2025; do
        [ -f "$(dirname "$SE_INPUT")/.workflow_syst_Run3_${era}.json" ] || continue
        SE_ERAS="${SE_ERAS:+$SE_ERAS,}$era"
    done
    [ -n "$SE_ERAS" ] || { echo "Nessuna era con merge-syst completo in $SE_INPUT" >&2; exit 1; }
    echo "[INFO] ere con merge-syst completo: $SE_ERAS"
fi
SE_OUTPUT="${SE_OUTPUT:-${repo}/combine/results_signal_extended}"
SE_ASIMOV="${SE_ASIMOV:--t -1 --expectSignal 1}"
SE_RANGE="${SE_RANGE:---rMin -5 --rMax 10}"
SE_PARALLEL="${SE_PARALLEL:-8}"
SE_POINTS="${SE_POINTS:-60}"
# Sottoinsieme dei passi, separati da virgola:
# build,significance,limits,fitdiagnostics,impacts,scan (default: tutti).
# Senza "build" usa card e workspace gia' presenti in SE_OUTPUT/<model>.
SE_STEPS=",${SE_STEPS:-build,significance,limits,fitdiagnostics,impacts,scan},"
step() { [[ "$SE_STEPS" == *",$1,"* ]]; }

if [ "${#models[@]}" -eq 0 ]; then
    models=(lnn rateparam-pu rateparam-both)
fi

for model in "${models[@]}"; do
    out="${SE_OUTPUT}/${model}"
    card="${out}/datacard_signal_extended_${model}.txt"
    workspace="${out}/datacard_signal_extended_${model}.root"
    mkdir -p "$out"

    echo "=============================================================="
    if step build; then
    echo "[$model] building the card"
    python3 combine/build_signal_extended_datacards.py \
        --input "$SE_INPUT" --eras "$SE_ERAS" \
        --dy-model "$model" --output "$card" \
        2>&1 | tee "${out}/build.log"

    echo "[$model] text2workspace"
    run_combine_tool text2workspace.py "$card" -m 125 -o "$workspace"
    fi

    # ---- expected significance ------------------------------------------
    if step significance; then
    mkdir -p "${out}/significance"
    ( cd "${out}/significance"
      run_combine_tool combine -M Significance "$workspace" -m 125 \
          $SE_ASIMOV --toysFreq $SE_RANGE -n ".SigExt_${model}" ) \
        2>&1 | tee "${out}/significance/significance.log"
    fi

    # ---- asymptotic limits on r -----------------------------------------
    if step limits; then
    mkdir -p "${out}/limits"
    ( cd "${out}/limits"
      run_combine_tool combine -M AsymptoticLimits "$workspace" -m 125 \
          -t -1 $SE_RANGE -n ".SigExt_${model}" ) \
        2>&1 | tee "${out}/limits/limits.log"
    fi

    # ---- fit diagnostics -------------------------------------------------
    if step fitdiagnostics; then
    mkdir -p "${out}/fitdiagnostics"
    ( cd "${out}/fitdiagnostics"
      run_combine_tool combine -M FitDiagnostics "$workspace" -m 125 \
          $SE_ASIMOV --robustFit 1 $SE_RANGE \
          --saveShapes --saveWithUncertainties --saveNormalizations \
          -n ".SigExt_${model}" ) \
        2>&1 | tee "${out}/fitdiagnostics/fitdiagnostics.log"
    fi

    # ---- pulls and impacts ----------------------------------------------
    # combineTool writes one file per nuisance in the working directory.
    if step impacts; then
    mkdir -p "${out}/impacts"
    ( cd "${out}/impacts"
      run_combine_tool combineTool.py -M Impacts -d "$workspace" -m 125 \
          --doInitialFit --robustFit 1 $SE_ASIMOV $SE_RANGE
      run_combine_tool combineTool.py -M Impacts -d "$workspace" -m 125 \
          --robustFit 1 --doFits --parallel "$SE_PARALLEL" $SE_ASIMOV $SE_RANGE
      run_combine_tool combineTool.py -M Impacts -d "$workspace" -m 125 \
          -o "impacts_${model}.json" $SE_ASIMOV $SE_RANGE
      run_combine_tool plotImpacts.py -i "impacts_${model}.json" -o "impacts_${model}" ) \
        2>&1 | tee "${out}/impacts/impacts.log"
    fi

    # ---- likelihood scan, with the stat-only breakdown -------------------
    if step scan; then
    mkdir -p "${out}/scan"
    ( cd "${out}/scan"
      run_combine_tool combine -M MultiDimFit "$workspace" -m 125 \
          --algo grid --points "$SE_POINTS" $SE_ASIMOV $SE_RANGE \
          --saveWorkspace -n ".SigExt_${model}.total"
      run_combine_tool combine -M MultiDimFit \
          "higgsCombine.SigExt_${model}.total.MultiDimFit.mH125.root" -m 125 \
          --algo grid --points "$SE_POINTS" $SE_ASIMOV $SE_RANGE \
          --snapshotName MultiDimFit --freezeParameters allConstrainedNuisances \
          -n ".SigExt_${model}.statonly"
      run_combine_tool plot1DScan.py \
          "higgsCombine.SigExt_${model}.total.MultiDimFit.mH125.root" \
          --others "higgsCombine.SigExt_${model}.statonly.MultiDimFit.mH125.root:Stat only:2" \
          --main-label "Total" --output "scan_r_${model}" ) \
        2>&1 | tee "${out}/scan/scan.log"
    fi

    echo "[$model] done -> $out"
done

echo "=============================================================="
echo "Summary"
for model in "${models[@]}"; do
    sig="${SE_OUTPUT}/${model}/significance/significance.log"
    lim="${SE_OUTPUT}/${model}/limits/limits.log"
    printf '%-16s %s | %s\n' "$model" \
        "$(grep -h 'Significance:' "$sig" 2>/dev/null | tail -1)" \
        "$(grep -h 'Expected 50.0%' "$lim" 2>/dev/null | tail -1)"
done

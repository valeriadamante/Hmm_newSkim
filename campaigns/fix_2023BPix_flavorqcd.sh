#!/usr/bin/env bash
#
# Ripara JESRegrouped_FlavorQCD_hadded/Run3_2023BPix/VVV.root e rifa' il
# merge-syst del 2023BPix.
#
# Quel file ha il buffer compresso rotto (`R__unzip_header: error in header`):
# ROOT non lo apre e `hadd` muore, ma il check della campagna lo promuove,
# perche' `workflow.py` valida con uproot leggendo solo un campione limitato di
# istogrammi. E' lo stesso caso di dnn_vbf_dy_unweighted/.../VVV.root: l'unico
# modo di rifarlo e' un hadd **senza** --missing-only, che riscrive con hadd -f.
#
#     nohup bash campaigns/fix_2023BPix_flavorqcd.sh > fix_2023BPix.log 2>&1 &

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# shellcheck disable=SC1091
source env.sh >/dev/null 2>&1

V4_IN=/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4
V4_MAN=/eos/user/v/vdamante/H_mumu/manifests_skim_v4
OUT=/eos/user/v/vdamante/H_mumu/skim_v4/post_dy/all_variables
POLL="${V4_POLL:-300}"

log() { echo "[$(date '+%F %T')] $*"; }

log "=== rifaccio l'hadd di JESRegrouped_FlavorQCD per il 2023BPix"
bash campaigns/all_variables.sh hadd --mode syst --families JESRegrouped_FlavorQCD \
    --eras 2023BPix --check-level files \
    --input-dir "$V4_IN" --manifest-root "$V4_MAN" --output-dir "$OUT" \
    || { log "hadd fallito"; exit 1; }

log "=== verifico che ROOT apra il file"
python3 - <<'PY' || exit 1
import sys
import ROOT
path = ('/eos/user/v/vdamante/H_mumu/skim_v4/post_dy/all_variables/'
        'JESRegrouped_FlavorQCD_hadded/Run3_2023BPix/VVV.root')
try:
    handle = ROOT.TFile.Open(path)
except Exception as exc:
    sys.exit(f'ancora rotto: {exc}')
if not handle or handle.IsZombie():
    sys.exit('ancora rotto: zombie')
print(f'ok, {len(handle.GetListOfKeys())} chiavi')
PY

# Il merge-syst delle altre ere sta girando: due merge insieme si pestano i
# piedi sulla stessa Hists_systMerged, quindi si aspetta.
log "attendo che finisca il merge-syst in corso"
while pgrep -u "$USER" -f "hmumu.py merge-systematics" >/dev/null; do sleep "$POLL"; done

log "=== merge-syst 2023BPix"
bash campaigns/all_variables.sh merge-syst --mode both --eras 2023BPix --check-level files \
    --input-dir "$V4_IN" --manifest-root "$V4_MAN" --output-dir "$OUT" \
    || { log "merge-syst 2023BPix fallito di nuovo"; exit 1; }

log "fatto"

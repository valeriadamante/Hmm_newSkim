#!/usr/bin/env bash
# Un'era dello studio sulla coppia VBF: troppo pesante (~25 GB) per lxplus.
cd /afs/cern.ch/work/v/vdamante/Hmm_newSkim
source env.sh >/dev/null 2>&1 || true
exec python3 studies/vbf_pair_definition/compare_vbf_pair_definitions.py \
  --era "$1" --regions Signal_Fit --max-files-background 60 --threads 4

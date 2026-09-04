#!/bin/bash

# Activate the LCG environment
#source /cvmfs/sft.cern.ch/lcg/views/LCG_109_cuda/x86_64-el9-gcc13-opt/setup.sh
source /eos/user/a/ayeagle/H_mumu/venv/MLENV2/bin/activate

# Run your training script
python3 main_condor.py -r "$1" -f "$2" -d "$3" -c "$4"
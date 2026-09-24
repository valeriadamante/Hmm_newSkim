#!/bin/sh
set -eu
exec bash "$(dirname "$0")/lib/runner.sh" generic --config config/campaigns/dnn_vbf_eta_regions.sh "$@"

#!/bin/sh
set -eu
exec bash "$(dirname "$0")/lib/runner.sh" generic --config config/campaigns/vbf_eta_regions.sh "$@"

#!/bin/sh
set -eu
exec sh "$(dirname "$0")/submit_campaign.sh" config/campaigns/dnn_vbf_z_sep03.sh "$@"

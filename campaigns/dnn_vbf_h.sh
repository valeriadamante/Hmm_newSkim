#!/bin/sh
set -eu
exec sh "$(dirname "$0")/submit_campaign.sh" config/campaigns/dnn_vbf_h_sep03.sh "$@"

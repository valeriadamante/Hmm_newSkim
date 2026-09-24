#!/bin/sh
set -eu
exec sh "$(dirname "$0")/submit_campaign.sh" config/campaigns/all_variables.sh "$@"

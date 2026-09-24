#!/bin/sh
set -eu
exec bash "$(dirname "$0")/lib/runner.sh" jet_horn_veto "$@"


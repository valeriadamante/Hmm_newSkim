#!/bin/sh
set -eu
exec bash "$(dirname "$0")/lib/runner.sh" dy_weights "$@"

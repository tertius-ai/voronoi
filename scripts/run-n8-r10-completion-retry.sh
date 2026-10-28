#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

repository_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

export VORONOI_COMPLETION_MAX_ITERATIONS=${VORONOI_COMPLETION_MAX_ITERATIONS:-1000}
export VORONOI_CANDIDATE_TIMEOUT_SECONDS=${VORONOI_CANDIDATE_TIMEOUT_SECONDS:-600}
export VORONOI_RETRY_TIMEOUTS=1
export VORONOI_RETRY_UNRESOLVED_ONLY=1

exec "$repository_root/scripts/run-n8-r10-completion.sh" "${1:-4}"

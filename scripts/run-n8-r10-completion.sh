#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

repository_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd -- "$repository_root"

concurrency=${1:-4}
case "$concurrency" in
    ''|*[!0-9]*)
        echo "concurrency must be an integer in 1..64" >&2
        exit 2
        ;;
esac
if ((concurrency < 1 || concurrency > 64)); then
    echo "concurrency must be an integer in 1..64" >&2
    exit 2
fi

shard_timeout_seconds=${VORONOI_SHARD_TIMEOUT_SECONDS:-21600}
case "$shard_timeout_seconds" in
    ''|*[!0-9]*)
        echo "VORONOI_SHARD_TIMEOUT_SECONDS must be an integer of at least 600" >&2
        exit 2
        ;;
esac
if ((shard_timeout_seconds < 600)); then
    echo "VORONOI_SHARD_TIMEOUT_SECONDS must be an integer of at least 600" >&2
    exit 2
fi

max_iterations=${VORONOI_COMPLETION_MAX_ITERATIONS:-200}
candidate_timeout_seconds=${VORONOI_CANDIDATE_TIMEOUT_SECONDS:-120}
for setting_name in max_iterations candidate_timeout_seconds; do
    setting_value=${!setting_name}
    case "$setting_value" in
        ''|*[!0-9]*)
            echo "$setting_name must be a positive integer" >&2
            exit 2
            ;;
    esac
    if ((setting_value < 1)); then
        echo "$setting_name must be a positive integer" >&2
        exit 2
    fi
done

retry_timeouts=${VORONOI_RETRY_TIMEOUTS:-0}
retry_unresolved_only=${VORONOI_RETRY_UNRESOLVED_ONLY:-0}
for setting_name in retry_timeouts retry_unresolved_only; do
    setting_value=${!setting_name}
    if [[ $setting_value != 0 && $setting_value != 1 ]]; then
        echo "$setting_name must be 0 or 1" >&2
        exit 2
    fi
done

retry_arguments=()
if ((retry_timeouts)); then
    retry_arguments+=(--retry-timeouts)
fi
if ((retry_unresolved_only)); then
    retry_arguments+=(--retry-unresolved-only)
fi

source_noether_python=${VORONOI_NOETHER_PYTHON:-$repository_root/../noether/python}
if [[ ! -f $source_noether_python/noether/__init__.py ]]; then
    echo "VORONOI_NOETHER_PYTHON is not a Noether package tree: $source_noether_python" >&2
    exit 1
fi

shopt -s nullglob
source_noether_engines=("$source_noether_python"/noether/_engine*.so)
shopt -u nullglob
if ((${#source_noether_engines[@]} != 1)); then
    echo "expected one built Noether extension, found ${#source_noether_engines[@]}" >&2
    exit 1
fi
source_noether_engine=${source_noether_engines[0]}

source_flint_preload=${VORONOI_FLINT_PRELOAD:-}
if [[ -z $source_flint_preload ]]; then
    shopt -s nullglob
    flint_candidates=("$source_noether_python"/tertius_noether.libs/libflint.so.*)
    shopt -u nullglob
    if ((${#flint_candidates[@]} != 1)); then
        echo "expected one bundled Noether libflint, found ${#flint_candidates[@]}" >&2
        exit 1
    fi
    source_flint_preload=${flint_candidates[0]}
fi
if [[ ! -f $source_flint_preload ]]; then
    echo "VORONOI_FLINT_PRELOAD is not a file: $source_flint_preload" >&2
    exit 1
fi

source_census_engine=${VORONOI_CENSUS_ENGINE:-$repository_root/target/release/voronoi-census-engine}
if [[ ! -x $source_census_engine ]]; then
    echo "VORONOI_CENSUS_ENGINE is not an executable file: $source_census_engine" >&2
    exit 1
fi

# Fail before creating a workspace if either selected component is stale.
PYTHONPATH="$source_noether_python:$repository_root/src" \
    LD_PRELOAD="$source_flint_preload${LD_PRELOAD:+:$LD_PRELOAD}" \
    "$repository_root/.venv/bin/python" -m voronoi.cli doctor --engine "$source_census_engine"

artifact_root=${VORONOI_ARTIFACT_ROOT:-$repository_root/artifacts/n8-r10}
artifact_root=$(realpath -- "$artifact_root")
for artifact_name in lower-000-orbits.jsonl lower-000-keyed.jsonl \
    lower-000-report.json lower-000-orbit-key-report.json lower-000-orbit-report.json; do
    if [[ ! -r $artifact_root/$artifact_name ]]; then
        echo "missing census input: $artifact_root/$artifact_name" >&2
        exit 1
    fi
done
# Keep the pre-0.3.2 production ledgers immutable. Reusing their mathematical
# evidence is a separate, explicit verification step, not a side effect of launch.
workspace=${VORONOI_COMPLETION_WORKSPACE:-$artifact_root/orbit-production-64-noether-0.3.2}
workspace=$(realpath -m -- "$workspace")
run_id=${VORONOI_COMPLETION_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}
log_directory=${VORONOI_COMPLETION_LOG_DIRECTORY:-$workspace/logs/$run_id}
log_directory=$(realpath -m -- "$log_directory")
mkdir -p -- "$log_directory"

exec 9>"$workspace/.full-completion.lock"
if ! flock -n 9; then
    echo "another full completion controller holds $workspace/.full-completion.lock" >&2
    exit 1
fi

# A production controller must not import or execute mutable development
# artifacts after launch.  Snapshot the complete Python projection, its native
# libraries, and the Rust worker into this run's artifact directory.  A later
# `make engine` or `cargo build` can then replace the development copies without
# disrupting queued shards.
runtime_root="$log_directory/runtime"
if [[ -e $runtime_root ]]; then
    echo "run runtime already exists and will not be overwritten: $runtime_root" >&2
    exit 1
fi
runtime_python="$runtime_root/python"
runtime_census_engine="$runtime_root/bin/voronoi-census-engine"
mkdir -p -- "$runtime_python" "$runtime_root/bin"
cp -a -- "$source_noether_python/noether" "$runtime_python/noether"
cp -a -- "$repository_root/src/voronoi" "$runtime_python/voronoi"
mkdir -p -- "$runtime_python/tertius_noether.libs"
# Freeze FLINT's transitive numerical dependencies too: current source builds
# can resolve GMP/MPFR from the mutable Noether .deps tree.
mapfile -t native_libraries < <(
    LD_PRELOAD="$source_flint_preload" ldd "$source_noether_engine" "$source_census_engine" \
        | awk '$1 ~ /^lib(flint|gmp|mpfr).*\.so/ && $2 == "=>" {print $3}' \
        | sort -u
)
for native_library in "${native_libraries[@]}" "$source_flint_preload"; do
    cp -Lp -- "$native_library" \
        "$runtime_python/tertius_noether.libs/$(basename -- "$native_library")"
done
cp -p -- "$source_census_engine" "$runtime_census_engine"

noether_python="$runtime_python"
flint_preload="$runtime_python/tertius_noether.libs/$(basename -- "$source_flint_preload")"
census_engine="$runtime_census_engine"
source_noether_engine_sha256=$(sha256sum -- "$source_noether_engine" | cut -d' ' -f1)
source_flint_sha256=$(sha256sum -- "$source_flint_preload" | cut -d' ' -f1)
source_census_engine_sha256=$(sha256sum -- "$source_census_engine" | cut -d' ' -f1)
noether_engine_sha256=$(sha256sum -- "$noether_python/noether/$(basename -- "$source_noether_engine")" | cut -d' ' -f1)
flint_sha256=$(sha256sum -- "$flint_preload" | cut -d' ' -f1)
census_engine_sha256=$(sha256sum -- "$census_engine" | cut -d' ' -f1)
if [[ $noether_engine_sha256 != "$source_noether_engine_sha256" \
    || $flint_sha256 != "$source_flint_sha256" \
    || $census_engine_sha256 != "$source_census_engine_sha256" ]]; then
    echo "production runtime snapshot failed its digest check" >&2
    exit 1
fi
chmod -R a-w -- "$runtime_root"

(
    cd -- "$runtime_root"
    find . -type f -print0 | sort -z | xargs -0 sha256sum
) >"$log_directory/runtime.sha256"

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$noether_python${PYTHONPATH:+:$PYTHONPATH}"
export LD_PRELOAD="$flint_preload${LD_PRELOAD:+:$LD_PRELOAD}"
export LD_LIBRARY_PATH="$runtime_python/tertius_noether.libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export VORONOI_CENSUS_ENGINE="$census_engine"

verify_runtime() {
    local resolved_noether
    local expected_noether
    if ! (cd -- "$runtime_root" && sha256sum --check --quiet "$log_directory/runtime.sha256"); then
        echo "production runtime changed after its snapshot" >&2
        return 1
    fi
    resolved_noether=$(
        "$repository_root/.venv/bin/python" -c \
            'import noether; print(noether.__file__)'
    )
    expected_noether=$(readlink -f -- "$noether_python/noether/__init__.py")
    if [[ $(readlink -f -- "$resolved_noether") != "$expected_noether" ]]; then
        echo "Noether resolved outside the production runtime: $resolved_noether" >&2
        return 1
    fi
    "$repository_root/.venv/bin/python" -m voronoi.cli doctor --engine "$census_engine"
}

verify_runtime

state=running
failures=0
write_status() {
    printf 'state=%s\nrun_id=%s\nconcurrency=%s\nfailures=%s\nmax_iterations=%s\ncandidate_timeout_seconds=%s\nretry_timeouts=%s\nretry_unresolved_only=%s\nnoether_source_python=%s\nnoether_python=%s\nnoether_engine_sha256=%s\nflint_preload=%s\nflint_sha256=%s\ncensus_engine=%s\ncensus_engine_sha256=%s\nnoether_version=0.3.2\nworkspace=%s\nupdated_utc=%s\n' \
        "$state" "$run_id" "$concurrency" "$failures" "$max_iterations" \
        "$candidate_timeout_seconds" "$retry_timeouts" \
        "$retry_unresolved_only" "$source_noether_python" "$noether_python" \
        "$noether_engine_sha256" "$flint_preload" "$flint_sha256" \
        "$census_engine" "$census_engine_sha256" "$workspace" \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        >"$log_directory/status"
}
finish() {
    exit_status=$?
    if ((exit_status != 0)) && [[ $state == running ]]; then
        state=interrupted
    fi
    write_status
}
trap finish EXIT
write_status

run_shard() {
    local shard=$1
    local rendered_shard
    local log_path
    printf -v rendered_shard '%05d' "$shard"
    log_path="$log_directory/shard-$rendered_shard.log"
    printf 'starting shard %s/64 at %s\n' "$shard" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if ! verify_runtime >"$log_path" 2>&1; then
        printf 'shard %s/64 failed its isolated-runtime preflight at %s\n' \
            "$shard" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
        return 1
    fi
    if /usr/bin/time -v timeout "${shard_timeout_seconds}s" \
        "$repository_root/.venv/bin/voronoi" census-complete-orbits \
        --orbit-artifact "$artifact_root/lower-000-orbits.jsonl" \
        --keyed-artifact "$artifact_root/lower-000-keyed.jsonl" \
        --pair-report "$artifact_root/lower-000-report.json" \
        --key-report "$artifact_root/lower-000-orbit-key-report.json" \
        --orbit-report "$artifact_root/lower-000-orbit-report.json" \
        --output-dir "$workspace" \
        --shard-index "$shard" \
        --shard-count 64 \
        --max-iterations "$max_iterations" \
        --strategy exact_shell \
        --memory-gib 4 \
        --timeout-seconds "$candidate_timeout_seconds" \
        "${retry_arguments[@]}" \
        >>"$log_path" 2>&1
    then
        printf 'finished shard %s/64 at %s\n' "$shard" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        return 0
    else
        status=$?
    fi
    printf 'shard %s/64 exited %s at %s; see %s\n' \
        "$shard" "$status" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$log_path" >&2
    return "$status"
}

active=0
for ((shard = 0; shard < 64; shard++)); do
    run_shard "$shard" &
    active=$((active + 1))
    if ((active >= concurrency)); then
        if ! wait -n; then
            failures=$((failures + 1))
            write_status
        fi
        active=$((active - 1))
    fi
done

while ((active > 0)); do
    if ! wait -n; then
        failures=$((failures + 1))
        write_status
    fi
    active=$((active - 1))
done

if ((failures == 0)); then
    state=complete
    exit 0
fi
state=failed
exit 1

#!/usr/bin/env bash
# Fetch or verify the locked public reference database. Never pull a moving head.

set -euo pipefail

check_only=0
case "${1:-}" in
  '') ;;
  --check) check_only=1 ;;
  *) echo "usage: $0 [--check]" >&2; exit 2 ;;
esac
if (($# > 1)); then
  echo "usage: $0 [--check]" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
lock="$repo_root/validation/reference-database.json"
data_dir="$repo_root/data/elbazvip-Voronoi-complexes-database"
python=${PYTHON:-python3}
read -r database_url database_revision < <(
  "$python" - "$lock" <<'LOCK'
import json, sys
with open(sys.argv[1]) as source:
    lock = json.load(source)
print(lock['repository'], lock['revision'])
LOCK
)

if [[ ! -e $data_dir/.git ]]; then
  if ((check_only)); then
    echo "reference database is absent; run scripts/fetch_database.sh" >&2
    exit 1
  fi
  if [[ -e $data_dir ]]; then
    echo "refusing to replace an existing non-Git data directory: $data_dir" >&2
    exit 1
  fi
  mkdir -p "$(dirname "$data_dir")"
  git init --quiet "$data_dir"
  git -C "$data_dir" remote add origin "$database_url"
fi

if [[ -n $(git -C "$data_dir" status --porcelain) ]]; then
  echo "reference database has local changes; preserving them without checkout" >&2
  exit 1
fi

if ((check_only)); then
  if [[ $(git -C "$data_dir" rev-parse HEAD) != "$database_revision" ]]; then
    echo "reference revision does not match the lock; run scripts/fetch_database.sh" >&2
    exit 1
  fi
else
  if ! git -C "$data_dir" cat-file -e "${database_revision}^{commit}" 2>/dev/null; then
    git -C "$data_dir" fetch --depth 1 -- "$database_url" "$database_revision"
  fi
  git -C "$data_dir" checkout --detach "$database_revision"
fi

"$python" - "$lock" "$data_dir" <<'VERIFY'
import hashlib, json, pathlib, sys
lock = json.loads(pathlib.Path(sys.argv[1]).read_text())
root = pathlib.Path(sys.argv[2])
for name, expected in lock['files'].items():
    path = root / 'DATA_pari' / name
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit(f'reference file does not match the lock: {name}')
if not (root / lock['license_file']).is_file():
    raise SystemExit('reference database omitted its upstream license')
print(f"Verified {len(lock['files'])} reference files at {lock['revision']}")
VERIFY

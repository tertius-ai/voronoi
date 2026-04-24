#!/usr/bin/env bash
# Fetch the public Voronoi cell database into data/.
# Safe to rerun: uses git clone or pull depending on existing state.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
data_dir="$repo_root/data/elbazvip-Voronoi-complexes-database"

if [ -d "$data_dir/.git" ]; then
  echo "==> updating $data_dir"
  git -C "$data_dir" pull --ff-only
else
  echo "==> cloning elbazvip/Voronoi-complexes-database into $data_dir"
  mkdir -p "$(dirname "$data_dir")"
  git clone --depth 1 https://github.com/elbazvip/Voronoi-complexes-database.git "$data_dir"
fi

echo
echo "==> contents:"
ls "$data_dir/DATA_pari/"

#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  printf 'Usage: %s /absolute/path/to/catalog.sqlite3\n' "$0" >&2
  exit 64
fi

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
database_path="$1"
if [[ "$database_path" != /* ]]; then
  database_path="$repo_root/$database_path"
fi

if [[ -e "$database_path" || -L "$database_path" ]]; then
  printf 'Refusing to overwrite existing database: %s\n' "$database_path" >&2
  exit 1
fi

cd "$repo_root"
mkdir -p -- "$(dirname -- "$database_path")"
run_id="catalog-bootstrap-$(date -u +%Y%m%dT%H%M%SZ)"

if command -v padel-availability >/dev/null 2>&1; then
  cli=(padel-availability)
  cli_database="$database_path"
else
  image="${PADEL_AVAILABILITY_IMAGE:-padel-availability:local}"
  cli=(
    docker run --rm
    --mount "type=bind,source=$(dirname -- "$database_path"),target=/data"
    --entrypoint padel-availability
    "$image"
  )
  cli_database="/data/$(basename -- "$database_path")"
fi

"${cli[@]}" init-db --database "$cli_database"
"${cli[@]}" import-candidates \
  --database "$cli_database" \
  --input data/candidates.json
"${cli[@]}" build-catalog \
  --database "$cli_database" \
  --candidates data/candidates.json \
  --verified data/verified_locations.json \
  --run-id "$run_id"

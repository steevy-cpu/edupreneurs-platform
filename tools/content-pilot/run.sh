#!/usr/bin/env bash
# Run the content-pilot tool or its tests without installing anything into the repository environment.
#   tools/content-pilot/run.sh validate
#   tools/content-pilot/run.sh sizes | manifest --check | verify-manifest | review-pack --check
#   tools/content-pilot/run.sh --test            (pytest)
#   tools/content-pilot/run.sh --build           (regenerate the pilot JSON from authoring/)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"
export PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}"
py=(uv run --no-project --python 3.12 --with jsonschema)
case "${1:-}" in
  --test)  shift; exec "${py[@]}" --with pytest python -m pytest -q -p no:cacheprovider tests "$@" ;;
  --build) exec "${py[@]}" python -m authoring.build ;;
  *)       exec "${py[@]}" python -m content_pilot "$@" ;;
esac

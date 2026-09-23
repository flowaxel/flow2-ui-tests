#!/bin/bash
# Fail fast and clearly if the two required env vars weren't passed -
# a pytest collection error burying "FLOW2_URL is required" three
# levels of traceback down is not a good first experience.
set -euo pipefail

# --webui (or FLOW2_WEBUI=1) starts the small web GUI (webui.py)
# instead of running pytest directly - it collects the URL/credentials
# itself via a form, so none of the env vars below are required for
# this path. See README.md's "Web GUI" section.
if [ "${1:-}" = "--webui" ] || [ "${FLOW2_WEBUI:-0}" = "1" ]; then
    exec python webui.py
fi

missing=()
[ -z "${FLOW2_URL:-}" ] && missing+=("FLOW2_URL")
[ -z "${FLOW2_USER:-}" ] && missing+=("FLOW2_USER")
[ -z "${FLOW2_PASSWORD:-}" ] && missing+=("FLOW2_PASSWORD")
if [ "${#missing[@]}" -gt 0 ]; then
    echo "Missing required environment variable(s): ${missing[*]}" >&2
    echo "See README.md for usage (docker run -e FLOW2_URL=... -e FLOW2_USER=... -e FLOW2_PASSWORD=... flow2-ui-tests)." >&2
    exit 2
fi

exec python -m pytest -v "$@"

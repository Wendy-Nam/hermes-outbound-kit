#!/bin/sh
set -eu
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    exec python3 outbound.py start
else
    exec bash scripts/bootstrap.command
fi

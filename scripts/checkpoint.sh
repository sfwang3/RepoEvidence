#!/usr/bin/env bash
set -e

# Usage: ./scripts/checkpoint.sh ["optional custom message"]

MSG="${1:-wip: local checkpoint $(date '+%Y-%m-%d %H:%M:%S')}"

if [ -z "$(git status --porcelain)" ]; then
    echo "ℹ️  No changes detected in working tree. Nothing to commit."
    exit 0
fi

git add -A
git commit -m "$MSG"
echo "✅ Local checkpoint saved: $MSG"

#!/usr/bin/env bash
set -e

# Usage: ./scripts/push_clean.sh ["commit message for remote push"]

DEFAULT_MSG="update: sync latest code changes"
PUSH_MSG="${1:-$DEFAULT_MSG}"

echo "🔍 Fetching remote status from GitHub..."
git fetch origin main >/dev/null 2>&1 || true

# Check if there are code changes compared to origin/main excluding docs/superpowers/
NON_AI_DIFF=$(git diff origin/main..HEAD -- . ':!docs/superpowers')

if [ -z "$NON_AI_DIFF" ]; then
    echo "ℹ️  GitHub origin/main is already up to date with all non-AI code changes."
    exit 0
fi

# Create a temporary index to create a clean commit for remote push
TMP_INDEX=$(mktemp)
export GIT_INDEX_FILE="$TMP_INDEX"

# Read origin/main into temporary index
git read-tree origin/main

# Stage all files from HEAD except docs/superpowers/
git checkout HEAD -- . ':!docs/superpowers'
git add -A . ':!docs/superpowers'

TREE_ID=$(git write-tree)
PARENT_ID=$(git rev-parse origin/main)

# Create a clean commit object without altering local branch history
CLEAN_COMMIT=$(git commit-tree "$TREE_ID" -p "$PARENT_ID" -m "$PUSH_MSG")

# Push the clean commit to origin/main using --no-verify to bypass pre-push guard
git push --no-verify origin "$CLEAN_COMMIT:refs/heads/main"

# Fetch updated origin/main tracking ref
git fetch origin main >/dev/null 2>&1 || true

# Clean up temp index
rm -f "$TMP_INDEX"
unset GIT_INDEX_FILE

echo "========================================================================="
echo "🚀 Clean code successfully pushed to GitHub origin/main!"
echo "   Remote Commit: $CLEAN_COMMIT"
echo "   Message:       $PUSH_MSG"
echo "   Note:          docs/superpowers/ was excluded from GitHub."
echo "========================================================================="


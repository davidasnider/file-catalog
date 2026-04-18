---
name: cleanup
description: Safely cleans up the local repository after a PR is merged. Switches to main, pulls latest, prunes remotes, deletes the merged branch, and syncs dependencies.
---

1. Ensures a clean git state and a merged PR before cleaning up the local feature branch and syncing `main`.

// turbo
```bash
CURRENT_BRANCH=$(git branch --show-current)

# 1. Safety Check: Don't run on main
if [ "$CURRENT_BRANCH" = "main" ]; then
    echo "ℹ️ Already on main branch. Nothing to clean up."
    exit 0
fi

# 2. Safety Check: Ensure git tree is clean
if [ -n "$(git status --porcelain)" ]; then
    echo "❌ Error: Git tree is not clean. Please commit or stash your changes before cleaning up."
    exit 1
fi

# 3. Verify PR Status via GitHub CLI
echo "🔍 Checking PR status for branch: $CURRENT_BRANCH..."
PR_STATE=$(gh pr view --json state --jq .state 2>/dev/null)

if [ "$PR_STATE" != "MERGED" ]; then
    echo "⚠️ Warning: PR for '$CURRENT_BRANCH' is not merged yet (State: ${PR_STATE:-UNKNOWN})."
    echo "Aborting cleanup to prevent data loss."
    exit 1
fi

# 4. Perform Cleanup
echo "🚀 PR is merged. Starting cleanup..."

echo "➡️ Switching to main..."
git checkout main

echo "📥 Pulling latest changes and pruning remotes..."
git pull origin main --prune

echo "🗑 Deleting local branch: $CURRENT_BRANCH..."
git branch -D -- "$CURRENT_BRANCH"

echo "🔄 Syncing dependencies..."
if command -v uv >/dev/null 2>&1; then
    uv sync
else
    echo "⚠️ 'uv' not found, skipping sync."
fi

echo "✅ Successfully cleaned up repository and synced main."
```

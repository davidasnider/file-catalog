---
name: sync-main
description: Ensures the git tree is on the main branch, clean, and runs uv sync to update dependencies. Use this workflow when asked to update, sync, or clean up the repository state and dependencies on the main branch.
---

1. Check if the git tree is clean. If not, abort.
2. Check out the `main` branch.
3. Pull the latest changes.
4. Run `uv sync`.

// turbo
```bash
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Error: Git tree is not clean. Please commit or stash your changes before syncing."
    exit 1
fi

git checkout main
git pull origin main
uv sync

echo "✅ Successfully synced main branch and updated dependencies."
```

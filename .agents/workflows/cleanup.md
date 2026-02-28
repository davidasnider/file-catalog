---
description: Clean up the local repository after a PR is merged by switching to main, pulling the latest code, and deleting the old branch.
---

1. Check to ensure the current branch's PR is merged, then check out `main`, pull the latest changes, and delete the local feature branch.
// turbo
```bash
CURRENT_BRANCH=$(git branch --show-current)

if [ "$CURRENT_BRANCH" == "main" ]; then
    echo "Already on main branch. Nothing to clean up."
    exit 0
fi

# Ensure PR is merged before proceeding
PR_STATE=$(gh pr view --json state --jq .state 2>/dev/null)

if [ "$PR_STATE" != "MERGED" ]; then
    echo "Error: PR is not merged yet (State: ${PR_STATE:-UNKNOWN})."
    echo "Aborting cleanup."
    exit 1
fi

git checkout main
git pull origin main
git branch -D $CURRENT_BRANCH
```

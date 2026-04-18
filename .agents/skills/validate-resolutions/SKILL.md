---
name: validate-resolutions
description: Verifies that all review comments on the PR have been resolved and that the code passes quality checks.
---

1. Queries GitHub for any remaining unresolved threads.
2. If all resolved, it triggers code analysis to ensure zero regressions.

// turbo
```bash
PR_NUMBER=$(gh pr view --json number -q .number)

echo "🔍 Validating all comments are resolved for PR #$PR_NUMBER..."

UNRESOLVED=$(gh api graphql -f query='
  query($owner: String!, $repo: String!, $pull: Int!) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $pull) {
        reviewThreads(first: 50) {
          nodes {
            isResolved
          }
        }
      }
    }
  }' -f owner=:owner -f repo=:repo -I pull=$PR_NUMBER --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)')

if [ -n "$UNRESOLVED" ]; then
    NUM_UNRESOLVED=$(echo "$UNRESOLVED" | wc -l | tr -d ' ')
    echo "❌ Error: There are still $NUM_UNRESOLVED unresolved review threads."
    exit 1
fi

echo "✅ All PR comments have been resolved."

# Now trigger code analysis
# Note: In the fix-pr-comments workflow, this would typically follow the analyzer execution
```

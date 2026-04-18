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

OWNER=$(gh repo view --json owner -q .owner.login)
REPO=$(gh repo view --json name -q .name)

UNRESOLVED=$(gh api graphql -F owner="$OWNER" -F repo="$REPO" -F pull="$PR_NUMBER" -f query='
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
  }' --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)')

if [ -n "$UNRESOLVED" ]; then
    NUM_UNRESOLVED=$(echo "$UNRESOLVED" | wc -l | tr -d ' ')
    echo "❌ Error: There are still $NUM_UNRESOLVED unresolved review threads."
    exit 1
fi

echo "✅ All PR comments have been resolved."

# Now trigger code analysis
echo "🧪 Running final code analysis..."
if command -v uv >/dev/null 2>&1; then
    uv run pre-commit run --all-files && uv run pytest
else
    pre-commit run --all-files && pytest
fi

echo "✅ Code verified. Ready for approval!"
```

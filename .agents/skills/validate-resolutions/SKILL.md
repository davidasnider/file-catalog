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

# 1. Check for Unresolved Threads (with pagination)
HAS_NEXT_PAGE=true
CURSOR="null"
UNRESOLVED_COUNT=0

while [ "$HAS_NEXT_PAGE" = "true" ]; do
  [ "$CURSOR" = "null" ] && RE_CURSOR="" || RE_CURSOR="$CURSOR"

  RESPONSE=$(gh api graphql -F owner="$OWNER" -F repo="$REPO" -F pull="$PR_NUMBER" -F cursor="$RE_CURSOR" -f query='
    query($owner: String!, $repo: String!, $pull: Int!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pull) {
          reviewThreads(first: 100, after: $cursor) {
            pageInfo { hasNextPage, endCursor }
            nodes { isResolved }
          }
        }
      }
    }')

  PAGE_UNRESOLVED=$(echo "$RESPONSE" | jq -r '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false) | .isResolved' | wc -l | tr -d ' ')
  UNRESOLVED_COUNT=$((UNRESOLVED_COUNT + PAGE_UNRESOLVED))
  HAS_NEXT_PAGE=$(echo "$RESPONSE" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.hasNextPage')
  CURSOR=$(echo "$RESPONSE" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.endCursor')
done

if [ "$UNRESOLVED_COUNT" -gt 0 ]; then
    echo "❌ Error: There are still $UNRESOLVED_COUNT unresolved review threads."
    exit 1
fi

echo "✅ All PR threads are marked as resolved."

# 2. Verify Agent Responses (with pagination)
echo "🔍 Verifying agent responses for all threads..."
SELF=$(gh api user --jq .login)
HAS_NEXT_PAGE=true
CURSOR="null"
THREADS_WITHOUT_REPLIES=0

while [ "$HAS_NEXT_PAGE" = "true" ]; do
  [ "$CURSOR" = "null" ] && RE_CURSOR="" || RE_CURSOR="$CURSOR"

  RESPONSE=$(gh api graphql -F owner="$OWNER" -F repo="$REPO" -F pull="$PR_NUMBER" -F cursor="$RE_CURSOR" -f query='
    query($owner: String!, $repo: String!, $pull: Int!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pull) {
          reviewThreads(first: 100, after: $cursor) {
            pageInfo { hasNextPage, endCursor }
            nodes {
              comments(first: 100) {
                nodes { author { login } }
              }
            }
          }
        }
      }
    }')

  PAGE_WITHOUT_REPLIES=$(echo "$RESPONSE" | jq -r --arg self "$SELF" '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.comments.nodes | map(.author.login) | contains([$self]) | not)] | length')
  THREADS_WITHOUT_REPLIES=$((THREADS_WITHOUT_REPLIES + PAGE_WITHOUT_REPLIES))
  HAS_NEXT_PAGE=$(echo "$RESPONSE" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.hasNextPage')
  CURSOR=$(echo "$RESPONSE" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.endCursor')
done

if [ "$THREADS_WITHOUT_REPLIES" -gt 0 ]; then
    echo "❌ Error: $THREADS_WITHOUT_REPLIES review threads have zero replies. You MUST reply to every thread."
    exit 1
fi

echo "✅ All review threads have received a response."

# Now trigger code analysis
echo "🧪 Running final code analysis..."
if command -v uv >/dev/null 2>&1; then
    uv run pre-commit run --all-files && uv run pytest
else
    pre-commit run --all-files && pytest
fi

echo "✅ Code verified. Ready for approval!"
```

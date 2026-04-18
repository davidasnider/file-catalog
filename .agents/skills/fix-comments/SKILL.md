---
name: fix-comments
description: Polls for unresolved PR comments and facilitates fixing them by fetching the thread context.
---

1. Polls for unresolved threads. If threads are found, the agent will systematically process each one.

// turbo
```bash
PR_NUMBER=$(gh pr view --json number -q .number)
MAX_ATTEMPTS=5
SLEEP_SECONDS=60

ATTEMPT=1
while [ $ATTEMPT -le $MAX_ATTEMPTS ]; do
  echo "🔍 Checking for unresolved comments on PR #$PR_NUMBER (Attempt $ATTEMPT/$MAX_ATTEMPTS)..."

  # Fetch unresolved review threads
  THREADS=$(gh api graphql -f query='
    query($owner: String!, $repo: String!, $pull: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pull) {
          reviewThreads(first: 50) {
            nodes {
              isResolved
              id
              comments(last: 1) {
                nodes {
                  body
                  path
                  line
                  author { login }
                }
              }
            }
          }
        }
      }
    }' -f owner=:owner -f repo=:repo -I pull=$PR_NUMBER --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)')

  if [ -n "$THREADS" ]; then
    echo "📣 Found unresolved comments:"
    echo "$THREADS" | jq -r '.comments.nodes[0] | "• \(.author.login) asks on \(.path):\(.line): \(.body)"'
    echo "💡 Proceeding to fix these issues one by one."
    exit 0
  fi

  if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
    echo "ℹ️ No unresolved comments found after $MAX_ATTEMPTS attempts."
    exit 0
  fi

  echo "⏳ No new comments yet. Waiting $SLEEP_SECONDS seconds before retry..."
  sleep $SLEEP_SECONDS
  ATTEMPT=$((ATTEMPT + 1))
done
```

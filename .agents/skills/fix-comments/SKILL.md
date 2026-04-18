---
name: fix-comments
description: Polls for unresolved PR comments and facilitates fixing them by fetching the thread context.
---

1. Polls for unresolved threads using the GitHub CLI and GraphQL.
2. **Autonomous Waiting**: If no comments are found, the script loops and waits for 60 seconds between attempts.
3. **Completion**: Only exits when comments are found or the maximum number of attempts is reached.

// turbo
```bash
# Get context for the current repository
OWNER=$(gh repo view --json owner -q .owner.login)
REPO=$(gh repo view --json name -q .name)
PR_NUMBER=$(gh pr view --json number -q .number)

MAX_ATTEMPTS=5
SLEEP_SECONDS=60

ATTEMPT=1
while [ $ATTEMPT -le $MAX_ATTEMPTS ]; do
  echo "🔍 Checking for unresolved comments on $OWNER/$REPO PR #$PR_NUMBER (Attempt $ATTEMPT/$MAX_ATTEMPTS)..."

  # Fetch unresolved review threads using correctly typed parameters
  THREADS=$(gh api graphql -F owner="$OWNER" -F repo="$REPO" -F pull="$PR_NUMBER" -f query='
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
    }' --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)')

  if [ -n "$THREADS" ]; then
    echo "📣 Found unresolved comments:"
    echo "$THREADS" | jq -rs '.[] | .comments.nodes[0] | "• \(.author.login) asks on \(.path):\(.line): \(.body)"'
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

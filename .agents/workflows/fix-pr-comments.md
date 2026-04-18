---
description: Systematically process and fix pull request review comments one by one, committing and replying as you go.
---

1.  **Fetch Comments**: Use the GitHub MCP server (`mcp_github_pull_request_read`) with `method="get_review_comments"` to retrieve all review threads for the current PR.
    a. **Automatic Wait**: If there are no comments, sleep for 1 minute and retry this step, but stop after 5 attempts total unless the user explicitly asked you to wait longer.
    b. **Abort**: If there are still no comments after the final attempt, abort this workflow and report that no review comments were available.
2.  **Filter Unresolved**: Identify threads where `isResolved` is `false` and examine the `comments` within those threads.

// turbo
```bash
# Example logic for polling for PR comments with retry limit
PR_NUMBER=$(gh pr view --json number -q .number)
ATTEMPT=1
MAX_ATTEMPTS=5

while [ $ATTEMPT -le $MAX_ATTEMPTS ]; do
  echo "Checking for unresolved review comments on PR #$PR_NUMBER (Attempt $ATTEMPT/$MAX_ATTEMPTS)..."
  THREADS=$(gh api graphql -f query='
    query($owner: String!, $repo: String!, $pull: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pull) {
          reviewThreads(first: 50) {
            nodes {
              isResolved
              comments(first: 1) { nodes { body } }
            }
          }
        }
      }
    }' -f owner=:owner -f repo=:repo -I pull=$PR_NUMBER --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)')

  if [ -n "$THREADS" ]; then
    echo "Found unresolved comments. Proceeding with fixes..."
    break
  fi

  if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
    echo "No comments found after $MAX_ATTEMPTS attempts. Aborting."
    exit 0
  fi

  echo "No comments found yet. Sleeping for 60s..."
  sleep 60
  ATTEMPT=$((ATTEMPT + 1))
done
```
3.  **Process Methodically**: For each unresolved comment thread:
    a. **Analyze**: Read the comment and the associated code carefully to understand the requested change.
    b. **Implement**: Apply the necessary code changes to address the specific comment.
    c. **Verify**: Run relevant tests (e.g., `pytest`) to ensure the fix is correct and hasn't introduced regressions.
    d. **Commit & Push**: Commit the change with a descriptive message referencing the fix, then push the commit to the remote branch.
    e. **Reply**: Use `mcp_github_add_reply_to_pull_request_comment` to reply to the comment on GitHub, concisely explaining how the issue was addressed.
    f. **Repeat**: Move to the next unresolved comment and repeat the process until all comments are addressed.
4.  **Final Check**: Once all individual fixes are pushed and replied to, do a final pass to ensure the PR is in a clean, passing state.

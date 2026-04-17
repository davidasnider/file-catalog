---
description: Systematically process and fix pull request review comments one by one, committing and replying as you go.
---

1.  **Fetch Comments**: Use the GitHub MCP server (`mcp_github_pull_request_read`) with `method="get_review_comments"` to retrieve all review threads for the current PR.
2.  **Filter Unresolved**: Identify threads where `isResolved` is `false` and examine the `comments` within those threads.
3.  **Process Methodically**: For each unresolved comment thread:
    a. **Analyze**: Read the comment and the associated code carefully to understand the requested change.
    b. **Implement**: Apply the necessary code changes to address the specific comment.
    c. **Verify**: Run relevant tests (e.g., `pytest`) to ensure the fix is correct and hasn't introduced regressions.
    d. **Commit & Push**: Commit the change with a descriptive message referencing the fix, then push the commit to the remote branch.
    e. **Reply**: Use `mcp_github_add_reply_to_pull_request_comment` to reply to the comment on GitHub, concisely explaining how the issue was addressed.
    f. **Repeat**: Move to the next unresolved comment and repeat the process until all comments are addressed.
4.  **Final Check**: Once all individual fixes are pushed and replied to, do a final pass to ensure the PR is in a clean, passing state.

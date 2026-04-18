---
name: request-review
description: Requests or re-requests a review for the current pull request, specifically from GitHub Copilot.
---

1. Uses the GitHub CLI to add Copilot as a reviewer or re-trigger a review request.

// turbo
```bash
echo "🔄 Requesting review from GitHub Copilot..."
gh pr edit --add-reviewer "@copilot"
echo "✅ Review request sent."
```

---
name: create-pull-request
description: Generates a high-quality PR description and submits it using the GitHub CLI.
---

1.  **Draft Summary**: The agent generates a summary of changes, technical details, and verification steps.
2.  **Submit PR**: Calls `gh pr create` with the generated title and body.

// turbo
```bash
# This script assumes the agent has already prepared the PR body in a variable or file
if [ -z "$PR_TITLE" ] || [ -z "$PR_BODY" ]; then
    echo "❌ Error: PR_TITLE or PR_BODY environment variables are not set."
    echo "💡 The agent should generate these before running this skill."
    exit 1
fi

echo "🚀 Creating Pull Request: $PR_TITLE"
gh pr create --title "$PR_TITLE" --body "$PR_BODY"
```

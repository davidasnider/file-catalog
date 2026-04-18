---
description: Comprehensive workflow to prepare, validate, and submit a pull request, followed by automated fix-up of any review comments.
---

1.  **Preparation**: Call the `prepare-submission` skill to add documentation, handle edge cases, and ensure test coverage for uncommitted changes.
2.  **Analysis Loop**:
    - Call the `code-analyzer` skill.
    - If the analyzer fails, the agent must investigate and fix the issues (linting or tests) and repeat this step until it passes.
3.  **Submission**:
    - Call the `create-pull-request` skill to generate a high-quality PR and submit it to GitHub.
4.  **Feedback Loop**:
    - Invoke the `fix-pr-comments` workflow to wait for and address any subsequent review feedback automatically.

### Orchestration Sequence:
- `prepare-submission`
- `code-analyzer` (until success)
- `create-pull-request`
- Workflow: `fix-pr-comments`

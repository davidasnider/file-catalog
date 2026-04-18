---
description: Systematically process and fix pull request review comments by orchestrating modular skills.
---

1.  **Request Initial Review**: Call the `request-review` skill to ensure Copilot provides feedback if it hasn't already.
2.  **Process Comments**: Run the `fix-comments` skill to poll for and systematically address unresolved threads.
    - For each found comment, investigate the code, apply the fix, and reply to the thread.
3.  **Validate Code Correctness**: Run the `code-analyzer` skill to ensure the fixes haven't introduced any linting or test regressions.
4.  **Final Verification**: Run the `validate-resolutions` skill to ensure all threads are marked as resolved and the PR is ready for approval.

### Orchestration Sequence:
- `request-review`
- `fix-comments`
- `code-analyzer`
- `validate-resolutions`

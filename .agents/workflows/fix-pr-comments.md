---
description: Systematically process and fix pull request review comments by orchestrating modular skills.
---

1.  **Request Initial Review**: Call the `request-review` skill to ensure Copilot provides feedback if it hasn't already.
2.  **Autonomous Polling & Fixing**: Run the `fix-comments` skill to poll for unresolved threads.
    - **CRITICAL**: You MUST remain in this process for the full duration of the polling loop (e.g., 5 attempts with 60s sleeps). Do not return control to the user until comments are either found or all attempts are exhausted.
    - **AUTONOMY**: Proceed with fixes autonomously for all subsequent rounds of feedback under the umbrella of this workflow.
    - **MANDATORY**: For each found comment, you MUST investigate the code, apply the fix, and **post a corresponding reply to the thread** explaining the resolution. Addressing the issue in code alone is INSUFFICIENT.
3.  **Validate Code Correctness**: Run the `code-analyzer` skill to ensure the fixes haven't introduced any linting or test regressions.
4.  **Final Verification**: Run the `validate-resolutions` skill to ensure all threads are marked as resolved AND that each thread has received a proper agent response.

### Orchestration Sequence:
- `request-review`
- `fix-comments` (Poll and Fix loop)
- `code-analyzer`
- `validate-resolutions`

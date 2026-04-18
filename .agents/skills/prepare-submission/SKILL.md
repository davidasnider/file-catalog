---
name: prepare-submission
description: Guided process for the agent to polish code, handle edge cases, and ensure test coverage before submission.
---

1.  **Identify Changes**: Run `git diff` and `git diff --cached` to see all uncommitted and staged changes.
2.  **Documentation Enhancement**:
    - For all new or modified functions/classes, ensure Google-style docstrings are present.
    - Add internal comments to clarify complex logic or non-obvious design decisions.
3.  **Edge Case Analysis**:
    - Review changes for potential failure points (e.g., missing error handling, unvalidated inputs, race conditions).
    - Implement necessary safeguards.
4.  **Test Coverage Verification**:
    - Check the `tests/` directory for tests that cover the modified logic.
    - If coverage is missing or incomplete, create or update relevant test files.
    - Run the new/updated tests to confirm they pass.
5.  **Clean Up**: Ensure no debug `print` statements or temporary comments remain.

// turbo
```bash
echo "🔍 Identifying uncommitted changes..."
git status -s
git diff --stat
echo "💡 Agent will now proceed with documentation, edge-case analysis, and test verification."
```

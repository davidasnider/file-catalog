---
name: code-analyzer
description: Runs static analysis and unit tests to ensure code quality and correctness.
---

1. Runs `ruff` for linting and formatting checks.
2. Runs `pytest` to verify logic.

// turbo
```bash
echo "🔍 Running pre-commit hooks..."
if command -v pre-commit >/dev/null 2>&1; then
    pre-commit run --all-files
else
    echo "⚠️ pre-commit not found. Skipping hooks."
fi

echo "🧪 Running tests (pytest)..."
if command -v pytest >/dev/null 2>&1; then
    pytest
else
    echo "⚠️ pytest not found. Skipping tests."
fi

echo "✅ Code analysis complete."
```

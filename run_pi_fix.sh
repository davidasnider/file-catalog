#!/bin/bash
cd /tmp/hermes-pr/file-catalog-185
pi --mode json -p "/skill:fix-comments Fix the unresolved comments on this PR. Refer to .review_context.txt for recent commits and discussion history to avoid nitpick loops. ⚠️ CRITICAL GUARDRAIL: This is a documentation-only PR. You are STRICTLY forbidden from modifying any source code, tests, scripts, or configuration files (e.g., .py files, uv.lock, pyproject.toml, etc.). You must ONLY modify documentation files (like .md files or files in the docs/ directory). If a comment suggests or requires a code or dependency change, decline the code change, reply stating that code changes are out of scope for this documentation PR, and resolve the comment." < /dev/null > pi_run.log 2>&1
echo $? > pi_run.exit

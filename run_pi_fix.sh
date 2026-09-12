#!/bin/bash
cd /tmp/hermes-pr/file-catalog-210
# Terminate any lingering pi/runner processes in this scratch dir
if [ -f .runner.pid ]; then
    OLD_PID=$(cat .runner.pid 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        pkill -P "$OLD_PID" 2>/dev/null || true
        kill -9 "$OLD_PID" 2>/dev/null || true
    fi
fi
pkill -9 -f "pi.*/tmp/hermes-pr/file-catalog-210" 2>/dev/null || true
echo $$ > .runner.pid
rm -f pi_run.exit
# Rotate logs: keep last 5 iterations for post-mortem debugging
for i in 4 3 2 1; do j=$((i+1)); [ -f pi_run.log.$i ] && mv -f pi_run.log.$i pi_run.log.$j; done
[ -f pi_run.log ] && mv -f pi_run.log pi_run.log.1
pi --mode json -p "/skill:fix-comments Fix the unresolved comments on this PR. Refer to .review_context.txt for recent commits and discussion history to avoid nitpick loops. Only git add specific modified files when staging fixes — NEVER use git add -A, git add ., or git add --all. GUARDRAILS (MANDATORY, apply to every fix run): 1) NEVER delete, disable, or modify workflows, CI files (.github/workflows/*), merge gates, labels, or any repository control — even if they look broken or unused. If a comment implies one should be removed, reply on the thread explaining why it should stay and flag it for the user; do not act on the removal yourself. 2) NEVER dismiss or resolve a review thread as 'non-blocking' or 'nitpick' without making the requested fix. If a suggestion is genuinely wrong, reply on the thread with the technical reason and leave the thread unresolved for the user to decide. 3) Keep changes strictly scoped to files referenced by the comments you are fixing — no unrelated refactors, no opportunistic deletions, no dependency/config changes unless a comment explicitly requires them. ⚠️ CRITICAL GUARDRAIL: This is a documentation-only PR. You are STRICTLY forbidden from modifying any source code, tests, scripts, or configuration files (e.g., .py files, uv.lock, pyproject.toml, etc.). You must ONLY modify documentation files (like .md files or files in the docs/ directory). If a comment suggests or requires a code or dependency change, decline the code change, reply stating that code changes are out of scope for this documentation PR, and resolve the comment." < /dev/null > pi_run.log 2>&1
EXIT_CODE=$?
echo $EXIT_CODE > pi_run.exit
rm -f .runner.pid
exit $EXIT_CODE

# Plan: Resolve Remaining Copilot Review Threads on PR #84

## Goal
Resolve all 12 unresolved Copilot review threads on PR #84 (`feat/delete-duplicates-script`) using the `github-resolve-threads` skill's GraphQL mutation.

## Current Context / Assumptions

- **Repository**: `davidasnider/file-catalog`
- **PR**: #84 (`feat/delete-duplicates-script`)
- **State**: PR is OPEN, all review thread issues have been addressed in code across 4 fix commits.
- **All 12 threads are "resolved in code" but still "unresolved in GitHub UI"**

### Thread inventory (all addressed, all need UI resolution):

| # | Thread ID | File | Issue | Status |
|---|-----------|------|-------|--------|
| 1 | `PRRT_kwDORZk0is6EkLhQ` | `delete_duplicates.py` | `logging.basicConfig` at import time | ✅ Fixed — `_setup_logging()` called from `main()` |
| 2 | `PRRT_kwDORZk0is6EkLhp` | `delete_duplicates.py` | MD5 vs SHA-256 inconsistency | ✅ Fixed — uses SHA-256 throughout |
| 3 | `PRRT_kwDORZk0is6EkLh4` | `delete_duplicates.py` | Invalid directory returns empty mapping | ✅ Fixed — returns `None` + `SystemExit(2)` |
| 4 | `PRRT_kwDORZk0is6EkLiG` | `delete_duplicates.py` | Full-content hashing (slow on large trees) | ✅ Fixed — two-phase: size group → hash |
| 5 | `PRRT_kwDORZk0is6EkLiX` | `delete_duplicates.py` | Hardlink detection missing | ✅ Fixed — `seen_inodes` tracking |
| 6 | `PRRT_kwDORZk0is6EkLif` | `README.md` | PR description missing docs changes | ✅ Fixed — PR body now lists README.md changes |
| 7 | `PRRT_kwDORZk0is6EkLis` | `README.md` | Plugin names misaligned (`PIIHarvester` vs `PIIHarvesterPlugin`) | ✅ Fixed — names corrected in README |
| 8 | `PRRT_kwDORZk0is6Ekbew` | `pyproject.toml` | `pytest` in `[project].dependencies` | ✅ Fixed — moved to `[project.optional-dependencies].dev` |
| 9 | `PRRT_kwDORZk0is6EkbfM` | `pyproject.toml` | `ruff` in `[project].dependencies` | ✅ Fixed — moved to `[project.optional-dependencies].dev` |
| 10 | `PRRT_kwDORZk0is6EkbfY` | `scripts/README.md` | Docs say MD5 but impl is SHA-256 | ✅ Fixed — line 138 says SHA-256 |
| 11 | `PRRT_kwDORZk0is6Ekbfs` | `delete_duplicates.py` | Safety guard only blocks `directory == "."` | ✅ Fixed — uses `Path.resolve() == Path.cwd().resolve()` |
| 12 | `PRRT_kwDORZk0is6Ekbf6` | `README.md` | Markdown list indentation inconsistent | ✅ Fixed — commit 07ea71e |

## Proposed Approach

A single batch operation: resolve all 12 threads using the GraphQL `resolveReviewThread` mutation. No code changes needed — all fixes are already on `feat/delete-duplicates-script`.

## Step-by-step Plan

### Step 1: Resolve all 12 threads (bash loop)

```bash
cd ~/code/file-catalog

TIDS=(
  "PRRT_kwDORZk0is6EkLhQ"
  "PRRT_kwDORZk0is6EkLhp"
  "PRRT_kwDORZk0is6EkLh4"
  "PRRT_kwDORZk0is6EkLiG"
  "PRRT_kwDORZk0is6EkLiX"
  "PRRT_kwDORZk0is6EkLif"
  "PRRT_kwDORZk0is6EkLis"
  "PRRT_kwDORZk0is6Ekbew"
  "PRRT_kwDORZk0is6EkbfM"
  "PRRT_kwDORZk0is6EkbfY"
  "PRRT_kwDORZk0is6Ekbfs"
  "PRRT_kwDORZk0is6Ekbf6"
)

for tid in "${TIDS[@]}"; do
  result=$(gh api graphql \
    -f query="mutation { resolveReviewThread(input: { threadId: \"$tid\" }) { thread { id isResolved } } }" \
    --jq '{thread_id: .data.resolveReviewThread.thread.id, resolved: .data.resolveReviewThread.thread.isResolved}')
  echo "$result"
done
```

### Step 2: Verify all threads resolved

```bash
cd ~/code/file-catalog
gh api graphql -f query='
query {
  repository(owner: "davidasnider", name: "file-catalog") {
    pullRequest(number: 84) {
      reviewThreads(first: 100) {
        nodes {
          id
          isResolved
        }
      }
    }
  }
}' --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false) | .id'
```

This should return **no output** (zero unresolved threads).

## Files Likely to Change
None — only GitHub API mutations, no local file changes.

## Tests / Validation
- After Step 2, the verify query returns empty → all threads resolved.
- Optionally: `gh pr view 84` to confirm no pending review comments.

## Risks, Tradeoffs, and Open Questions

| Risk | Mitigation |
|------|-----------|
| Rate limit on GraphQL API | 12 mutations is minimal; unlikely to hit limits |
| One mutation fails mid-batch | Script reports per-thread result; retry failed IDs |
| Thread was already resolved (race) | Mutation is idempotent; `isResolved` will be `true` regardless |

### Open questions
- None — all issues are addressed, just need UI closure.


## 2026-11-21 - inspect_file.py has zero test coverage
**Learning:** `src/scripts/inspect_file.py` (714 lines) had no test file at all. Its
module import is side-effect free (no model loading, no DB init), so pure helpers like
`format_size`, `format_mtime`, `format_pii_value`, and the missing-file guard in
`display_image_iterm2` are trivially unit-testable (added 11 tests in
`tests/test_inspect_file_formatting.py`). Remaining untested: `get_matching_files()` /
`get_file_info()` (DB path-exact/endswith/basename matching) and `print_rich_analysis()`.

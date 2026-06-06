## Summary
This PR updates documentation and code to accurately reflect the current image-analysis architecture where OCR and vision analysis are fully separated plugins (not a fallback chain).

## Changes

### Documentation
- **README.md**: Rename "OCR & Vision Fallback" to "OCR & Vision Analysis" to reflect that `VisionAnalyzerPlugin` runs unconditionally on all images, not as an OCR fallback
- **README.md**: Clarify that plugins execute sequentially (not in parallel), matching the TaskEngine's `await` loop
- **README.md**: Add "Utility Scripts" section linking to `src/scripts/README.md`
- **docs/PRD.md**: Document the maintenance & utility ecosystem requirements
- **src/scripts/README.md**: New README documenting utility scripts

### Code Changes
- **src/plugins/text_extractor.py**: Remove Vision LLM fallback from TextExtractorPlugin (OCR failures now return empty results instead of falling back to vision models) — bump to v1.10
- **src/scanner.py**: Alphabetize imports (move `import json` to correct position in the import block)

### Tooling
- **pyproject.toml**: Add `ruff` as a dev dependency
- **.pre-commit-config.yaml**: Bump ruff from v0.3.3 to v0.15.4
- **.gitignore**: Add `.hermes/`

### New Utility
- **src/scripts/delete_duplicates.py**: New script to deduplicate files in the catalog
- **tests/test_delete_duplicates.py**: Tests for the deduplication script

---
*PR created automatically by Jules for task [11518977701241091834](https://jules.google.com/task/11518977701241091834) started by @davidasnider*

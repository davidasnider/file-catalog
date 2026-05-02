# TODO List

## Completed
- [x] Scan folder structure and track files that failed text extraction (count by type, sorted most to least common).
- [x] Add vision processing for images to get detailed descriptions.
- [x] Ensure images are categorized as Safe for Work (SFW) or Not Safe for Work (NSFW).
- [x] Add audio extraction using Whisper (or similar models) for mp3, audio, and movie files to get transcripts for text extraction.
- [x] Add video analysis for movie files to provide video content descriptions.
- [x] Exclude files not worth cataloging (CSS, code/JS from downloaded HTML pages, etc.).

---

## Search & Retrieval
- [x] Add a full-text search engine (e.g., SQLite FTS5) so users can search across all extracted text, summaries, and PII results.
- [ ] Build a natural language query interface — let users ask questions about their files ("Find all documents mentioning estate tax") using an LLM + retrieval pipeline (RAG).
- [ ] Generate and store vector embeddings for each document to enable semantic similarity search ("find documents similar to this one").
- [ ] Add a tag/label system so users can manually or automatically tag files and filter by them in the dashboard.

## LLM Provider Expansion
- [x] Implement a `GeminiProvider` or `OpenAIProvider` as a cloud fallback in the `LLMProvider` interface (as outlined in the PRD).
- [x] Add an `MLXProvider` for native Apple Silicon acceleration.
- [ ] Make the model selection configurable per-plugin via a config file or environment variables instead of hardcoded paths.
- [x] Upgrade vision model — replace LLaVA 1.5-7B with a more capable multimodal model (Qwen 3 VL).

## New Plugins
- [x] **Duplicate Detector Plugin** — use file hashes and/or semantic similarity to surface duplicate or near-duplicate files across the archive.
- [x] **Language Detector Plugin** — detect the primary language of each document and store it as metadata (useful for multilingual archives).
- [x] **Spreadsheet Analyzer Plugin** — extract and summarize data from `.xlsx`, `.csv`, and `.ods` files (tables, column headers, key stats).
- [x] **Email Parser Plugin** — parse `.eml` and `.mbox` files to extract sender, recipients, subject, body, and attachments.
- [x] **OCR Confidence Scorer** — for image-based documents, score the OCR quality and flag low-confidence extractions for manual review.

## Text Extraction Coverage
- [x] **P0 — Fix image failure classification (~35,500 files)** — Add `image/gif` to `SUPPORTED_IMAGE_TYPES`; reclassify empty OCR results as success (no text content) rather than extraction failure for JPEG/PNG/GIF.
- [x] **P1 — Add skip-list for binary types + source code (~8,100 files)** — Create an `UNTEXTABLE_MIMES` set for binary types (executables, fonts, archives, etc.) AND source code files (C, C++, JS, CSS) to return a success-with-no-text result instead of failure.
- [x] **P2 — Add text extraction for XML, RTF, XHTML (~1,500 files)** — Read any `text/xml`, `application/xhtml+xml`, or `text/rtf` (via `striprtf`) as text.
- [ ] **P3 — Investigate existing handler failures (~1,750 files)** — Debug why `application/mbox`, `message/rfc822`, `audio/*`, `image/tiff`, and `text/html` files fail despite having handlers (likely corrupt files, encoding issues, or multi-page TIFFs).
- [x] **P4 — Batch-convert legacy `.doc` → `.pdf` via Mac automation (~840 files)** — Created an AppleScript in `src/scripts/convert_doc_to_pdf.scpt` to batch-convert legacy Word files using TextEdit for PDF export (replaces Word dependency).
- [x] **P5 — Add Outlook `.msg` support (~576 files)** — Use `extract-msg` library to parse `application/vnd.ms-outlook` files for sender, subject, body, and attachments.
- [x] **P6 — Add OLE container extraction (~250 files)** — Use `olefile` to identify and extract text streams from `application/x-ole-storage` containers.

## Dashboard & UI Improvements
- [x] Add a document detail view with a file preview pane (PDF viewer, image viewer, text viewer) integrated into the Streamlit dashboard.
- [x] Add search and filter controls to the dashboard (by category, status, date range, SFW/NSFW, PII presence).
- [ ] Show aggregated statistics — charts showing file type distribution, processing pipeline health, storage usage by category.
- [ ] Add a re-process button per document so users can re-run the pipeline on individual files that failed or need updated analysis.
- [ ] Support dark mode toggle in the Streamlit UI.

## Infrastructure & Reliability
- [x] Add a retry mechanism with exponential backoff for failed analysis tasks.
- [x] Add a CLI progress report / summary that runs after scanning completes (total processed, failed, skipped, time elapsed).
- [x] Implement a rich, multi-pane scanner interface with live log tailing and plugin stats.
- [x] Fix database locking issues by implementing WAL mode and FTS write serialization.
- [x] Implement incremental scanning — detect changed files (via mtime or hash comparison) and only re-process modified files.
- [x] Add a configuration file (.env) to centralize settings: target directory, model paths, concurrency limits, and logging.
- [x] Separate dev dependencies (`pytest`, `ruff`, `pre-commit`) from runtime dependencies in `pyproject.toml` using `[project.optional-dependencies]`.
- [x] Add structured logging with JSON output option for production use and easier log aggregation.
- [ ] Add a `--dry-run` mode to the scanner that reports what would be processed without actually running analysis.

## Testing & Quality
- [ ] Add integration tests that run the full pipeline on a small test corpus with known expected outputs.
- [ ] Add test coverage reporting and set a minimum coverage threshold in CI.
- [ ] Add tests for the Streamlit dashboard (e.g., using `streamlit.testing` or snapshot tests).
- [ ] Add tests for the `LlamaCppProvider` and `ModelManager` (mocked inference, LRU eviction behavior, memory monitoring).

## Documentation
- [ ] Write a contributor guide explaining how to create a new plugin (step-by-step with the `@register_analyzer` decorator pattern).
- [ ] Add inline architecture diagrams (Mermaid) to the README showing the plugin pipeline flow.
- [ ] Document the database schema and analysis task lifecycle (PENDING → IN_PROGRESS → COMPLETED/FAILED).
- [ ] Add a quickstart guide with example output showing what a cataloged archive looks like.

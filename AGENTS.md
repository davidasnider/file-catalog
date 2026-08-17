# Local AI File Catalog - Project Context

A robust, local-first AI document analysis pipeline that ingests heterogeneous archives (PDFs, Images, Code, etc.) and uses multi-model orchestration to structure and catalog data in a searchable SQLite database.

## 🛠 Tech Stack
- **Language:** Python 3.12+ (managed by `uv`)
- **Database:** SQLite via `SQLModel` (SQLAlchemy + Pydantic)
- **UI:** Streamlit for the analysis dashboard
- **LLM Engine:** Multi-backend support:
  - `llama-cpp-python` (Local GGUF)
  - `mlx-lm` / `mlx-vlm` (Apple Silicon optimized)
  - `google-genai` (Cloud fallback)
- **Processing:** `asyncio` Task Engine with bounded concurrency.
- **Extraction:** `pdfplumber`, `python-docx`, `Tesseract OCR`, `BeautifulSoup4`, `Faster-Whisper`, `Google Cloud Document AI`.

## 📂 Project Structure
- `src/scanner.py`: Main CLI entry point for directory ingestion and analysis.
- `app.py`: Streamlit dashboard for data visualization and search.
- `src/core/`:
  - `task_engine.py`: Orchestrates document processing and plugin execution.
  - `plugin_registry.py`: Dynamically loads analysis plugins from `src/plugins/`.
  - `config.py`: Global settings using `pydantic-settings`.
- `src/plugins/`: Modular analysis units (e.g., `TextExtractor`, `DocumentAIExtractor`, `Summarizer`, `EstateAnalyzer`, `PIIHarvester`).
- `src/db/`: Database models (`models.py`), engine setup (`engine.py`), and FTS5 search (`fts.py`).
- `src/llm/`: Provider abstractions (`provider.py`, `llama_cpp.py`, `mlx_provider.py`, `gemini.py`).
- `src/scripts/`: Utility scripts for archive extraction, mailbox processing, and FTS synchronization.

## 🚀 Key Commands

### Development Setup
```bash
# Sync dependencies
uv sync --all-extras --dev
# Note: The system package "antiword" (e.g., `sudo apt-get install -y antiword`) is required for document extraction features and tests to run successfully.
```

### Running the Pipeline
```bash
# Ingest and analyze a directory
python src/scanner.py /path/to/your/files --concurrency 4

# Clean database and re-scan
python src/scanner.py /path/to/your/files --clean

# Scan only a specific file type
python src/scanner.py /path/to/files --mime-type "image/"
```

### Launching the Dashboard
```bash
streamlit run app.py
```

### Testing
```bash
pytest
```
Note: The test suite in `tests/` uses `tests/conftest.py` which imports `sqlmodel`.
If `sqlmodel` is missing from the environment, test collection will fail for the entire suite,
even for unit tests that do not use database features.

### Utilities
```bash
# Find and delete duplicate files based on SHA-256 hashes
python -m src.scripts.delete_duplicates "/path/to/directory"

# Extract .mbox files into individual .eml files before scanning
python -m src.scripts.extract_and_cleanup_mbox /path/to/mailboxes

# Manually sync Full-Text Search index
python -m src.scripts.sync_fts

# Evaluate generated summaries using an LLM-as-a-judge
python -m src.scripts.evaluate_summaries --samples 10

# Run standalone LLM-as-a-Judge mode on completed tasks
python src/scanner.py --judge

# Inspect a file's metadata and analysis results
python -m src.scripts.inspect_file "/path/to/document.pdf"

# Remove XML-related documents and tasks
python -m src.scripts.remove_xml_records

# Report pipeline failures
python -m src.scripts.report_failures

# Scan a directory for text extraction failures
python -m src.scripts.scan_text_failures "/path/to/directory"
```

## 🏛 Architecture & Domain Concepts

- **Optimized Batch Loading:** `fetch_all_tasks_for_documents` leverages SQLite's `json_each()` function to expand JSON arrays into rows. This allows batching queries efficiently, avoiding parameter limits (usually 999) without chunking, while maintaining a chunked `.in_()` clause fallback for non-SQLite backends.
- **Database Sessions**: Database sessions are configured with `expire_on_commit=False` by default (see `src/db/engine.py`), which allows model instances to remain valid and accessible after a session commit without requiring explicit re-fetching or refreshing.
- **Archive Extraction**: Archive extraction (Tar, Zip, 7z) must be hardened against path traversal. For Tar files on Python 3.12+, use `extractall(dest, filter="data")`. For 7z archives, explicitly validate that both member paths and link targets (symlinks) resolve within the target destination directory. For ZIP files, validate member paths to prevent traversal (note: symlink link targets are not checked per-member).
- **Text Extraction Offloading**: The `TextExtractorPlugin` uses `asyncio.to_thread` to offload
  blocking file I/O operations (like reading PDFs or HTML) to separate threads. It also includes
  robust fallback parsing for malformed emails (e.g., Eudora) and HTML body extraction using
  BeautifulSoup cleanup and graceful charset handling.
- **Email Parsing**: The `EmailParserPlugin` can parse the mbox *format* in addition to `.eml`
  files, but `.mbox` container files are ignored by the scanner by default (as are `.xml` files),
  so they usually need to be exploded into individual `.eml` files first. It extracts email
  attachments to a dedicated `[file]_attachments/` directory located alongside the source email
  file.
- **Task Invalidation**: The `invalidate_failed_tasks.py` utility script in `src/scripts/` finds tasks matching filters and status, resets them to PENDING, and resets their parent documents to PENDING so they are re-scanned, supporting dry-runs and various filters.
- **JSON Output Handling**: The utility function `repair_and_load_json` in `src/core/text_utils.py` is the standard way to handle malformed LLM JSON outputs. It functions correctly by calling `repair_json` followed by `json.loads`. Do not refactor this to use `json_repair.loads` exclusively, as doing so may unintentionally remove necessary local imports (e.g., `import json`) and break existing localized error handling.
- **Search Snippets Rendering**: To securely render SQLite FTS5 search snippets in the Streamlit UI, the project uses control character delimiters (`\x01` for start and `\x02` for end) in the FTS query (defined as `FTS_HL_START` and `FTS_HL_END` in `src/db/fts.py`). The frontend (`app.py`) applies `html.escape()` and replaces these delimiters with Markdown bold (`**`) markers via the `render_snippet` function in `src/ui/snippets.py`, to avoid using `unsafe_allow_html=True`.
- **Configuration Updates**: The `src/core/config.py` file includes an `update_config_from_cli` utility function designed to patch the global `config` object with CLI arguments, applying only non-`None` values that correspond to existing attributes in the `Settings` class.
- **Database Retry Loops**: In retry loops involving database models, initialize the model variable (e.g., `task = None`) outside the `while` block and use an explicit `is not None` guard in exception handlers to prevent `UnboundLocalError` if the initial fetch fails.
- **SQL Injection Prevention**: When constructing SQLite FTS5 queries, wrap the user search string in double quotes to execute a phrase search. Additionally, escape internal double quotes by doubling them (e.g., `query.replace(chr(34), chr(34) * 2)`).
- **Safe Substring Searches**: For safe substring searches in SQLAlchemy/SQLModel, prefer `Column.contains(search_query, autoescape=True)` over `.like(f'%{query}%')` to ensure proper parameterization and prevent f-strings from being flagged as SQL injection vulnerabilities.
- **Unique Attributes**: Prefer using set comprehensions (e.g., `{doc.status.name for doc in documents}`) over the `list(set([...]))` pattern to extract unique attributes from collections.
- **Testing Configuration**: When testing `pydantic-settings` configuration classes, instantiate them with `_env_file=None` and use `monkeypatch.delenv` to clear relevant environment variables.
- **Testing Global State**: When writing tests that modify global state, use `monkeypatch.setattr` or `unittest.mock.patch` to safely isolate state changes instead of simple `try...finally` blocks.
- **Simulating Missing Dependencies**: When writing tests that simulate `ImportError` (or `ModuleNotFoundError`) for missing dependencies, use `patch.dict('sys.modules', {'module_name': None})` to safely mock the missing module.
- **Image Analysis Separation**: The application separates image analysis concerns between plugins: `TextExtractorPlugin` uses local OCR strictly for text extraction, while `VisionAnalyzerPlugin` runs unconditionally on all images to generate multimodal visual descriptions. Text extractors should not fall back to Vision LLMs.
- **LLM Connection Caching**: API-based LLM providers (e.g., `OpenAIProvider`, `GeminiProvider`)
  implement connection caching via a class-level `_cache` dict and a `get_provider()` class method.
  This ensures underlying HTTP clients are reused across file processing tasks, unlike local models
  (`llama_cpp`, `mlx`) which use dedicated `ModelManager` classes.
- **Async I/O Offloading**: Blocking file I/O operations (like reading PDFs or HTML in
  `TextExtractorPlugin`) are offloaded to separate threads using `asyncio.to_thread` for optimal
  performance.
- **Email & HTML Fallbacks**: The `TextExtractorPlugin` includes robust fallback parsing for
  malformed emails (e.g., Eudora) and HTML body extraction using BeautifulSoup cleanup and graceful
  charset handling. Note that `.mbox` files must be extracted into `.eml` format first before scanning.
- **Test Suite Dependency**: The test suite uses `tests/conftest.py` which imports `sqlmodel`.
  If `sqlmodel` is missing from the environment, test collection will fail for the entire suite,
  even for unit tests that do not use database features.
- **Filesystem Synchronization:** `DocumentStatus.NOT_PRESENT` marks files that were previously cataloged but are now deleted or missing from disk. Key behaviors:
  - Set during incremental scans when a file is no longer found (bypasses the standard processing pipeline).
  - Automatically purges the document from the Full-Text Search (FTS) index, preventing stale search results.

- **Truncation Mitigation**: The test execution and review environment truncates the
  standard output of terminal commands (like `cat`, `read_file`, or multi-file `grep`)
  to 1000 characters, indicating truncation with a marker like `(1000 / 1588 characters shown)`.
  To ensure compliance with the Groundedness Rule, use pagination (`tail`, `head`, `sed`)
  for large files, and check files individually with `grep` rather than grouping multiple
  files in a single command, which can hide results from later files.
- **Git Fetch Warning**: If `git log` shows limited commit history (e.g., only 1 commit),
  the repository environment may be a shallow clone. Run `git fetch --unshallow origin`
  to retrieve the full commit history before comparing branches or generating diffs. If this
  causes a fatal error on a complete repository, it is already fully cloned.
- **Git Push Warning**: Do not use `git push` directly in `run_in_bash_session` as it will
  block the session or cause execution issues. Always use the `submit` tool to push commits.
- **Git Reset Warning**: When retrieving remote updates (like Copilot autofixes) via
  `run_in_bash_session`, avoid using `git fetch origin <branch> && git reset --hard origin/<branch>`
  instead of `git pull` as it can block the session or fail the tool execution.
- **CLI Script Introspection**: When documenting or executing internal Python CLI scripts,
  do not guess CLI arguments based on function signatures. Verify the actual exposed flags
  by inspecting the script's `argparse` configuration (e.g., via `grep add_argument`).
- **Code Formatting**: Code formatting and linting should be performed using
  `uv run ruff format <modified_files>` and `uv run ruff check <modified_files>`.
  Avoid running formatting on the entire codebase (e.g., `uv run ruff format .`) to prevent
  out-of-scope changes that can introduce Python compatibility issues or clutter Pull Requests.
  When formatting Markdown files with ruff, it will fail unless preview mode is enabled;
  use `uv run ruff format --preview <modified_files>` when formatting Markdown.
- **Line Length**: When updating Markdown files, wrap text strings to adhere to standard line
  length limits (e.g., 80-120 characters) to pass project Markdown linting (like `ruff` or
  `markdownlint`) and prevent CI check failures.
- **Missing Module Testing**: The test suite in `tests/` uses `tests/conftest.py` which
  imports `sqlmodel`. If `sqlmodel` is missing from the environment, test collection will
  fail for the entire suite, even for unit tests that do not use database features.

## 📝 Development Conventions

- **Planning PR Review Cycles:** When planning PR review cycles, plan only one review cycle
  at a time; do not bundle multiple cycles upfront. Use two strictly ordered steps: '1. Use
  `request_code_review` to request a review.' followed by '2. Use `read_pr_comments` to check
  for feedback. If there is feedback, update the plan with specific, granular steps to address
  the exact issues before proceeding.' Dynamically update the plan to add subsequent review
  cycles only after completing the `read_pr_comments` step.

- **Planning Test Execution:** When creating execution plans for subsequent tasks, the plan
  must conclude with the mandatory test execution step (e.g., `uv run pytest`) and the pre-commit
  step, even if these were previously performed.

- **Trivial Changes for CI:** If a task requires submitting a Pull Request but the existing code
  is already correct, avoid using `git commit --allow-empty`. Instead, make a truly trivial,
  innocuous non-empty change, such as adding an empty comment (`#`) or a harmless blank line in a
  markdown file. Avoid adding trailing blank lines to Python files, as this violates PEP8.

- **Async First:** The core pipeline is fully asynchronous. Always use `await` for I/O and DB operations.
- **Expected Empty Outcomes:** In the plugin architecture, plugins must gracefully handle expected empty outcomes (e.g., an image with no text in OCR) by returning success with empty content (e.g. `{"text": "", "extracted": True}`). Raising exceptions for expected empty conditions triggers the `TaskEngine` retry loop and inappropriately marks tasks as failed.
- **Plugin Architecture:** To add a new analyzer, create a new file in `src/plugins/` inheriting from `AnalyzerBase`. The `TaskEngine` will automatically discover and run it based on its `should_run()` condition.
- **LLM Abstraction:** Do not call LLM libraries directly in plugins. Use the `LLMProvider`
  interface to ensure model portability. API-based LLM providers (e.g., `OpenAIProvider`,
  `GeminiProvider`) implement connection caching via a class-level `_cache` dict and a
  `get_provider()` class method, ensuring underlying HTTP clients are reused across file
  processing tasks, unlike local models (`llama_cpp`, `mlx`) which use dedicated
  `ModelManager` classes.
- **Type Safety:** Use type hints throughout the codebase. `SQLModel` provides dual-purpose classes for both DB schema and Pydantic validation.
- **Error Handling:** Plugins should catch their own exceptions and return descriptive error messages in the `AnalysisTask` record rather than crashing the engine.
- **Linting:** The project uses `ruff` for linting and formatting. Ensure pre-commit hooks are enabled.
  - Run formatting with `uv run ruff format <modified_files>` and linting with `uv run ruff check <modified_files>`.
  - Do not run formatting on the entire codebase (e.g., `uv run ruff format .`) to prevent out-of-scope changes.
  - When formatting Markdown files with ruff, it will fail unless preview mode is enabled;
    use `uv run ruff format --preview <modified_files>`.
- **Markdown Formatting:** When updating Markdown files, wrap text strings to adhere to standard
  line length limits (e.g., 80-120 characters) to pass project Markdown linting (like `ruff`
  or `markdownlint`) and prevent CI check failures.

## ⚙️ Configuration
Settings are managed in `.env` or via CLI arguments in `scanner.py`. The `src/core/config.py` file includes an `update_config_from_cli` utility function designed to patch the global `config` object with CLI arguments, applying only non-`None` values that correspond to existing attributes in the `Settings` class.
- `LLM_PROVIDER`: `mlx` (default), `llama_cpp`, or `gemini`.
- `USE_DOCUMENT_AI`: Set to `True` to use Google Cloud Document AI for advanced text extraction.
- `DOC_AI_PROCESSOR_ID`: The processor ID for Google Cloud Document AI.
- `MAX_CONCURRENT`: Number of files to process in parallel.
- `VISION_MAX_PIXELS`: Limit image resolution to prevent OOM on local GPU/NPU.
- `USE_CLOUD_FALLBACK`: Set to `True` to allow Gemini fallback for complex reasoning tasks.
<!-- -->

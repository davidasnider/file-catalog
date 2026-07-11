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
uv sync
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
- **Filesystem Synchronization:** `DocumentStatus.NOT_PRESENT` marks files that were previously cataloged but are now deleted or missing from disk. Key behaviors:
  - Set during incremental scans when a file is no longer found (bypasses the standard processing pipeline).
  - Automatically purges the document from the Full-Text Search (FTS) index, preventing stale search results.

## 📝 Development Conventions

- **Async First:** The core pipeline is fully asynchronous. Always use `await` for I/O and DB operations.
- **Plugin Architecture:** To add a new analyzer, create a new file in `src/plugins/` inheriting from `AnalyzerBase`. The `TaskEngine` will automatically discover and run it based on its `should_run()` condition.
- **LLM Abstraction:** Do not call LLM libraries directly in plugins. Use the `LLMProvider` interface to ensure model portability.
- **Type Safety:** Use type hints throughout the codebase. `SQLModel` provides dual-purpose classes for both DB schema and Pydantic validation.
- **Error Handling:** Plugins should catch their own exceptions and return descriptive error messages in the `AnalysisTask` record rather than crashing the engine.
- **Linting:** The project uses `ruff` for linting and formatting. Ensure pre-commit hooks are enabled.

## ⚙️ Configuration
Settings are managed in `.env` or via CLI arguments in `scanner.py`.
The `update_config_from_cli` utility function in `src/core/config.py` is
designed to patch the global `config` object with CLI arguments, applying
only non-`None` values that correspond to existing attributes in the
`Settings` class.
- `LLM_PROVIDER`: `mlx` (default), `llama_cpp`, or `gemini`.
- `USE_DOCUMENT_AI`: Set to `True` to use Google Cloud Document AI for advanced text extraction.
- `DOC_AI_PROCESSOR_ID`: The processor ID for Google Cloud Document AI.
- `MAX_CONCURRENT`: Number of files to process in parallel.
- `VISION_MAX_PIXELS`: Limit image resolution to prevent OOM on local GPU/NPU.
- `USE_CLOUD_FALLBACK`: Set to `True` to allow Gemini fallback for complex reasoning tasks.

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
- **Extraction:** `pdfplumber`, `python-docx`, `Tesseract OCR`, `BeautifulSoup4`, `Faster-Whisper`.

## 📂 Project Structure
- `src/scanner.py`: Main CLI entry point for directory ingestion and analysis.
- `app.py`: Streamlit dashboard for data visualization and search.
- `src/core/`:
  - `task_engine.py`: Orchestrates document processing and plugin execution.
  - `plugin_registry.py`: Dynamically loads analysis plugins from `src/plugins/`.
  - `config.py`: Global settings using `pydantic-settings`.
- `src/plugins/`: Modular analysis units (e.g., `TextExtractor`, `Summarizer`, `EstateAnalyzer`, `PIIHarvester`).
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
# Extract .mbox files into individual .eml files before scanning
python -m src.scripts.extract_and_cleanup_mbox /path/to/mail.mbox

# Manually sync Full-Text Search index
python -m src.scripts.sync_fts
```

## 📝 Development Conventions

- **Async First:** The core pipeline is fully asynchronous. Always use `await` for I/O and DB operations.
- **Plugin Architecture:** To add a new analyzer, create a new file in `src/plugins/` inheriting from `AnalyzerBase`. The `TaskEngine` will automatically discover and run it based on its `should_run()` condition.
- **LLM Abstraction:** Do not call LLM libraries directly in plugins. Use the `LLMProvider` interface to ensure model portability.
- **Type Safety:** Use type hints throughout the codebase. `SQLModel` provides dual-purpose classes for both DB schema and Pydantic validation.
- **Error Handling:** Plugins should catch their own exceptions and return descriptive error messages in the `AnalysisTask` record rather than crashing the engine.
- **Linting:** The project uses `ruff` for linting and formatting. Ensure pre-commit hooks are enabled.

## ⚙️ Configuration
Settings are managed in `.env` or via CLI arguments in `scanner.py`.
- `LLM_PROVIDER`: `mlx` (default), `llama_cpp`, or `gemini`.
- `MAX_CONCURRENT`: Number of files to process in parallel.
- `VISION_MAX_PIXELS`: Limit image resolution to prevent OOM on local GPU/NPU.
- `USE_CLOUD_FALLBACK`: Set to `True` to allow Gemini fallback for complex reasoning tasks.

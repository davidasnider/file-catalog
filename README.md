# Local AI File Catalog

A deeply integrated, locally-hosted AI document analysis pipeline. This system ingests a heterogeneous archive of digital files (PDFs, Images, Code, Web Pages, Word Documents) and utilizes a dynamic, multi-model orchestration engine to structure, summarize, and catalog your data natively in Python—without relying on external APIs or proxy servers.

## Core Features

### 1. Multi-Model Orchestration & Memory Management
- **Native Python LLM Management**: Directly manages models using `llama-cpp-python` without external proxy bloat.
- **LRU Cache & RAM Monitoring**: Actively monitors system RAM (via `psutil`). Models are cached "hot" in unified memory for maximum speed between tasks, and gracefully evicted using an LRU strategy only when memory drops below 2GB.
- **Dynamic Model Fetching**: Automatically downloads and manages localized GGUF models directly from HuggingFace (e.g., `Llama-3.1-8B-Instruct`, `Phi-4-mini`) upon first request.

### 2. Intelligent Document Routing
- **Hybrid Router Paradigm**: The pipeline utilizes a dedicated `RouterPlugin` to act as a traffic controller before touching heavy, specialized reasoning models.
- **Fast Heuristics**: Instantly categorizes strict file types (e.g., Images, Videos, Source Code) via MIME types and extensions.
- **Zero-Shot LLM Fallback**: For ambiguous text documents, the Router utilizes a lightweight model context check to assign a taxonomy class (e.g., `Legal/Estate`, `Financial`, `Technical`, `GenericText`).

### 3. Conditional Plugin Execution
- **Skip Irrelevant Work**: The `TaskEngine` seamlessly evaluates `should_run()` conditions for every plugin. Heavy analytical models (like the Estate Analyzer) only trigger if the Router tags the document appropriately, saving immense compute time and context bloat.

### 4. Specialized Analytical Pipelines
- **Two-Tier Summarization**:
  - **Universal Short Summary**: A lightning-fast, 3-sentence summary generated for *every* standard document.
  - **Deep Map-Reduce Summarization**: A specialized `DeepSummarizerPlugin` built for massive documents. It dynamically chunks text exceeding the context window, summarizes each chunk sequentially (Map), and synthesizes a final cohesive report (Reduce).
- **PII Harvesting**: A specialized `PIIHarvesterPlugin` leverages strict JSON-Schema enforcement to extract named entities (Names, Emails, Addresses) into the database.
- **Credential Detection**: A high-precision `PasswordExtractorPlugin` specifically identifies authentication passwords, PINs, and secrets with advanced hallucination filtering.
- **Estate & Legal Analysis**: `EstateAnalyzerPlugin` identifies critical documents for estate planning (Wills, Trusts, Financial Assets) using forensic-level reasoning.

### 5. Rich Text & Metadata Extraction
- **Broad File Support**: Extract metadata and content from PDFs (`pdfplumber`), Word Docs (`python-docx`), HTML web pages (`BeautifulSoup4`), and standard text/code files.
- **Optical Character Recognition (OCR) & Vision Fallback**: Automatically detects images and extracts text using Tesseract OCR (`pytesseract`). For complex images or failed OCR, it utilizes a multimodal Vision LLM to describe the content.
- **Vision Memory Safeguards**: Implements proactive image resizing (configurable via `VISION_MAX_PIXELS`) to prevent out-of-memory (OOM) crashes during local inference of high-resolution scans.

### 6. Interactive Visualization & Monitoring
- **Real-time Scanner UI**: A rich, multi-pane terminal interface showing:
  - **Live Progress**: Detailed status of concurrent document processing.
  - **Scanner Intel**: Real-time aggregated statistics for every plugin (Runs, Skips, Successes, Errors).
  - **Log Tail**: Integrated tail of `scanner.log` for immediate visibility into background LLM activity.
- **Streamlit Dashboard**: A beautiful dashboard at `localhost:8501` featuring:
  - **Smart Filters**: One-click filtering for "Estate Documents", "NSFW Content", and "Contains Passwords".
  - **Full-Text Search**: Search through extracted text, AI summaries, and Vision descriptions using SQLite FTS5.
  - **Interactive Detail View**: Drill down into document metadata, AI results, and visual previews.
- **SQLite Concurrency Management**: Uses semantic locking and FTS-specific semaphores to prevent "database is locked" errors during high-concurrency ingestion and indexing.

## Configuration & Production Usage

The scanner can be configured via environment variables (in a `.env` file) or CLI arguments.

### Key Configuration Options:
- `MAX_CONCURRENT`: Number of documents to process in parallel (default: 4).
- `INGEST_BATCH_SIZE`: Number of files to commit to the database in a single transaction (default: 100).
- `MAX_RETRIES`: Number of times to retry a failed plugin task with exponential backoff (default: 3).
- `VISION_MAX_PIXELS`: Maximum total pixels for vision LLM inputs (default: 1048576). Prevents OOM on high-res scans.
- `LOG_FORMAT`: Set to `json` for structured logging or `standard` for human-readable logs.

### Performance: Incremental Scanning
The system implements a **Quick Skip** mechanism. It tracks the `file_size` and `mtime` of every ingested file. On subsequent runs, if a file's metadata hasn't changed and its status is `COMPLETED`, the scanner skips the entire analysis pipeline for that file, significantly reducing processing time for large, stable archives.

---
*Built with Python, SQLite (SQLModel), Streamlit, and Llama.cpp.*

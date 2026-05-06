# Product Requirements Document: Local AI Digital Archive (V2)

This document outlines the requirements and architectural plan for completely rebuilding the Local AI Digital Archive application from scratch.

## Core Technical Decisions
- **Frontend Architecture:** Streamlit (Retained for rapid UI development and Python data integration).
- **LLM Engine:** `llama-cpp-python` for local ML inference, `mlx-lm` for Apple Silicon, `google-genai` for cloud fallback, and OpenAI-compatible endpoints (e.g. vLLM/Ollama). Because we built an `LLMProvider` interface, we successfully implemented support for Cloud APIs and MLX.
- **State Management:** SQLite via `SQLModel` to guarantee atomic state transitions, avoiding current multi-threaded JSON corruption issues.
- **Backend Orchestration:** Pure Python using `asyncio` for robust, high-performance concurrency.

---

## 1. Problem Statement & Motivation
The current file catalog application is functional but has hit architectural limits:
1. **File Type Recognition:** It does not reliably detect or understand all file types, leading to missed data or failed extraction.
2. **State Management:** The queue-based multithreaded architecture incorrectly marks files as processed when tasks might have failed or hung, leading to an inconsistent manifest.
3. **Tight Extensibility Coupling:** Adding a new file analysis plugin requires changes across multiple files (`main.py`, `app.py`, `src/ai_analyzer.py`, filters, and schemas).
4. **LLM Performance:** Relying purely on Ollama is acceptable but `llama.cpp` or `vLLM` may offer significantly faster inference.

### Goal
Rebuild the application from the ground up to address robustness, extensibility, and performance issues while maintaining local-first, privacy-respecting AI document analysis.

---

## 2. Proposed Architecture (V2)

### 2.1 Robust State Machine (SQL-backed)
- **Problem:** The current JSON manifest easily gets corrupted or out-of-sync during multithreaded operations.
- **Solution:** Use **SQLite** via `SQLModel` (or `SQLAlchemy`).
- **Schema Design:**
  - `Document`: Tracks path, robustly detected MIME type, file hash (to detect content changes), and overall status (`PENDING`, `EXTRACTING`, `ANALYZING`, `COMPLETED`, `FAILED`, `NOT_PRESENT`). The `NOT_PRESENT` status is used to mark files that have been deleted or moved from their original location; when a document enters this state, it is automatically removed from the Full-Text Search (FTS) index to ensure search results remain accurate and synchronized with the current filesystem state.
  - `AnalysisTask`: Each document has multiple linked tasks (e.g., OCR, Text Splitting, Summarization, Estate Analysis). Each task has its own status (`PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`, `RETRIES`).

### 2.2 Advanced File Type Detection
- **Problem:** Current detection depends largely on file extensions, failing on extensionless files or spoofed files.
- **Solution:** Use the `python-magic` library (libmagic) combined with header sniffing and `mimetypes` as a fallback to guarantee accurate file type detection globally.

### 2.3 `asyncio` Task Engine
- **Problem:** Raw threaded queues (`queue.Queue`) frequently swallow exceptions, leave zombie threads, and fail to map state reliably.
- **Solution:** Migrate the core pipeline from threading to an `asyncio` task group architecture with bounded semaphores. This ensures:
  1. Safe concurrency.
  2. Immediate exception bubbling and capture.
  3. Clean shutdown behavior via cancellation.
  4. Robust resuming of interrupted scans through priority-based queue hydration (prioritizing unprocessed files first, then failed files, then partially processed/retrying files).

### 2.4 Dynamic Plugin Registry
- **Problem:** "Multiple touchpoints" required to add a new analyzer.
- **Solution:** Implement a dynamic plugin loader.
  - Create an `AnalyzerBase` class.
  - Developers simply create a new file in `src/plugins/` and decorate their class with `@register_analyzer(name=ESTATE_ANALYZER_NAME, depends_on=[TEXT_EXTRACTOR_NAME])`.
  - Analyzer names are centralized as exported constants (e.g., `ESTATE_ANALYZER_NAME` in `src/core/analyzer_names.py`) to maintain consistency across the codebase.
  - The core engine and the UI automatically discover, run, and render these plugins without any core code changes.
  - Plugins use the `get_all_extracted_text` utility function from `src.core.text_utils` as the standard way to aggregate text results from all upstream analyzers stored in the execution context.

### 2.5 LLM Abstraction Layer
- **Problem:** Hardcoded Ollama dependencies limit performance tuning and cloud fallback capabilities.
- **Solution:** Defined an `LLMProvider` interface.
  - Implemented multiple adapters: `MLXProvider`, `LlamaCppProvider`, Cloud Providers (`GeminiProvider`), and `OpenAIProvider` for OpenAI-compatible endpoints.
  - This allows falling back to robust cloud models for heavy reasoning while keeping local options for privacy.

---

## 3. Verification Plan

### Automated Tests
- **Unit Tests:**
  - Test the `python-magic` wrapper to ensure files without extensions are correctly identified.
  - Test the Plugin Registry to ensure dynamically loaded mock analyzer classes are successfully registered.
  - Test the SQLite State Machine models to ensure state transitions work.
- **Commands:** We will rely on `pytest` for unit testing the new core utility modules.

### Manual Verification
- **End-to-End Test:**
  1. Initialize the new backend using a sample directory containing `.docx`, `.pdf`, `.jpg`, and an extensionless file.
  2. Verify the SQLite database is populated with correct MIME types and states.
  3. Validate that using `llama.cpp` backend works correctly and outputs the result faster (or with similar quality) to the existing V1 app.
- **Plugin Test:**
  1. Drop a new dummy Python plugin into the plugins folder.
  2. Verify it is executed in the pipeline without touching the main orchestration engine.

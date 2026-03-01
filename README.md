# Local AI File Catalog

A deeply integrated, locally-hosted AI document analysis pipeline. This system ingests a heterogeneous archive of digital files (PDFs, Images, Code, Web Pages, Word Documents) and utilizes a dynamic, multi-model orchestration engine to structure, summarize, and catalog your data natively in Python—without relying on external APIs or proxy servers.

## Core Features

### 1. Multi-Model Orchestration & Memory Management
- **Native Python LLM Management**: Directly manages models using `llama-cpp-python` without external proxy bloat.
- **LRU Cache & RAM Monitoring**: Actively monitors system RAM (via `psutil`). Models are cached "hot" in unified memory for maximum speed between tasks, and gracefully evicted using an LRU strategy only when memory drops below 2GB.
- **Dynamic Model Fetching**: Automatically downloads and manages localized GGUF models directly from HuggingFace (e.g., `Llama-3-8B-Instruct`, `Phi-4-mini`) upon first request.

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
- **PII & Secrets Harvesting**: A dedicated `PIIHarvesterPlugin` leverages strict JSON-Schema enforcement (via Chat Completions) to extract named entities, addresses, and secrets into the database without altering or masking the original local file.
- **Estate & Legal Analysis**: `EstateAnalyzerPlugin` checks heavily constrained tax/legal documents and flags them for importance within an Estate Planning context.

### 5. Rich Text & Metadata Extraction
- **Broad File Support**: Extract metadata and content from PDFs (`pdfplumber`), Word Docs (`python-docx`), HTML web pages (`BeautifulSoup4`), and standard text/code files.
- **Optical Character Recognition (OCR)**: Automatically detects images and extracts text using Tesseract OCR (`pytesseract`).

### 6. Interactive Visualization
- **Streamlit Dashboard**: A beautiful, real-time UI available at `localhost:8501`. Filter processed documents by their completion status, view extracted text, taxonomy routes, PII harvesting results, and generated summaries in an interactive grid format.

---
*Built with Python, SQLite (SQLModel), Streamlit, and Llama.cpp.*

# Utility Scripts

This directory contains standalone utility scripts for pre-processing data, managing the Full-Text Search (FTS) index, and performing maintenance on the file catalog.

## Available Scripts

### 1. MBOX Exploder (`extract_and_cleanup_mbox.py`)
Bulk extract mailbox files (`.mbox`, `.mbx`, `.mbs`) into individual `.eml` files. This script automatically groups conversation threads into subdirectories based on `Message-ID` and `Subject` headers.

**Why use this?**
The main scanner ignores mailbox container files such as `.mbox`, `.mbx`, and `.mbs`. Running this script first converts them into individual `.eml` files so the emails are indexed and searchable.

**Examples:**
```bash
# Preview what would be extracted without making changes
python -m src.scripts.extract_and_cleanup_mbox /path/to/mail --dry-run

# Extract all mailboxes and DELETE the original .mbox files (Standard usage)
python -m src.scripts.extract_and_cleanup_mbox /path/to/mail

# Extract mailboxes but KEEP the original files
python -m src.scripts.extract_and_cleanup_mbox /path/to/mail --keep
```

---

### 2. Archive Extractor (`extract_and_cleanup_archives.py`)
Recursively extracts compressed archives (`.zip`, `.tar.gz`, `.7z`, etc.) into nested folders and removes the original archive.

**Note on .7z Support:**
Extraction of `.7z` files requires the `archives` optional dependency (`uv add "file-catalog[archives]"`). If missing, the script will log a warning and skip `.7z` files.

**Examples:**
```bash
# Extract all archives in a directory recursively
python -m src.scripts.extract_and_cleanup_archives /path/to/archives

# Extract archives but keep the original compressed files
python -m src.scripts.extract_and_cleanup_archives /path/to/archives --keep
```

---

### 3. FTS Index Synchronizer (`sync_fts.py`)
Manually trigger a synchronization between the primary SQLite database and the Full-Text Search (FTS5) index for documents currently marked `DocumentStatus.COMPLETED`.

**Examples:**
```bash
# Synchronize documents in the COMPLETED state to the search index
python -m src.scripts.sync_fts
```

---

### 4. Performance Benchmarking (`perf_test_llms.py`)
Test the inference speed and memory consumption of configured LLM providers (`mlx`, `llama_cpp`, `gemini`) on your local hardware.

**Examples:**
```bash
# Benchmark the default provider
python -m src.scripts.perf_test_llms

# Benchmark a specific model path
python -m src.scripts.perf_test_llms --model-path "mlx-community/Meta-Llama-3.1-8B-Instruct-4bit"

---

### 5. Summary Evaluation (`evaluate_summaries.py`)
Uses an LLM-as-a-judge to evaluate the accuracy, coverage, and hallucination rate of generated document summaries by comparing them against the original extracted text.

**Examples:**
```bash
# Randomly sample 10 documents and evaluate their summaries
python -m src.scripts.evaluate_summaries --samples 10

# Save detailed evaluation results to a JSON file
python -m src.scripts.evaluate_summaries --samples 5 --output eval_results.json
```

---

### 6. Inspect File (`inspect_file.py`)
Retrieves and displays all database metadata and analysis results for a specific file in YAML format. If using iTerm2, it will also display a visual preview of the image or a video thumbnail.

**Example:**
```bash
python -m src.scripts.inspect_file "/path/to/your/document.pdf"
```
```

## General Usage Note
All scripts should be run from the root of the project using the `python -m src.scripts.<script_name>` syntax to ensure that internal imports and the `PYTHONPATH` are handled correctly.

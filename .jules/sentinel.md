## 2024-05-27 - [Title]
**Vulnerability:** SQL injection risks due to f-strings with `.like()`
**Learning:** Found several places using `.like(f"%{user_input}%")` in SQLModel
queries without escaping or parameterization. This pattern is vulnerable to SQL
injection and can also be flagged by static analysis tools. Memory instructions
recommend using `.contains(search_query, autoescape=True)` for substring
searches to ensure proper parameterization, handle automatic wildcard escaping,
and prevent SQL injection.
**Prevention:** Always use `.contains(user_input, autoescape=True)` instead of
`.like(f"%{user_input}%")` for substring search in SQLAlchemy/SQLModel.

## 2024-05-24 - Path Traversal in 7z Extraction
**Vulnerability:** The 7z extraction script was using `archive.extractall()`
which is vulnerable to path traversal attacks if the archive contains
malicious paths.
**Learning:** `py7zr` `extractall` does not have a safe filter option like
`tarfile` does. We need to manually extract only verified members. `py7zr`
uses `archive.list()` not `archive.get_files()`.
**Prevention:** Iterating over `archive.list()` and extracting specific targets
using `archive.extract(..., targets=[...])` is the safer approach for 7z files
in `py7zr`.

## 2024-10-02 - SQL Injection vulnerability in like statement
**Vulnerability:** Found `func.lower(Document.path).like("%.xml")` in `src/scripts/remove_xml_records.py`. This uses `.like()` with a hardcoded wildcard without parameterization.
**Learning:** For safely filtering by extensions or substrings without SQL injection vulnerability and complying with codebase security best practices, we should use `.endswith(".xml")` which automatically handles parameterization and wildcards safely inside SQLModel.
**Prevention:** Avoid using `.like()` directly for substring checks. Instead, use the built-in SQLAlchemy operators like `.endswith()`, `.contains()`, or `.startswith()`.

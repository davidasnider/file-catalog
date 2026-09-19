## 2024-05-24 - Path Traversal in 7z Extraction
**Vulnerability:** The 7z extraction script was using `archive.extractall()` which is vulnerable to path traversal attacks if the archive contains malicious paths.
**Learning:** `py7zr` `extractall` does not have a safe filter option like `tarfile` does. We need to manually extract only verified members.
**Prevention:** Iterating over `archive.get_files()` and extracting specific targets using `archive.extract(..., targets=[...])` is the safer approach for 7z files in `py7zr`.

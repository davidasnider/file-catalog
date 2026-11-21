## 2024-05-15 - Streamlit Accessibility and Empty States
**Learning:** Adding `help` parameters to Streamlit UI components (like
multiselects and columns) acts as accessible tooltips, significantly
improving the experience for users unsure about filter functionality.
Additionally, replacing generic "No documents found" messages with actionable
empty states (e.g., "Try adjusting your criteria in the sidebar") reduces
user frustration when filtering yields no results.
**Action:** Always provide `help` tooltips on interactive filters and ensure
empty states guide the user on how to resolve the empty condition.

## 2024-05-16 - Empty States and Warnings
**Learning:** Generic `st.info` messages for empty states (e.g., "No documents
found") lack visual prominence and clear indication that user action might be
required. Using `st.warning` instead draws more attention and better suits
situations where a filter yielded no results, prompting the user to adjust
their criteria. Adding context (like "It may still be processing") to empty
state messages prevents user confusion when data is temporarily missing.
**Action:** Use `st.warning` for empty states resulting from active filtering
to better highlight the need for user adjustment. Always provide helpful
context in empty state messages to explain *why* it might be empty (e.g.,
queueing, processing) rather than just stating that it *is* empty.

## 2024-06-25 - Streamlit Layout Constraints and State Management
**Learning:** Placing wide dataframes inside `st.sidebar` severely restricts
readability and creates a cramped UX. Following constraints to place tables in
the main view significantly improves data accessibility. Additionally,
providing feedback for actions that trigger a page reload (like clearing
cache) requires persisting a flag in `st.session_state` before `st.rerun()`,
then checking and clearing it at the top of the script to display an
`st.toast()`.
**Action:** Always place dataframes in the main layout and use
`st.session_state` for cross-rerun UI feedback.

## 2026-09-26 - Document Index Layout Consistency
**Learning:** Hiding structural UI elements like section headers (e.g.,
`st.subheader("Document Index")`) when the content beneath them is empty
(like a filtered-out dataframe) causes jarring layout shifts and context loss.
Users benefit from seeing the header remain in place, acting as an anchor, even
if the content below it is an empty state warning.
**Action:** Always render structural headers before evaluating conditional
logic that might early-return or display empty states, ensuring the layout
remains consistent regardless of filter results.

## 2026-10-17 - Selection Empty State Visibility
**Learning:** Using `st.info` for the primary selection prompt empty state ("Select a document from the table above...") is often overlooked by users because it blends in too much with the UI, especially when data is present in the table but nothing is selected. `st.warning` is more effective at drawing attention to actionable next steps when the detail view is empty.
**Action:** Use `st.warning` instead of `st.info` for empty states that require user action to populate the view, even if it's just selecting an item from a list.

## 2026-10-24 - Empty State Actionability
**Learning:** Using `st.write` or generic strings for empty states (like "No text extracted" or "No result data available") fails to provide users with actionable next steps or context on *why* the data is missing. Replacing these with `st.warning` visually draws the user's attention, and providing explicit context (e.g., "The task may still be processing" or "Try ensuring the file... requires OCR") significantly reduces user frustration and confusion.
**Action:** Always use `st.warning` for empty data states, and accompany the warning with specific context or troubleshooting steps explaining the absence of data.

## 2026-11-16 - CLI Surface Untouched by Earlier Runs
**Learning:** All prior Palette work targeted the Streamlit dashboard, but this repo's CLI (src/scanner.py plus the scripts in src/scripts/) is also an interface. Most of it is already well-behaved: bad directory paths are caught with logger.error, and inspect_file.py reports errors through a rich Console (stderr by default). src/scanner.py's missing-directory error was the lone offender, printing "Error:" plus full help to stdout; it is now on stderr (exit code 1 unchanged).
**Action:** If looking for more CLI candidates, try checklist B-6 (add an epilog with a real example to scanner.py --help) or raw value formatting in CLI output; verify whether errors already reach stderr before assuming they don't.

## 2026-11-21 - Exit code and stderr for bad-directory errors
**Learning:** `src/scripts/scan_text_failures.py` printed its "not a valid directory"
error to stdout (this repo's rich version defaults `Console()` to stdout) and returned,
exiting 0 — so a typo'd path looked like a successful scan. Fixed by adding the same
`parser.error(...)` guard in `main()` that `delete_duplicates.py` already uses (stderr,
exit 2). Note: an earlier journal entry called rich Console "stderr by default"; in the
installed version the default is stdout — scripts that look like they report errors via a
plain `Console()` may still be writing to stdout.
**Action:** Other directory-taking scripts were not re-audited for the same exit-0
pattern; check any script whose error path does `console.print(...)` + `return` before
assuming it signals failure correctly. The scanner.py --help epilog (B-6) is still an
open, known-good candidate.
